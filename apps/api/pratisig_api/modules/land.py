"""Module analyse foncière — évaluation d'une parcelle avant acquisition.

Repris de `pratisig/terracheck-senegal` (Next.js 14 + TypeScript), qui évaluait
un terrain sur six critères pondérés : inondation, topographie, occupation du
sol, accessibilité, marché et distance à la ville.

Deux idées de TerraCheck sont conservées telles quelles car elles sont bonnes :

1. **Redistribution des poids** — quand une composante est indisponible, son
   poids est réparti sur les autres au lieu d'être compté comme zéro. Un
   terrain n'est pas pénalisé parce qu'une source est en panne.
2. **Aucune donnée simulée** — le dépôt d'origine avait explicitement supprimé
   son `mockGee.ts` (« Si une source est indisponible, la donnée est absente
   plutôt que simulée »). C'est aussi la règle de cette plateforme.

Différence d'implémentation : TerraCheck contournait le blocage des IP Vercel
en exécutant Overpass et Esri **dans le navigateur**, ce qui rendait l'analyse
inaccessible en API. Ici tout est côté serveur, où ce blocage n'existe pas.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import settings
from ..core import cache
from ..core.geo import haversine_m
from ..core.http import UpstreamError, get_json, post_json

log = logging.getLogger("pratisig.land")
router = APIRouter(prefix="/api/land", tags=["foncier"])

CACHE_NS = "land"

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPENTOPODATA_URL = "https://api.opentopodata.org/v1/srtm30m"

# Pondération du score global (TerraCheck)
WEIGHTS = {
    "flood": 0.30,
    "topography": 0.15,
    "landcover": 0.15,
    "accessibility": 0.15,
    "services": 0.15,
    "travel": 0.10,
}

# En deçà de ce taux de couverture, le score est affiché mais signalé comme
# non concluant : trop de critères manquants pour trancher.
MIN_COVERAGE_PCT = 50.0

SCORE_THRESHOLDS = [
    (75, "excellent", "#437a22"),
    (55, "bon", "#6daa45"),
    (35, "moyen", "#d19900"),
    (20, "faible", "#da7101"),
    (0, "critique", "#a12c7b"),
]

# Points de référence urbains d'Afrique de l'Ouest
REFERENCE_CITIES = {
    "dakar": {"label": "Dakar", "lat": 14.6937, "lon": -17.4441},
    "thies": {"label": "Thiès", "lat": 14.7886, "lon": -16.9246},
    "saint-louis": {"label": "Saint-Louis", "lat": 16.0179, "lon": -16.4896},
    "kaolack": {"label": "Kaolack", "lat": 14.1652, "lon": -16.0726},
    "ziguinchor": {"label": "Ziguinchor", "lat": 12.5665, "lon": -16.2733},
    "bamako": {"label": "Bamako", "lat": 12.6392, "lon": -8.0029},
    "abidjan": {"label": "Abidjan", "lat": 5.3600, "lon": -4.0083},
}

COST_PER_KM_CFA = 150
AVG_SPEED_KMH = 50

# Aptitude à la construction par classe d'occupation du sol
LANDCOVER_SCORES = {
    "sol_nu": {"score": 80, "label": "Sol nu / sableux", "buildable": True},
    "savane": {"score": 75, "label": "Savane / brousse", "buildable": True},
    "agricole": {"score": 70, "label": "Terres agricoles", "buildable": True},
    "foret": {"score": 65, "label": "Forêt / végétation dense", "buildable": True},
    "urbain": {"score": 60, "label": "Zone urbaine / bâti", "buildable": True},
    "industriel": {"score": 30, "label": "Zone industrielle", "buildable": True},
    "eau": {"score": 10, "label": "Eau / zone humide", "buildable": False},
    "inconnu": {"score": 55, "label": "Non déterminé", "buildable": True},
}


class LandAnalysisRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    reference_city: str = Field("dakar", description="Ville de référence, voir /api/land/references")
    include_services: bool = Field(True, description="Rechercher les équipements OSM alentour")
    years: int = Field(1, ge=1, le=5, description="Années d'historique pluviométrique")


class LandCompareRequest(BaseModel):
    parcels: list[LandAnalysisRequest] = Field(..., min_length=2, max_length=8)


def _score_label(total: float) -> tuple[str, str]:
    for threshold, label, color in SCORE_THRESHOLDS:
        if total >= threshold:
            return label, color
    return "critique", "#a12c7b"


async def _analyze_flood(lat: float, lon: float, years: int) -> dict[str, Any] | None:
    """Risque d'inondation par historique pluviométrique (Open-Meteo ERA5)."""
    from datetime import date, timedelta

    end = date.today() - timedelta(days=7)  # ERA5 a quelques jours de latence
    start = end - timedelta(days=365 * years)

    key = cache.cache_key("flood", round(lat, 4), round(lon, 4), years)
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        data = await get_json(
            "open-meteo",
            OPEN_METEO_ARCHIVE,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "precipitation_sum",
                "timezone": "auto",
            },
        )
    except UpstreamError as exc:
        log.warning("Historique pluviométrique indisponible : %s", exc)
        return None

    values = [v for v in (data.get("daily", {}).get("precipitation_sum") or []) if v is not None]
    if not values:
        return None

    max_day = max(values)
    total = sum(values)
    annual = total / years
    heavy_days = sum(1 for v in values if v > 50)

    if max_day > 80 or annual > 800:
        risk = "élevé"
    elif max_day > 40 or annual > 400:
        risk = "moyen"
    else:
        risk = "faible"

    # Score : pénalise les pluies intenses, qui provoquent le ruissellement
    if risk == "faible":
        score = 85 + max(0, 10 - max_day / 8)
    elif risk == "moyen":
        score = 45 + max(0, 20 - max_day / 5)
    else:
        score = max(0, 25 - (max_day - 80) / 4)

    result = {
        "risk_level": risk,
        "score": round(min(100, max(0, score)), 1),
        "max_daily_mm": round(max_day, 1),
        "annual_rainfall_mm": round(annual, 1),
        "heavy_rain_days": heavy_days,
        "years_analyzed": years,
        "source": "Open-Meteo ERA5",
    }
    cache.set(CACHE_NS, key, result)
    return result


