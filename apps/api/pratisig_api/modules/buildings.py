"""Module Open Buildings — Google + Microsoft (dataset VIDA).

Fusion de `pratisig/Openbuildings` (Streamlit, GeoParquet par pays) et
`pratisig/openbuildings_app` (sélection WKT, tuiles S2 v3).

Apports par rapport aux deux originaux :
  * requête DuckDB avec pushdown du bbox → on ne télécharge plus le parquet
    complet d'un pays (plusieurs Go) pour n'en garder qu'un quartier ;
  * découpe possible par polygone GeoJSON, pas seulement par bbox ;
  * filtre de confiance et limite de features ;
  * réponse GeoJSON standard réutilisable par n'importe quel client.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core import cache
from ..core.duckdb_engine import engine
from ..core.geo import BBox, geometry_area_m2, point_in_polygon
from ..core.schemas import AreaOfInterest

log = logging.getLogger("pratisig.buildings")
router = APIRouter(prefix="/api/buildings", tags=["batiments"])

CACHE_NS = "buildings"
COUNTRIES_FILE = settings.data_dir / "reference" / "countries.geojson"


class BuildingsQuery(BaseModel):
    country_iso3: str = Field(..., min_length=3, max_length=3, description="Code ISO3, ex: SEN")
    area: AreaOfInterest | None = Field(None, description="Restriction spatiale dans le pays")
    min_confidence: float = Field(0.0, ge=0.0, le=1.0)
    min_area_m2: float = Field(0.0, ge=0.0)
    limit: int = Field(5_000, ge=1, le=200_000)
    clip_to_geometry: bool = Field(True, description="Découper au polygone exact si fourni")


class BuildingsStatsQuery(BaseModel):
    country_iso3: str = Field(..., min_length=3, max_length=3)
    area: AreaOfInterest | None = None
    min_confidence: float = Field(0.0, ge=0.0, le=1.0)


def _parquet_url(iso3: str) -> str:
    iso3 = iso3.upper()
    return f"{settings.open_buildings_base}/country_iso={iso3}/{iso3}.parquet"


def _load_countries() -> list[dict[str, Any]]:
    """Liste des pays de référence (fichier local hérité de Openbuildings)."""

    def produce() -> list[dict[str, Any]]:
        if not COUNTRIES_FILE.exists():
            log.warning("countries.geojson absent (%s)", COUNTRIES_FILE)
            return []
        try:
            data = json.loads(COUNTRIES_FILE.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Lecture countries.geojson impossible: %s", exc)
            return []

        countries: list[dict[str, Any]] = []
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            iso3 = (
                props.get("ISO3166-1-Alpha-3")
                or props.get("ISO_A3")
                or props.get("iso_a3")
                or props.get("adm0_a3")
            )
            name = props.get("name") or props.get("NAME") or props.get("admin")
            if not iso3 or not name or str(iso3).lower() in ("nan", "none", "-99"):
                continue
            entry: dict[str, Any] = {"iso3": str(iso3).upper().strip(), "name": str(name).strip()}
            iso2 = props.get("ISO3166-1-Alpha-2") or props.get("ISO_A2")
            if iso2 and str(iso2).lower() not in ("nan", "none", "-99"):
                entry["iso2"] = str(iso2).upper().strip()
            geom = feat.get("geometry")
            if geom:
                try:
                    entry["bbox"] = BBox.from_geojson(geom).to_list()
                except Exception:
                    pass
            countries.append(entry)
        countries.sort(key=lambda c: c["name"])
        return countries

    return cache.memoize(CACHE_NS, "countries-index", produce, ttl=0)


# Schema reel du GeoParquet VIDA, releve le 29/07/2026 sur le fichier SEN :
#   boundary_id BIGINT · bf_source VARCHAR · confidence DOUBLE
#   area_in_meters DOUBLE · s2_id BIGINT · country_iso VARCHAR
#   geohash VARCHAR · geometry GEOMETRY · bbox STRUCT(xmin, ymin, xmax, ymax)
# La cle primaire est `boundary_id`, pas `id` : interroger `id` provoquait
# un « Binder Error » et rendait tout le module inutilisable.
BUILDINGS_COLUMNS = (
    "boundary_id", "bf_source", "confidence", "area_in_meters",
    "s2_id", "country_iso", "geohash", "geometry", "bbox",
)


def _bbox_clause(bbox: BBox, margin_deg: float = 0.05) -> str:
    """Filtre spatial permettant l'elagage des row-groups par DuckDB.

    Encadrer chaque colonne des deux cotes est indispensable : sans borne
    inferieure, `bbox.xmin <= xmax` laisse passer tous les row-groups situes
    a l'ouest de la zone et DuckDB telecharge le pays entier.

    La marge est plus faible que pour Overture : les empreintes de batiments
    depassent rarement quelques dizaines de metres.
    """
    return (
        f"bbox.xmin BETWEEN {bbox.xmin - margin_deg} AND {bbox.xmax} "
        f"AND bbox.ymin BETWEEN {bbox.ymin - margin_deg} AND {bbox.ymax} "
        f"AND bbox.xmax >= {bbox.xmin} AND bbox.ymax >= {bbox.ymin}"
    )


def _build_sql(iso3: str, bbox: BBox | None, min_confidence: float, min_area: float, limit: int) -> str:
    where: list[str] = []
    if bbox is not None:
        # Pushdown : DuckDB n'ouvre que les row-groups intersectant la bbox.
        where.append(_bbox_clause(bbox))
    if min_confidence > 0:
        where.append(f"confidence >= {min_confidence}")
    if min_area > 0:
        where.append(f"area_in_meters >= {min_area}")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return f"""
        SELECT
            boundary_id AS id,
            confidence,
            area_in_meters,
            bf_source AS source,
            s2_id,
            ST_AsGeoJSON(geometry) AS geom_json
        FROM read_parquet('{_parquet_url(iso3)}')
        {clause}
        LIMIT {limit}
    """


@router.get("/countries", summary="Pays couverts par le dataset")
def list_countries(q: str | None = None) -> dict[str, Any]:
    countries = _load_countries()
    if q:
        needle = q.lower()
        countries = [c for c in countries if needle in c["name"].lower() or needle in c["iso3"].lower()]
    return {
        "countries": countries,
        "count": len(countries),
        "source": "VIDA Google-Microsoft Open Buildings",
        "note": "Couverture réelle : Afrique, Asie du Sud/Sud-Est, Amérique latine, Caraïbes.",
    }


@router.get("/countries/{iso3}", summary="Métadonnées d'un pays")
def country_detail(iso3: str) -> dict[str, Any]:
    iso3 = iso3.upper()
    match = next((c for c in _load_countries() if c["iso3"] == iso3), None)
    if match is None:
        raise HTTPException(404, f"Pays inconnu : {iso3}")
    return {**match, "parquet_url": _parquet_url(iso3)}


@router.post("/query", summary="Extraire les empreintes de bâtiments")
def query_buildings(payload: BuildingsQuery) -> dict[str, Any]:
    if not engine.available:
        raise HTTPException(503, "Moteur DuckDB indisponible sur ce déploiement")

    iso3 = payload.country_iso3.upper()
    bbox: BBox | None = None
    geometry: dict[str, Any] | None = None

    if payload.area is not None:
        try:
            bbox = payload.area.resolve_bbox()
        except Exception as exc:
            raise HTTPException(400, f"Zone invalide : {exc}") from exc
        geometry = payload.area.geometry()

    sql = _build_sql(iso3, bbox, payload.min_confidence, payload.min_area_m2, payload.limit)
    key = cache.cache_key(sql, payload.clip_to_geometry, geometry)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        cached.setdefault("metadata", {})["cached"] = True
        return cached

    try:
        result = engine.query_geojson(sql)
    except Exception as exc:
        detail = str(exc)
        if "HTTP" in detail or "404" in detail:
            raise HTTPException(
                404,
                f"Le pays '{iso3}' n'est pas disponible dans le dataset Open Buildings.",
            ) from exc
        raise HTTPException(500, f"Erreur DuckDB : {detail}") from exc

    features = result["features"]

    # Découpe exacte au polygone (le pushdown bbox est rectangulaire)
    if geometry is not None and payload.clip_to_geometry:
        from ..core.geo import centroid

        kept = []
        for feat in features:
            try:
                lon, lat = centroid(feat["geometry"])
            except Exception:
                continue
            if point_in_polygon(lon, lat, geometry):
                kept.append(feat)
        features = kept

    total_area = sum(
        (f["properties"].get("area_in_meters") or geometry_area_m2(f["geometry"]))
        for f in features
    )

    response = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "country_iso3": iso3,
            "count": len(features),
            "total_area_m2": round(total_area, 2),
            "bbox": bbox.to_list() if bbox else None,
            "min_confidence": payload.min_confidence,
            "limit_reached": len(result["features"]) >= payload.limit,
            "source": "VIDA Google-Microsoft Open Buildings",
            "cached": False,
        },
    }
    cache.set(CACHE_NS, key, response)
    return response


@router.post("/stats", summary="Statistiques agrégées sans télécharger les géométries")
def buildings_stats(payload: BuildingsStatsQuery) -> dict[str, Any]:
    if not engine.available:
        raise HTTPException(503, "Moteur DuckDB indisponible sur ce déploiement")

    iso3 = payload.country_iso3.upper()
    where: list[str] = []
    bbox: BBox | None = None
    if payload.area is not None:
        try:
            bbox = payload.area.resolve_bbox()
        except Exception as exc:
            raise HTTPException(400, f"Zone invalide : {exc}") from exc
        where.append(_bbox_clause(bbox))
    if payload.min_confidence > 0:
        where.append(f"confidence >= {payload.min_confidence}")
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
        SELECT
            COUNT(*)                AS total,
            SUM(area_in_meters)     AS surface_totale_m2,
            AVG(area_in_meters)     AS surface_moyenne_m2,
            MEDIAN(area_in_meters)  AS surface_mediane_m2,
            AVG(confidence)         AS confiance_moyenne,
            MIN(confidence)         AS confiance_min,
            MAX(confidence)         AS confiance_max
        FROM read_parquet('{_parquet_url(iso3)}')
        {clause}
    """
    key = cache.cache_key("stats", sql)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        rows = engine.query_dicts(sql)
    except Exception as exc:
        raise HTTPException(500, f"Erreur DuckDB : {exc}") from exc

    stats = rows[0] if rows else {}
    result = {
        "country_iso3": iso3,
        "bbox": bbox.to_list() if bbox else None,
        "stats": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()},
        "density_per_km2": (
            round((stats.get("total") or 0) / bbox.area_km2, 2)
            if bbox and bbox.area_km2 > 0
            else None
        ),
    }
    cache.set(CACHE_NS, key, result)
    return result
