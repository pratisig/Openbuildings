"""Module Overture Maps — requêtes DuckDB sur S3.

Repris de `pratisig/openmapagents` (backend.py + agent.py, qui dupliquaient la
même logique). Ici : une seule définition des thèmes, paramètres validés
(plus d'injection SQL par f-string non contrôlée), cache mutualisé.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core import cache
from ..core.duckdb_engine import engine
from ..core.geo import BBox, centroid, point_in_polygon
from ..core.schemas import AreaOfInterest

log = logging.getLogger("pratisig.overture")
router = APIRouter(prefix="/api/overture", tags=["overture"])

CACHE_NS = "overture"

THEMES: dict[str, dict[str, Any]] = {
    "places": {
        "label": "Points d'intérêt",
        "type": "place",
        "columns": (
            "id, names.primary AS name, categories.primary AS category, confidence, "
            "ST_AsGeoJSON(geometry) AS geom_json"
        ),
        "filters": ["category", "name", "min_confidence"],
        "geometry": "Point",
    },
    "buildings": {
        "label": "Bâtiments",
        "type": "building",
        "columns": (
            "id, names.primary AS name, height, num_floors, class, subtype, "
            "ST_AsGeoJSON(geometry) AS geom_json"
        ),
        "filters": ["name", "min_height", "max_height", "class"],
        "geometry": "Polygon",
    },
    "transportation": {
        "label": "Réseau de transport",
        "type": "segment",
        "columns": "id, class, subtype, names.primary AS name, ST_AsGeoJSON(geometry) AS geom_json",
        "filters": ["name", "class"],
        "geometry": "LineString",
    },
    "divisions": {
        "label": "Divisions administratives",
        "type": "division_area",
        "columns": (
            "id, names.primary AS name, subtype, country, region, "
            "ST_AsGeoJSON(geometry) AS geom_json"
        ),
        "filters": ["name", "country"],
        "geometry": "Polygon",
    },
    "base": {
        "label": "Occupation du sol & eau",
        "type": "land_use",
        "columns": "id, class, subtype, names.primary AS name, ST_AsGeoJSON(geometry) AS geom_json",
        "filters": ["class"],
        "geometry": "Polygon",
    },
    "addresses": {
        "label": "Adresses",
        "type": "address",
        "columns": "id, number, street, postcode, country, ST_AsGeoJSON(geometry) AS geom_json",
        "filters": ["country"],
        "geometry": "Point",
    },
}


class OvertureQuery(BaseModel):
    theme: str = Field(..., description="places | buildings | transportation | divisions | base | addresses")
    area: AreaOfInterest
    category: str | None = None
    name: str | None = Field(None, description="Filtre nom, correspondance partielle")
    class_filter: str | None = Field(None, alias="class")
    country: str | None = Field(None, min_length=2, max_length=2)
    min_confidence: float | None = Field(None, ge=0, le=1)
    min_height: float | None = Field(None, ge=0)
    max_height: float | None = Field(None, ge=0)
    limit: int = Field(1_000, ge=1, le=50_000)
    clip_to_geometry: bool = True

    model_config = {"populate_by_name": True}


class OvertureStatsQuery(BaseModel):
    theme: str
    area: AreaOfInterest
    group_by: str | None = Field(None, description="Colonne d'agrégation, ex: category, class")
    limit: int = Field(25, ge=1, le=200)


def _escape(value: str) -> str:
    """Échappement SQL minimal pour littéraux chaîne."""
    return value.replace("'", "''")


def _theme_or_404(theme: str) -> dict[str, Any]:
    if theme not in THEMES:
        raise HTTPException(404, f"Thème inconnu '{theme}'. Disponibles : {list(THEMES)}")
    return THEMES[theme]


def _source_path(theme: str) -> str:
    ptype = THEMES[theme]["type"]
    return f"{settings.overture_release_path}/theme={theme}/type={ptype}/*"


def _bbox_clause(bbox: BBox, margin_deg: float = 0.5) -> str:
    """Filtre spatial permettant l'elagage des row-groups par DuckDB.

    Le motif « bbox.xmin <= xmax AND bbox.xmax >= xmin » est exact au sens
    de l'intersection, mais il laisse `bbox.xmin` sans borne inferieure :
    DuckDB ne peut alors ecarter aucun row-group a partir de ses statistiques
    min/max, et telecharge des giga-octets depuis S3 (delai depasse observe
    a 45 s sur une simple requete Dakar).

    On encadre donc chaque colonne des deux cotes, comme le fait la
    documentation Overture. La marge conserve les entites dont le coin
    inferieur gauche tombe hors de la zone alors que l'entite l'intersecte
    (grands polygones : batiments etendus, divisions administratives).
    """
    return (
        f"bbox.xmin BETWEEN {bbox.xmin - margin_deg} AND {bbox.xmax} "
        f"AND bbox.ymin BETWEEN {bbox.ymin - margin_deg} AND {bbox.ymax} "
        f"AND bbox.xmax >= {bbox.xmin} AND bbox.ymax >= {bbox.ymin}"
    )


@router.get("/themes", summary="Thèmes Overture disponibles")
def list_themes() -> dict[str, Any]:
    from ..services.overture_release import status as release_status

    return {
        "release": settings.overture_release,
        "release_info": release_status(),
        "themes": {
            key: {
                "id": key,
                "label": meta["label"],
                "type": meta["type"],
                "geometry": meta["geometry"],
                "filters": meta["filters"],
            }
            for key, meta in THEMES.items()
        },
    }


@router.post("/query", summary="Requêter un thème Overture")
def query_overture(payload: OvertureQuery) -> dict[str, Any]:
    meta = _theme_or_404(payload.theme)
    if not engine.available:
        raise HTTPException(503, "Moteur DuckDB indisponible sur ce déploiement")

    try:
        bbox = payload.area.resolve_bbox()
    except Exception as exc:
        raise HTTPException(400, f"Zone invalide : {exc}") from exc
    geometry = payload.area.geometry()

    where = [_bbox_clause(bbox)]
    if payload.category and payload.theme == "places":
        where.append(f"categories.primary = '{_escape(payload.category)}'")
    if payload.name:
        where.append(f"names.primary ILIKE '%{_escape(payload.name)}%'")
    if payload.class_filter:
        where.append(f"class = '{_escape(payload.class_filter)}'")
    if payload.country:
        where.append(f"country = '{_escape(payload.country.upper())}'")
    if payload.min_confidence is not None and payload.theme == "places":
        where.append(f"confidence >= {payload.min_confidence}")
    if payload.min_height is not None and payload.theme == "buildings":
        where.append(f"height >= {payload.min_height}")
    if payload.max_height is not None and payload.theme == "buildings":
        where.append(f"height <= {payload.max_height}")

    sql = f"""
        SELECT {meta['columns']}
        FROM read_parquet('{_source_path(payload.theme)}', hive_partitioning=1)
        WHERE {' AND '.join(where)}
        LIMIT {payload.limit}
    """

    key = cache.cache_key(sql, payload.clip_to_geometry, geometry)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        cached.setdefault("metadata", {})["cached"] = True
        return cached

    try:
        result = engine.query_geojson(sql)
    except Exception as exc:
        raise HTTPException(500, f"Erreur DuckDB : {exc}") from exc

    features = result["features"]
    if geometry is not None and payload.clip_to_geometry:
        kept = []
        for feat in features:
            try:
                lon, lat = centroid(feat["geometry"])
            except Exception:
                continue
            if point_in_polygon(lon, lat, geometry):
                kept.append(feat)
        features = kept

    response = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "theme": payload.theme,
            "label": meta["label"],
            "count": len(features),
            "bbox": bbox.to_list(),
            "release": settings.overture_release,
            "limit_reached": len(result["features"]) >= payload.limit,
            "cached": False,
        },
    }
    cache.set(CACHE_NS, key, response)
    return response


@router.post("/stats", summary="Statistiques agrégées d'un thème")
def overture_stats(payload: OvertureStatsQuery) -> dict[str, Any]:
    _theme_or_404(payload.theme)
    if not engine.available:
        raise HTTPException(503, "Moteur DuckDB indisponible sur ce déploiement")

    try:
        bbox = payload.area.resolve_bbox()
    except Exception as exc:
        raise HTTPException(400, f"Zone invalide : {exc}") from exc

    path = _source_path(payload.theme)
    clause = _bbox_clause(bbox)

    if payload.group_by:
        column = payload.group_by
        if not column.replace("_", "").replace(".", "").isalnum():
            raise HTTPException(400, "Nom de colonne invalide")
        if column == "category" and payload.theme == "places":
            column = "categories.primary"
        sql = f"""
            SELECT {column} AS valeur, COUNT(*) AS total
            FROM read_parquet('{path}', hive_partitioning=1)
            WHERE {clause}
            GROUP BY 1 ORDER BY total DESC LIMIT {payload.limit}
        """
    else:
        sql = f"""
            SELECT COUNT(*) AS total
            FROM read_parquet('{path}', hive_partitioning=1)
            WHERE {clause}
        """

    key = cache.cache_key("stats", sql)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        rows = engine.query_dicts(sql)
    except Exception as exc:
        raise HTTPException(500, f"Erreur DuckDB : {exc}") from exc

    result = {
        "theme": payload.theme,
        "bbox": bbox.to_list(),
        "area_km2": round(bbox.area_km2, 2),
        "group_by": payload.group_by,
        "rows": rows,
    }
    cache.set(CACHE_NS, key, result)
    return result