async def _analyze_topography(lat: float, lon: float) -> dict[str, Any] | None:
    """Altitude, pente et détection de cuvette (SRTM 30 m via OpenTopoData)."""
    delta = 0.001  # environ 111 m
    points = [
        (lat, lon),
        (lat + delta, lon),
        (lat - delta, lon),
        (lat, lon + delta),
        (lat, lon - delta),
    ]
    locations = "|".join(f"{p[0]:.6f},{p[1]:.6f}" for p in points)

    key = cache.cache_key("topo", round(lat, 4), round(lon, 4))
    cached = cache.get(CACHE_NS, key, ttl=0)  # le relief ne change pas
    if cached is not None:
        return cached

    try:
        data = await get_json("opentopodata", OPENTOPODATA_URL, params={"locations": locations})
    except UpstreamError as exc:
        log.warning("Topographie indisponible : %s", exc)
        return None

    if data.get("status") != "OK":
        return None

    elevations = [
        r.get("elevation")
        for r in data.get("results", [])
        if r.get("elevation") is not None
    ]
    if not elevations:
        return None

    centre = elevations[0]
    neighbours = elevations[1:]
    if not neighbours:
        return None
    neighbour_avg = sum(neighbours) / len(neighbours)
    is_depression = centre < neighbour_avg - 0.5

    import math

    dx_m = delta * 111_320 * math.cos(math.radians(lat))
    dy_m = delta * 110_574
    dz_ew = abs((elevations[3] if len(elevations) > 3 else centre) - (elevations[4] if len(elevations) > 4 else centre))
    dz_ns = abs((elevations[1] if len(elevations) > 1 else centre) - (elevations[2] if len(elevations) > 2 else centre))
    slope_deg = math.degrees(math.atan(math.sqrt((dz_ew / dx_m) ** 2 + (dz_ns / dy_m) ** 2)))

    if is_depression:
        terrain = "Dépression / cuvette"
        score = 20.0
    else:
        if slope_deg > 15:
            terrain = "Terrain pentu"
        elif slope_deg > 5:
            terrain = "Terrain légèrement pentu"
        elif centre < 5:
            terrain = "Plaine littorale basse"
        elif centre < 50:
            terrain = "Plaine"
        else:
            terrain = "Plateau / colline"

        elev_score = min(100, centre * 1.2)
        slope_score = 100 if slope_deg < 2 else 80 if slope_deg < 5 else 55 if slope_deg < 10 else 30
        score = (elev_score + slope_score) / 2

    result = {
        "elevation_m": round(centre, 1),
        "slope_deg": round(slope_deg, 2),
        "is_depression": is_depression,
        "terrain_type": terrain,
        "score": round(min(100, max(0, score)), 1),
        "source": "SRTM 30 m (OpenTopoData)",
    }
    cache.set(CACHE_NS, key, result)
    return result


