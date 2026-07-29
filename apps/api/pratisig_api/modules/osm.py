"""Module OpenStreetMap — Overpass API côté serveur.

Reprend les gabarits de requêtes de `pratisig/city-roads` (src/lib/Query.js),
qui interrogeait Overpass depuis le navigateur, et remplace `osmnx` utilisé
dans `innondationSN` (dépendance lourde, lente, difficile à déployer).

Bénéfices : cache partagé, requêtes normalisées, sortie GeoJSON directe.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core import cache
from ..core.geo import BBox, feature, geometry_length_m
from ..core.http import UpstreamError, post_json
from ..core.schemas import AreaOfInterest

log = logging.getLogger("pratisig.osm")
router = APIRouter(prefix="/api/osm", tags=["osm"])

CACHE_NS = "osm"

# Gabarits repris de city-roads/src/lib/Query.js
PRESETS: dict[str, dict[str, Any]] = {
    "roads_all": {
        "label": "Toutes les routes",
        "filter": 'way["highway"]',
        "geometry": "LineString",
    },
    "roads_main": {
        "label": "Routes principales",
        "filter": 'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)(_link)?$"]',
        "geometry": "LineString",
    },
    "roads_strict": {
        "label": "Routes carrossables (strict)",
        "filter": (
            'way["highway"~"^(((motorway|trunk|primary|secondary|tertiary)(_link)?)'
            '|unclassified|residential|living_street|pedestrian|service|track)$"]["area"!="yes"]'
        ),
        "geometry": "LineString",
    },
    "buildings": {
        "label": "Bâtiments",
        "filter": 'way["building"]',
        "geometry": "Polygon",
    },
    "waterways": {
        "label": "Cours d'eau",
        "filter": 'way["waterway"]',
        "geometry": "LineString",
    },
    "water_bodies": {
        "label": "Plans d'eau",
        "filter": 'way["natural"="water"]',
        "geometry": "Polygon",
    },
    "health": {
        "label": "Structures de santé",
        "filter": 'nwr["amenity"~"^(hospital|clinic|doctors|pharmacy)$"]',
        "geometry": "Point",
    },
    "education": {
        "label": "Établissements scolaires",
        "filter": 'nwr["amenity"~"^(school|college|university|kindergarten)$"]',
        "geometry": "Point",
    },
    "markets": {
        "label": "Marchés et commerces",
        "filter": 'nwr["amenity"="marketplace"]',
        "geometry": "Point",
    },
    "landuse": {
        "label": "Occupation du sol",
        "filter": 'way["landuse"]',
        "geometry": "Polygon",
    },
}


class OSMQuery(BaseModel):
    preset: str | None = Field(None, description="Identifiant de gabarit, voir /api/osm/presets")
    custom_filter: str | None = Field(None, description="Filtre Overpass brut, ex: way[\"amenity\"=\"bank\"]")
    area: AreaOfInterest
    limit: int = Field(5_000, ge=1, le=50_000)
    timeout: int = Field(60, ge=10, le=180)


def _build_overpass(filter_expr: str, bbox: BBox, limit: int, timeout: int) -> str:
    bbox_str = f"{bbox.ymin},{bbox.xmin},{bbox.ymax},{bbox.xmax}"
    return f"""[out:json][timeout:{timeout}];
({filter_expr}({bbox_str}););
out geom {limit};"""


def _element_to_feature(element: dict[str, Any]) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    props = {"osm_id": element.get("id"), "osm_type": element.get("type"), **tags}
    etype = element.get("type")

    if etype == "node":
        if element.get("lat") is None:
            return None
        return feature({"type": "Point", "coordinates": [element["lon"], element["lat"]]}, props)

    geometry_nodes = element.get("geometry")
    if not geometry_nodes:
        if element.get("center"):
            c = element["center"]
            return feature({"type": "Point", "coordinates": [c["lon"], c["lat"]]}, props)
        return None

    coords = [[n["lon"], n["lat"]] for n in geometry_nodes if n.get("lon") is not None]
    if len(coords) < 2:
        return None

    is_closed = len(coords) >= 4 and coords[0] == coords[-1]
    is_area = is_closed and any(k in tags for k in ("building", "landuse", "natural", "amenity", "leisure"))
    if is_area:
        return feature({"type": "Polygon", "coordinates": [coords]}, props)
    return feature({"type": "LineString", "coordinates": coords}, props)


@router.get("/presets", summary="Gabarits de requêtes OSM disponibles")
def list_presets() -> dict[str, Any]:
    return {
        "presets": [{"id": key, **{k: v for k, v in meta.items()}} for key, meta in PRESETS.items()],
        "count": len(PRESETS),
        "endpoint": settings.overpass_url,
    }


@router.post("/query", summary="Extraire des données OSM par zone")
async def query_osm(payload: OSMQuery) -> dict[str, Any]:
    if not payload.preset and not payload.custom_filter:
        raise HTTPException(400, "Fournir `preset` ou `custom_filter`")
    if payload.preset and payload.preset not in PRESETS:
        raise HTTPException(404, f"Gabarit inconnu. Disponibles : {list(PRESETS)}")

    filter_expr = payload.custom_filter or PRESETS[payload.preset]["filter"]
    try:
        bbox = payload.area.resolve_bbox()
    except Exception as exc:
        raise HTTPException(400, f"Zone invalide : {exc}") from exc

    if bbox.area_km2 > 10_000:
        raise HTTPException(
            400,
            f"Zone trop vaste ({bbox.area_km2:.0f} km²). Overpass limite à ~10 000 km² par requête.",
        )

    query = _build_overpass(filter_expr, bbox, payload.limit, payload.timeout)
    key = cache.cache_key(query)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        cached.setdefault("metadata", {})["cached"] = True
        return cached

    try:
        raw = await post_json("overpass", settings.overpass_url, data={"data": query})
    except UpstreamError as exc:
        raise HTTPException(exc.status_code, f"Overpass : {exc.detail}") from exc

    features = [f for f in (_element_to_feature(e) for e in raw.get("elements", [])) if f]
    response = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "preset": payload.preset,
            "count": len(features),
            "bbox": bbox.to_list(),
            "area_km2": round(bbox.area_km2, 2),
            "source": "OpenStreetMap (ODbL) via Overpass",
            "cached": False,
        },
    }
    cache.set(CACHE_NS, key, response)
    return response


@router.post("/roads", summary="Réseau routier avec longueurs (mode city-roads)")
async def roads(payload: OSMQuery) -> dict[str, Any]:
    """Extraction du réseau routier avec statistiques par classe."""
    payload.preset = payload.preset or "roads_strict"
    result = await query_osm(payload)

    by_class: dict[str, dict[str, float]] = {}
    total_length = 0.0
    for feat in result["features"]:
        highway = feat["properties"].get("highway", "inconnu")
        length = geometry_length_m(feat["geometry"])
        feat["properties"]["length_m"] = round(length, 1)
        total_length += length
        entry = by_class.setdefault(highway, {"count": 0, "length_m": 0.0})
        entry["count"] += 1
        entry["length_m"] += length

    for entry in by_class.values():
        entry["length_km"] = round(entry["length_m"] / 1000, 2)
        entry["length_m"] = round(entry["length_m"], 1)

    result["metadata"]["total_length_km"] = round(total_length / 1000, 2)
    result["metadata"]["by_class"] = dict(
        sorted(by_class.items(), key=lambda kv: kv[1]["length_m"], reverse=True)
    )
    return result
