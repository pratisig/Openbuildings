"""Module itinéraires & accessibilité.

Unifie trois besoins qui existaient séparément :
  * `GeoRouteX` (plugin QGIS) : plus court chemin sur réseau — devient un service web ;
  * `openmapagents` : routes et isochrones via l'API Mapbox (clé payante requise) ;
  * `sante-isochrones-app` : accessibilité aux structures de santé.

Choix technique : OSRM public (sans clé API) plutôt que Mapbox, avec repli
sur une isochrone approximée par cercle géodésique si le service est absent.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core import cache
from ..core.geo import circle_polygon, haversine_m
from ..core.http import UpstreamError, get_json

log = logging.getLogger("pratisig.routing")
router = APIRouter(prefix="/api/routing", tags=["routage"])

CACHE_NS = "routing"

PROFILES: dict[str, dict[str, Any]] = {
    "foot": {"osrm": "foot", "label": "À pied", "speed_kmh": 4.5},
    "bike": {"osrm": "bike", "label": "Vélo", "speed_kmh": 15.0},
    "car": {"osrm": "car", "label": "Voiture", "speed_kmh": 50.0},
}

Profile = Literal["foot", "bike", "car"]


class RouteRequest(BaseModel):
    waypoints: list[list[float]] = Field(..., min_length=2, max_length=25)
    profile: Profile = "car"
    steps: bool = Field(False, description="Inclure les instructions détaillées")
    alternatives: bool = False


class IsochroneRequest(BaseModel):
    center: list[float] = Field(..., min_length=2, max_length=2)
    minutes: list[int] = Field(default_factory=lambda: [5, 10, 15], max_length=5)
    profile: Profile = "foot"


class AccessibilityRequest(BaseModel):
    """Accessibilité : quels équipements sont atteignables depuis chaque origine."""

    origins: list[list[float]] = Field(..., min_length=1, max_length=100)
    facilities: dict[str, Any] = Field(..., description="FeatureCollection des équipements")
    max_minutes: int = Field(30, ge=1, le=180)
    profile: Profile = "car"


def _validate_point(point: list[float], label: str) -> tuple[float, float]:
    if len(point) != 2:
        raise HTTPException(400, f"{label} : attendu [longitude, latitude]")
    lon, lat = float(point[0]), float(point[1])
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise HTTPException(400, f"{label} : coordonnées hors bornes")
    return lon, lat


@router.get("/profiles", summary="Modes de déplacement disponibles")
def profiles() -> dict[str, Any]:
    return {
        "profiles": [{"id": key, **meta} for key, meta in PROFILES.items()],
        "engine": settings.osrm_url,
    }


@router.post("/route", summary="Calculer un itinéraire")
async def route(payload: RouteRequest) -> dict[str, Any]:
    points = [_validate_point(p, f"waypoint {i}") for i, p in enumerate(payload.waypoints)]
    coords = ";".join(f"{lon},{lat}" for lon, lat in points)
    profile = PROFILES[payload.profile]["osrm"]

    key = cache.cache_key("route", coords, profile, payload.steps, payload.alternatives)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    url = f"{settings.osrm_url}/route/v1/{profile}/{coords}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true" if payload.steps else "false",
        "alternatives": "true" if payload.alternatives else "false",
    }

    try:
        raw = await get_json("osrm", url, params=params)
    except UpstreamError as exc:
        raise HTTPException(exc.status_code, f"Service de routage : {exc.detail}") from exc

    if raw.get("code") != "Ok" or not raw.get("routes"):
        raise HTTPException(422, f"Aucun itinéraire trouvé ({raw.get('message', raw.get('code'))})")

    features = []
    for idx, r in enumerate(raw["routes"]):
        props: dict[str, Any] = {
            "index": idx,
            "primary": idx == 0,
            "distance_m": round(r["distance"], 1),
            "distance_km": round(r["distance"] / 1000, 2),
            "duration_s": round(r["duration"], 1),
            "duration_min": round(r["duration"] / 60, 1),
            "profile": payload.profile,
        }
        if payload.steps:
            props["steps"] = [
                {
                    "instruction": s.get("maneuver", {}).get("type", ""),
                    "modifier": s.get("maneuver", {}).get("modifier"),
                    "name": s.get("name", ""),
                    "distance_m": round(s.get("distance", 0), 1),
                    "duration_s": round(s.get("duration", 0), 1),
                }
                for leg in r.get("legs", [])
                for s in leg.get("steps", [])
            ]
        features.append({"type": "Feature", "geometry": r["geometry"], "properties": props})

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "profile": payload.profile,
            "waypoints": len(points),
            "routes": len(features),
            "engine": "OSRM",
        },
    }
    cache.set(CACHE_NS, key, result)
    return result


@router.post("/isochrone", summary="Zones d'accessibilité (isochrones)")
async def isochrone(payload: IsochroneRequest) -> dict[str, Any]:
    """Isochrone par échantillonnage de la matrice de temps OSRM.

    On tire des points sur des rayons autour du centre, on interroge OSRM en
    une seule requête `table`, puis on relie les points atteignables dans le
    temps imparti. Si OSRM est indisponible, repli sur un cercle basé sur la
    vitesse moyenne du mode (résultat approximatif, signalé dans metadata).
    """
    lon, lat = _validate_point(payload.center, "center")
    minutes = sorted({m for m in payload.minutes if 0 < m <= 120})
    if not minutes:
        raise HTTPException(400, "Fournir au moins une durée entre 1 et 120 minutes")

    profile_meta = PROFILES[payload.profile]
    key = cache.cache_key("isochrone", round(lon, 5), round(lat, 5), tuple(minutes), payload.profile)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    max_minutes = max(minutes)
    max_radius_m = profile_meta["speed_kmh"] * 1000 / 60 * max_minutes * 1.1

    import math

    bearings = 24
    rings = 6
    samples: list[tuple[float, float]] = []
    for r_idx in range(1, rings + 1):
        radius = max_radius_m * r_idx / rings
        for b_idx in range(bearings):
            angle = 2 * math.pi * b_idx / bearings
            dlat = (radius * math.sin(angle)) / 110_574.0
            dlon = (radius * math.cos(angle)) / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
            samples.append((lon + dlon, lat + dlat))

    durations: list[float] | None = None
    engine_used = "OSRM"
    try:
        coords = ";".join(f"{x},{y}" for x, y in [(lon, lat), *samples])
        raw = await get_json(
            "osrm",
            f"{settings.osrm_url}/table/v1/{profile_meta['osrm']}/{coords}",
            params={"sources": "0", "annotations": "duration"},
        )
        if raw.get("code") == "Ok" and raw.get("durations"):
            durations = raw["durations"][0][1:]
    except UpstreamError as exc:
        log.warning("Matrice OSRM indisponible, repli géométrique : %s", exc)

    features: list[dict[str, Any]] = []
    if durations:
        for m in minutes:
            limit_s = m * 60
            reachable = [
                samples[i]
                for i, d in enumerate(durations)
                if d is not None and d <= limit_s
            ]
            if len(reachable) < 3:
                radius = profile_meta["speed_kmh"] * 1000 / 60 * m
                geom = circle_polygon(lon, lat, radius)
            else:
                geom = _hull_polygon(lon, lat, reachable)
            features.append(
                {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {
                        "minutes": m,
                        "profile": payload.profile,
                        "sample_points": len(reachable),
                    },
                }
            )
    else:
        engine_used = "approximation géodésique"
        for m in minutes:
            radius = profile_meta["speed_kmh"] * 1000 / 60 * m
            features.append(
                {
                    "type": "Feature",
                    "geometry": circle_polygon(lon, lat, radius),
                    "properties": {
                        "minutes": m,
                        "profile": payload.profile,
                        "radius_m": round(radius),
                        "approximate": True,
                    },
                }
            )

    # Ordre décroissant : les grandes zones dessous
    features.sort(key=lambda f: f["properties"]["minutes"], reverse=True)

    result = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "center": [lon, lat],
            "profile": payload.profile,
            "minutes": minutes,
            "engine": engine_used,
            "approximate": engine_used != "OSRM",
        },
    }
    cache.set(CACHE_NS, key, result)
    return result


def _hull_polygon(lon: float, lat: float, points: list[tuple[float, float]]) -> dict[str, Any]:
    """Enveloppe convexe (marche de Jarvis) des points atteignables."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return circle_polygon(lon, lat, 200)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    ring = lower[:-1] + upper[:-1]
    if len(ring) < 3:
        return circle_polygon(lon, lat, 200)
    coords = [[x, y] for x, y in ring]
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