async def _analyze_services(lat: float, lon: float) -> dict[str, Any] | None:
    """Distance aux routes et aux équipements (Overpass), côté serveur."""
    query = f"""[out:json][timeout:25];
(
  way["highway"~"^(primary|secondary|tertiary|residential|unclassified|trunk)$"](around:3000,{lat},{lon});
  nwr["amenity"~"^(school|hospital|clinic|marketplace|pharmacy)$"](around:5000,{lat},{lon});
  nwr["amenity"~"^(bus_station|taxi)$"](around:3000,{lat},{lon});
);
out center tags 200;"""

    key = cache.cache_key("services", round(lat, 4), round(lon, 4))
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        data = await post_json("overpass", settings.overpass_url, data={"data": query})
    except UpstreamError as exc:
        log.warning("Équipements OSM indisponibles : %s", exc)
        return None

    elements = data.get("elements", [])
    if not elements:
        return None

    def distance_to(predicate) -> tuple[float | None, dict[str, Any] | None]:
        best_dist: float | None = None
        best_el: dict[str, Any] | None = None
        for el in elements:
            tags = el.get("tags") or {}
            if not predicate(tags):
                continue
            centre = el.get("center") or ({"lat": el.get("lat"), "lon": el.get("lon")})
            if centre.get("lat") is None:
                continue
            d = haversine_m(lon, lat, centre["lon"], centre["lat"])
            if best_dist is None or d < best_dist:
                best_dist, best_el = d, el
        return best_dist, best_el

    road_dist, road_el = distance_to(lambda t: "highway" in t)
    school_dist, _ = distance_to(lambda t: t.get("amenity") == "school")
    health_dist, _ = distance_to(lambda t: t.get("amenity") in ("hospital", "clinic", "pharmacy"))
    market_dist, _ = distance_to(lambda t: t.get("amenity") == "marketplace")
    transit_dist, _ = distance_to(lambda t: t.get("amenity") in ("bus_station", "taxi"))

    # Score d'accès routier : au-delà de 2 km, l'accès est difficile
    if road_dist is None:
        access_score = 15.0
    elif road_dist < 100:
        access_score = 100.0
    elif road_dist < 500:
        access_score = 85.0
    elif road_dist < 1000:
        access_score = 65.0
    elif road_dist < 2000:
        access_score = 40.0
    else:
        access_score = 20.0

    # Score d'équipements : présence pondérée des services de proximité
    def service_points(dist: float | None, near: float, far: float) -> float:
        if dist is None:
            return 0.0
        if dist <= near:
            return 100.0
        if dist >= far:
            return 20.0
        return 100 - (dist - near) / (far - near) * 80

    services_score = (
        service_points(school_dist, 1000, 5000) * 0.3
        + service_points(health_dist, 1500, 5000) * 0.3
        + service_points(market_dist, 2000, 5000) * 0.2
        + service_points(transit_dist, 1000, 3000) * 0.2
    )

    def km(value: float | None) -> float | None:
        return round(value / 1000, 2) if value is not None else None

    result = {
        "access_score": round(access_score, 1),
        "services_score": round(services_score, 1),
        "nearest_road_km": km(road_dist),
        "nearest_road_type": (road_el.get("tags", {}).get("highway") if road_el else None),
        "distances_km": {
            "school": km(school_dist),
            "health": km(health_dist),
            "market": km(market_dist),
            "transit": km(transit_dist),
        },
        "source": "OpenStreetMap (Overpass)",
    }
    cache.set(CACHE_NS, key, result)
    return result


