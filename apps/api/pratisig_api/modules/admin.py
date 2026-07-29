"""Module découpage administratif — sélection de zone unifiée.

Rassemble trois approches qui coexistaient :
  * `Carto-facileSN` : shapefiles IGN Sénégal, 4 niveaux (Flask + cache maison) ;
  * `floodingsn` / `innondationSN` : GADM 4.1 chargé à la volée par pays ;
  * `Openbuildings` : countries.geojson local pour la liste des pays.

Objectif : un seul endroit pour répondre à « quelle est ma zone d'étude ? ».
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..core import cache
from ..core.geo import BBox, centroid, geometry_area_m2
from ..core.http import UpstreamError, get_json

log = logging.getLogger("pratisig.admin")
router = APIRouter(prefix="/api/admin", tags=["administratif"])

CACHE_NS = "admin"

# Pays d'Afrique de l'Ouest prioritaires (hérité de floodingsn / innondationSN)
FOCUS_COUNTRIES = {
    "SEN": "Sénégal",
    "MLI": "Mali",
    "BFA": "Burkina Faso",
    "NER": "Niger",
    "MRT": "Mauritanie",
    "GMB": "Gambie",
    "GNB": "Guinée-Bissau",
    "GIN": "Guinée",
    "CIV": "Côte d'Ivoire",
    "GHA": "Ghana",
    "TGO": "Togo",
    "BEN": "Bénin",
    "NGA": "Nigeria",
}

# Niveaux administratifs du Sénégal (nomenclature Carto-facileSN)
SENEGAL_LEVELS = {
    "regions": {"gadm_level": 1, "label": "Régions", "expected": 14},
    "departements": {"gadm_level": 2, "label": "Départements", "expected": 46},
    "arrondissements": {"gadm_level": 3, "label": "Arrondissements", "expected": 133},
    "communes": {"gadm_level": 4, "label": "Communes", "expected": 557},
}


def _countries_index() -> list[dict[str, Any]]:
    from .buildings import _load_countries

    return _load_countries()


def _gadm_url(iso3: str, level: int) -> str:
    return f"{settings.gadm_base_url}/gadm41_{iso3.upper()}_{level}.json"


def _simplify_properties(props: dict[str, Any], level: int) -> dict[str, Any]:
    """Normalise les propriétés GADM en champs stables pour le front."""
    name = props.get(f"NAME_{level}") or props.get("COUNTRY") or ""
    out: dict[str, Any] = {
        "code": props.get(f"GID_{level}") or props.get("GID_0") or "",
        "name": name,
        "level": level,
        "country": props.get("COUNTRY", ""),
        "type": props.get(f"ENGTYPE_{level}") or props.get(f"TYPE_{level}") or "",
    }
    for parent in range(0, level):
        parent_name = props.get(f"NAME_{parent}") if parent > 0 else props.get("COUNTRY")
        if parent_name:
            out[f"parent_{parent}"] = parent_name
            out[f"parent_{parent}_code"] = props.get(f"GID_{parent}", "")
    return out


async def _load_gadm(iso3: str, level: int, with_geometry: bool = True) -> dict[str, Any]:
    iso3 = iso3.upper()
    if level < 0 or level > 5:
        raise HTTPException(400, "Niveau administratif attendu entre 0 et 5")

    key = cache.cache_key("gadm", iso3, level, with_geometry)
    cached = cache.get(CACHE_NS, key, ttl=0)
    if cached is not None:
        return cached

    try:
        raw = await get_json("gadm", _gadm_url(iso3, level))
    except UpstreamError as exc:
        if exc.status_code == 404:
            raise HTTPException(
                404,
                f"Niveau {level} indisponible pour {iso3} dans GADM 4.1.",
            ) from exc
        raise HTTPException(exc.status_code, f"GADM : {exc.detail}") from exc

    features: list[dict[str, Any]] = []
    for feat in raw.get("features", []):
        props = _simplify_properties(feat.get("properties") or {}, level)
        geom = feat.get("geometry")
        if geom:
            try:
                props["bbox"] = BBox.from_geojson(geom).to_list()
                lon, lat = centroid(geom)
                props["centroid"] = [round(lon, 6), round(lat, 6)]
                props["area_km2"] = round(geometry_area_m2(geom) / 1e6, 2)
            except Exception:
                pass
        features.append(
            {"type": "Feature", "properties": props, "geometry": geom if with_geometry else None}
        )

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "country_iso3": iso3,
            "level": level,
            "count": len(features),
            "source": "GADM 4.1",
            "with_geometry": with_geometry,
        },
    }
    cache.set(CACHE_NS, key, result)
    return result


@router.get("/countries", summary="Liste des pays")
def countries(focus: bool = Query(False, description="Limiter à l'Afrique de l'Ouest")) -> dict[str, Any]:
    all_countries = _countries_index()
    if focus:
        items = [c for c in all_countries if c["iso3"] in FOCUS_COUNTRIES]
        if not items:
            items = [{"iso3": k, "name": v} for k, v in FOCUS_COUNTRIES.items()]
    else:
        items = all_countries
    return {"countries": items, "count": len(items), "focus": focus}


@router.get("/gadm/{iso3}/{level}", summary="Limites administratives GADM")
async def gadm(
    iso3: str,
    level: int,
    with_geometry: bool = Query(True),
    parent_code: str | None = Query(None, description="Filtrer par code GADM parent, ex: SEN.1_1"),
) -> dict[str, Any]:
    result = await _load_gadm(iso3, level, with_geometry)
    if parent_code:
        filtered = [
            f
            for f in result["features"]
            if any(
                str(v).startswith(parent_code)
                for k, v in f["properties"].items()
                if k.startswith("parent_") and k.endswith("_code")
            )
        ]
        result = {**result, "features": filtered}
        result["metadata"] = {**result["metadata"], "count": len(filtered), "parent_code": parent_code}
    return result


@router.get("/senegal/{niveau}", summary="Découpage administratif du Sénégal")
async def senegal(
    niveau: str,
    with_geometry: bool = Query(True),
    parent_code: str | None = Query(None),
) -> dict[str, Any]:
    """Niveaux : regions | departements | arrondissements | communes."""
    if niveau not in SENEGAL_LEVELS:
        raise HTTPException(404, f"Niveau inconnu. Disponibles : {list(SENEGAL_LEVELS)}")
    meta = SENEGAL_LEVELS[niveau]
    result = await gadm("SEN", meta["gadm_level"], with_geometry, parent_code)
    result["metadata"]["niveau"] = niveau
    result["metadata"]["label"] = meta["label"]
    result["metadata"]["expected_count"] = meta["expected"]
    return result


@router.get("/senegal", summary="Niveaux administratifs sénégalais disponibles")
def senegal_levels() -> dict[str, Any]:
    return {
        "country": "Sénégal",
        "iso3": "SEN",
        "levels": [{"id": key, **meta} for key, meta in SENEGAL_LEVELS.items()],
    }


@router.get("/resolve", summary="Résoudre un code administratif en zone")
async def resolve(code: str = Query(..., description="Code GADM (ex: SEN.1.2_1) ou ISO3")) -> dict[str, Any]:
    """Retourne bbox + géométrie d'une entité administrative, pour alimenter les autres modules."""
    parts = code.split(".")
    iso3 = parts[0].split("_")[0].upper()
    level = len(parts) - 1 if len(parts) > 1 else 0

    result = await _load_gadm(iso3, level, with_geometry=True)
    for feat in result["features"]:
        if feat["properties"].get("code") == code:
            return {
                "code": code,
                "name": feat["properties"].get("name"),
                "level": level,
                "bbox": feat["properties"].get("bbox"),
                "centroid": feat["properties"].get("centroid"),
                "area_km2": feat["properties"].get("area_km2"),
                "geometry": feat["geometry"],
            }
    raise HTTPException(404, f"Code administratif introuvable : {code}")