@router.post("/accessibility", summary="Accessibilité aux équipements")
async def accessibility(payload: AccessibilityRequest) -> dict[str, Any]:
    """Pour chaque origine, l'équipement le plus proche et son temps de trajet.

    Cas d'usage direct : accès aux structures de santé, aux écoles, aux marchés.
    """
    origins = [_validate_point(o, f"origine {i}") for i, o in enumerate(payload.origins)]

    facility_points: list[tuple[float, float, dict[str, Any]]] = []
    for feat in payload.facilities.get("features", []):
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Point":
            c = geom["coordinates"]
            facility_points.append((float(c[0]), float(c[1]), feat.get("properties") or {}))
        else:
            try:
                from ..core.geo import centroid as geom_centroid

                cx, cy = geom_centroid(geom)
                facility_points.append((cx, cy, feat.get("properties") or {}))
            except Exception:
                continue

    if not facility_points:
        raise HTTPException(400, "Aucun équipement exploitable dans `facilities`")
    if len(facility_points) > 200:
        facility_points = facility_points[:200]

    profile_meta = PROFILES[payload.profile]
    coords = ";".join(
        f"{x},{y}" for x, y in [*origins, *[(fx, fy) for fx, fy, _ in facility_points]]
    )
    sources = ";".join(str(i) for i in range(len(origins)))
    destinations = ";".join(str(len(origins) + i) for i in range(len(facility_points)))

    matrix: list[list[float | None]] | None = None
    engine_used = "OSRM"
    try:
        raw = await get_json(
            "osrm",
            f"{settings.osrm_url}/table/v1/{profile_meta['osrm']}/{coords}",
            params={"sources": sources, "destinations": destinations, "annotations": "duration,distance"},
        )
        if raw.get("code") == "Ok":
            matrix = raw.get("durations")
            distances = raw.get("distances")
        else:
            distances = None
    except UpstreamError as exc:
        log.warning("Matrice OSRM indisponible, repli distance à vol d'oiseau : %s", exc)
        distances = None

    features: list[dict[str, Any]] = []
    for i, (olon, olat) in enumerate(origins):
        best_idx: int | None = None
        best_duration: float | None = None
        best_distance: float | None = None

        if matrix and matrix[i]:
            for j, dur in enumerate(matrix[i]):
                if dur is None:
                    continue
                if best_duration is None or dur < best_duration:
                    best_duration = dur
                    best_idx = j
                    if distances:
                        best_distance = distances[i][j]
        else:
            engine_used = "approximation à vol d'oiseau"
            for j, (fx, fy, _) in enumerate(facility_points):
                d = haversine_m(olon, olat, fx, fy)
                if best_distance is None or d < best_distance:
                    best_distance = d
                    best_idx = j
            if best_distance is not None:
                best_duration = best_distance / (profile_meta["speed_kmh"] * 1000 / 3600)

        props: dict[str, Any] = {
            "origin_index": i,
            "profile": payload.profile,
            "reachable": bool(
                best_duration is not None and best_duration <= payload.max_minutes * 60
            ),
        }
        if best_idx is not None:
            fx, fy, fprops = facility_points[best_idx]
            props.update(
                {
                    "nearest_facility": fprops.get("name") or fprops.get("nom") or f"#{best_idx}",
                    "nearest_facility_index": best_idx,
                    "nearest_coordinates": [fx, fy],
                    "duration_min": round(best_duration / 60, 1) if best_duration else None,
                    "distance_km": round(best_distance / 1000, 2) if best_distance else None,
                }
            )
        features.append(
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [olon, olat]}, "properties": props}
        )

    reachable = sum(1 for f in features if f["properties"]["reachable"])
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "origins": len(origins),
            "facilities": len(facility_points),
            "max_minutes": payload.max_minutes,
            "profile": payload.profile,
            "reachable_count": reachable,
            "coverage_rate": round(reachable / len(features) * 100, 1) if features else 0,
            "engine": engine_used,
        },
    }