async def _analyze_landcover(lat: float, lon: float) -> dict[str, Any] | None:
    """Occupation du sol déduite des usages OSM environnants.

    Approche dégradée mais sans clé : Earth Engine (Dynamic World) donne un
    bien meilleur résultat quand il est configuré — voir `/api/raster`.
    """
    query = f"""[out:json][timeout:20];
(
  way["landuse"](around:400,{lat},{lon});
  way["natural"](around:400,{lat},{lon});
  way["building"](around:250,{lat},{lon});
);
out tags 120;"""

    key = cache.cache_key("landcover", round(lat, 4), round(lon, 4))
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        data = await post_json("overpass", settings.overpass_url, data={"data": query})
    except UpstreamError as exc:
        log.warning("Occupation du sol indisponible : %s", exc)
        return None

    elements = data.get("elements", [])
    counts: dict[str, int] = {}
    for el in elements:
        tags = el.get("tags") or {}
        landuse = tags.get("landuse", "")
        natural = tags.get("natural", "")

        if "building" in tags:
            klass = "urbain"
        elif landuse in ("residential", "commercial", "retail"):
            klass = "urbain"
        elif landuse in ("industrial", "quarry"):
            klass = "industriel"
        elif landuse in ("farmland", "farmyard", "orchard", "vineyard", "allotments"):
            klass = "agricole"
        elif landuse in ("forest",) or natural in ("wood", "scrub"):
            klass = "foret" if natural != "scrub" else "savane"
        elif natural in ("water", "wetland", "marsh") or landuse == "basin":
            klass = "eau"
        elif natural in ("sand", "bare_rock", "beach"):
            klass = "sol_nu"
        elif landuse in ("meadow", "grass") or natural == "grassland":
            klass = "savane"
        else:
            continue
        counts[klass] = counts.get(klass, 0) + 1

    if not counts:
        dominant = "inconnu"
        confidence = 0.0
    else:
        dominant = max(counts, key=counts.get)
        confidence = round(counts[dominant] / sum(counts.values()), 2)

    meta = LANDCOVER_SCORES[dominant]
    result = {
        "dominant_class": dominant,
        "label": meta["label"],
        "buildable": meta["buildable"],
        "score": float(meta["score"]),
        "confidence": confidence,
        "distribution": counts,
        "source": "OpenStreetMap (usages du sol)",
        "note": "Pour une classification satellitaire précise, utiliser /api/raster avec Dynamic World.",
    }
    cache.set(CACHE_NS, key, result)
    return result


def _analyze_travel(lat: float, lon: float, city_key: str) -> dict[str, Any]:
    """Distance et coût de transport vers la ville de référence."""
    city = REFERENCE_CITIES.get(city_key, REFERENCE_CITIES["dakar"])
    distance_km = haversine_m(lon, lat, city["lon"], city["lat"]) / 1000

    if distance_km < 30:
        score = 95.0
    elif distance_km < 80:
        score = 80.0
    elif distance_km < 150:
        score = 60.0
    elif distance_km < 300:
        score = 40.0
    else:
        score = 20.0

    return {
        "reference_city": city["label"],
        "distance_km": round(distance_km, 1),
        "travel_time_min": round(distance_km / AVG_SPEED_KMH * 60),
        "transport_cost_cfa": round(distance_km * COST_PER_KM_CFA),
        "score": score,
        "note": "Distance à vol d'oiseau — utiliser /api/routing/route pour la distance réseau.",
    }


def _compute_score(components: dict[str, float | None]) -> dict[str, Any]:
    """Score global avec redistribution des poids (principe TerraCheck).

    Une composante indisponible ne pénalise pas la parcelle : son poids est
    réparti proportionnellement entre les composantes disponibles.
    """
    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        return {
            "total": None,
            "label": "indéterminé",
            "color": "#bab9b4",
            "breakdown": components,
            "coverage_pct": 0.0,
            "note": "Aucune source de données disponible",
        }

    active_weight = sum(WEIGHTS[k] for k in available)
    total = sum(v * (WEIGHTS[k] / active_weight) for k, v in available.items())
    total = round(min(100, max(0, total)), 1)
    label, color = _score_label(total)
    coverage = round(active_weight / sum(WEIGHTS.values()) * 100, 1)

    # Un score calculé sur trop peu de composantes n'est pas exploitable.
    # Sans ce garde-fou, une parcelle dont seule la distance à la ville est
    # connue ressortait « excellente » à 95/100 — conclusion trompeuse.
    reliable = coverage >= MIN_COVERAGE_PCT
    if not reliable:
        label = "non concluant"
        color = "#bab9b4"

    return {
        "total": total,
        "label": label,
        "color": color,
        "reliable": reliable,
        "breakdown": components,
        "weights_applied": {k: round(WEIGHTS[k] / active_weight, 3) for k in available},
        "coverage_pct": coverage,
        "missing": [k for k, v in components.items() if v is None],
        "note": (
            None
            if reliable
            else f"Score indicatif seulement : {coverage} % des critères disponibles "
                 f"(minimum {MIN_COVERAGE_PCT} % pour conclure). "
                 "Vérifiez que les sources externes sont joignables."
        ),
    }


@router.get("/criteria", summary="Critères d'évaluation et pondérations")
def criteria() -> dict[str, Any]:
    return {
        "weights": WEIGHTS,
        "thresholds": [
            {"min_score": t, "label": name, "color": c} for t, name, c in SCORE_THRESHOLDS
        ],
        "landcover_classes": LANDCOVER_SCORES,
        "principle": (
            "Les composantes indisponibles voient leur poids redistribué "
            "sur les autres : une source en panne ne pénalise pas la parcelle."
        ),
    }


