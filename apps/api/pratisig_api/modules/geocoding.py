"""Module de géocodage — Nominatim mutualisé.

Avant : `agent.py` appelait Nominatim en direct, `city-roads` le faisait côté
navigateur, `floodingsn` codait en dur les coordonnées des pays. Ici un seul
service, avec cache disque (Nominatim impose une politique d'usage stricte).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..config import settings
from ..core import cache
from ..core.http import UpstreamError, get_json

router = APIRouter(prefix="/api/geocoding", tags=["geocodage"])

CACHE_NS = "geocoding"


def _format_result(item: dict[str, Any]) -> dict[str, Any]:
    bbox = item.get("boundingbox") or []
    formatted: dict[str, Any] = {
        "display_name": item.get("display_name", ""),
        "latitude": float(item["lat"]),
        "longitude": float(item["lon"]),
        "type": item.get("type", ""),
        "category": item.get("class", ""),
        "importance": item.get("importance"),
        "osm_type": item.get("osm_type"),
        "osm_id": item.get("osm_id"),
    }
    if len(bbox) == 4:
        # Nominatim : [south, north, west, east] → [xmin, ymin, xmax, ymax]
        formatted["bbox"] = [float(bbox[2]), float(bbox[0]), float(bbox[3]), float(bbox[1])]
    if item.get("address"):
        formatted["address"] = item["address"]
    if item.get("geojson"):
        formatted["geojson"] = item["geojson"]
    return formatted


@router.get("/search", summary="Rechercher un lieu")
async def search(
    q: str = Query(..., min_length=2, description="Nom de lieu, adresse ou point d'intérêt"),
    limit: int = Query(5, ge=1, le=20),
    country: str | None = Query(None, description="Filtre pays, codes ISO2 séparés par virgule"),
    with_geometry: bool = Query(False, description="Inclure la géométrie du lieu"),
) -> dict[str, Any]:
    key = cache.cache_key("search", q, limit, country, with_geometry)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    params: dict[str, Any] = {
        "q": q,
        "format": "json",
        "limit": limit,
        "addressdetails": 1,
    }
    if country:
        params["countrycodes"] = country.lower()
    if with_geometry:
        params["polygon_geojson"] = 1

    try:
        raw = await get_json("nominatim", f"{settings.nominatim_url}/search", params=params)
    except UpstreamError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    result = {"query": q, "results": [_format_result(item) for item in raw], "count": len(raw)}
    cache.set(CACHE_NS, key, result)
    return result


@router.get("/reverse", summary="Géocodage inverse")
async def reverse(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    zoom: int = Query(14, ge=0, le=18),
) -> dict[str, Any]:
    key = cache.cache_key("reverse", round(lat, 5), round(lon, 5), zoom)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        raw = await get_json(
            "nominatim",
            f"{settings.nominatim_url}/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": zoom, "addressdetails": 1},
        )
    except UpstreamError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    if "error" in raw:
        raise HTTPException(404, "Aucun lieu trouvé à ces coordonnées")

    result = _format_result(raw)
    cache.set(CACHE_NS, key, result)
    return result


async def geocode_one(query: str) -> dict[str, Any] | None:
    """Helper interne réutilisé par l'agent et le module routing."""
    try:
        payload = await search(q=query, limit=1, country=None, with_geometry=False)
    except HTTPException:
        return None
    results = payload.get("results") or []
    return results[0] if results else None