@router.get("/references", summary="Villes de référence")
def references() -> dict[str, Any]:
    return {"cities": [{"id": k, **v} for k, v in REFERENCE_CITIES.items()]}


@router.post("/analyze", summary="Évaluer une parcelle")
async def analyze(payload: LandAnalysisRequest) -> dict[str, Any]:
    """Analyse foncière multicritère d'un point.

    Chaque source est interrogée indépendamment : une indisponibilité rend la
    composante `null` (et redistribue son poids) sans faire échouer l'analyse.
    """
    lat, lon = payload.latitude, payload.longitude

    flood = await _analyze_flood(lat, lon, payload.years)
    topography = await _analyze_topography(lat, lon)
    landcover = await _analyze_landcover(lat, lon)
    services = await _analyze_services(lat, lon) if payload.include_services else None
    travel = _analyze_travel(lat, lon, payload.reference_city)

    score = _compute_score({
        "flood": flood["score"] if flood else None,
        "topography": topography["score"] if topography else None,
        "landcover": landcover["score"] if landcover else None,
        "accessibility": services["access_score"] if services else None,
        "services": services["services_score"] if services else None,
        "travel": travel["score"],
    })

    warnings: list[dict[str, str]] = []
    if topography and topography["is_depression"]:
        warnings.append({
            "level": "danger",
            "message": "Parcelle en cuvette : accumulation d'eau probable en saison des pluies.",
        })
    if topography and topography["elevation_m"] < 5:
        warnings.append({
            "level": "warning",
            "message": "Altitude très basse : exposition à la submersion et aux remontées salines.",
        })
    if flood and flood["risk_level"] == "élevé":
        warnings.append({
            "level": "danger",
            "message": f"Pluies intenses relevées (max {flood['max_daily_mm']} mm/jour).",
        })
    if landcover and not landcover["buildable"]:
        warnings.append({
            "level": "danger",
            "message": f"Occupation du sol défavorable : {landcover['label']}.",
        })
    if services and services["nearest_road_km"] and services["nearest_road_km"] > 2:
        warnings.append({
            "level": "warning",
            "message": f"Route la plus proche à {services['nearest_road_km']} km : desserte difficile.",
        })
    if score["missing"]:
        warnings.insert(0, {
            "level": "warning" if score["reliable"] else "danger",
            "message": (
                f"Composantes indisponibles : {', '.join(score['missing'])} "
                f"(couverture {score['coverage_pct']} %)."
                + ("" if score["reliable"] else " Score non concluant.")
            ),
        })

    return {
        "coordinates": {"latitude": lat, "longitude": lon},
        "score": score,
        "flood": flood,
        "topography": topography,
        "landcover": landcover,
        "services": services,
        "travel": travel,
        "warnings": warnings,
        "disclaimer": (
            "Analyse indicative fondée sur des données ouvertes. Elle ne remplace "
            "ni une visite de terrain, ni une vérification cadastrale, ni un avis "
            "de géomètre ou de notaire."
        ),
    }


@router.post("/compare", summary="Comparer plusieurs parcelles")
async def compare(payload: LandCompareRequest) -> dict[str, Any]:
    """Analyse et classe plusieurs parcelles candidates."""
    results = []
    for index, parcel in enumerate(payload.parcels):
        analysis = await analyze(parcel)
        results.append({
            "index": index,
            "coordinates": analysis["coordinates"],
            "score": analysis["score"],
            "summary": {
                "flood_risk": analysis["flood"]["risk_level"] if analysis["flood"] else None,
                "terrain": analysis["topography"]["terrain_type"] if analysis["topography"] else None,
                "landcover": analysis["landcover"]["label"] if analysis["landcover"] else None,
                "nearest_road_km": (
                    analysis["services"]["nearest_road_km"] if analysis["services"] else None
                ),
                "distance_city_km": analysis["travel"]["distance_km"],
            },
            "warnings": [w for w in analysis["warnings"] if w["level"] in ("danger", "warning")],
        })

    ranked = sorted(
        results,
        key=lambda r: r["score"]["total"] if r["score"]["total"] is not None else -1,
        reverse=True,
    )

    return {
        "count": len(ranked),
        "ranking": ranked,
        "best": ranked[0] if ranked else None,
        "disclaimer": (
            "Comparaison indicative. Les parcelles dont la couverture de données "
            "diffère ne sont pas strictement comparables — vérifier `coverage_pct`."
        ),
    }
