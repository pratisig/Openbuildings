"""Module agriculture — suivi agronomique et aptitude culturale.

Fusion de `pratisig/AGRISIGHT` (Streamlit monolithique 1496 lignes, calculs
GDD/FAO-56 vectorisés) et `pratisig/AgriSight_v2` (base de cultures typée,
zones agro-écologiques, préférences pédologiques).

Les deux dépôts couvraient le même besoin avec des données complémentaires :
AGRISIGHT apportait les paramètres thermiques et phénologiques, AgriSight_v2
les seuils pluviométriques, les rendements et les préférences de sol. La base
de cultures ci-dessous est la réunion des deux.

Correction majeure : `calculate_vegetation_indices()` d'AGRISIGHT **simulait**
le NDVI avec une sinusoïde et du bruit gaussien (`np.random.normal`) — des
courbes d'allure crédible mais sans lien avec le terrain. Ici, les indices
proviennent du module `raster` (Sentinel-2 réel) ou sont absents.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

log = logging.getLogger("pratisig.agriculture")
router = APIRouter(prefix="/api/agriculture", tags=["agriculture"])

CACHE_NS = "agriculture"

# ── Base de cultures — fusion AGRISIGHT × AgriSight_v2 ─────────────
# base_temp / opt_temp / max_temp / cycle_days / stages : AGRISIGHT
# rain_min / rain_max / yield_max / soils / ndvi_optimal : AgriSight_v2
CROPS: dict[str, dict[str, Any]] = {
    "mil": {
        "label": "Mil",
        "base_temp": 8.0,
        "opt_temp": 25.0,
        "max_temp": 35.0,
        "cycle_days": 90,
        "rain_min": 400,
        "rain_max": 600,
        "water_req_mm": 400,
        "yield_max_t_ha": 1.5,
        "kc": 0.40,
        "lai_max": 3.5,
        "ndvi_optimal": 0.60,
        "soils": ["sableux", "argilo-sableux"],
        "water_need": "faible",
        "stages": ["Germination", "Levée", "Tallage", "Panicule", "Floraison", "Maturation"],
    },
    "sorgho": {
        "label": "Sorgho",
        "base_temp": 10.0,
        "opt_temp": 28.0,
        "max_temp": 37.0,
        "cycle_days": 120,
        "rain_min": 450,
        "rain_max": 700,
        "water_req_mm": 450,
        "yield_max_t_ha": 2.0,
        "kc": 0.45,
        "lai_max": 4.0,
        "ndvi_optimal": 0.65,
        "soils": ["argilo-sableux", "limoneux"],
        "water_need": "moyen",
        "stages": ["Germination", "Levée", "Tallage", "Panicule", "Floraison", "Grain", "Maturation"],
    },
    "mais": {
        "label": "Maïs",
        "base_temp": 8.0,
        "opt_temp": 24.0,
        "max_temp": 35.0,
        "cycle_days": 110,
        "rain_min": 500,
        "rain_max": 800,
        "water_req_mm": 500,
        "yield_max_t_ha": 4.0,
        "kc": 0.50,
        "lai_max": 5.0,
        "ndvi_optimal": 0.70,
        "soils": ["limoneux", "argileux"],
        "water_need": "élevé",
        "stages": ["Germination", "Levée", "V4-V6", "VT", "Floraison", "Remplissage", "Maturité"],
    },
    "riz": {
        "label": "Riz",
        "base_temp": 12.0,
        "opt_temp": 28.0,
        "max_temp": 35.0,
        "cycle_days": 120,
        "rain_min": 800,
        "rain_max": 1500,
        "water_req_mm": 1200,
        "yield_max_t_ha": 5.0,
        "kc": 0.80,
        "lai_max": 6.0,
        "ndvi_optimal": 0.75,
        "soils": ["argileux"],
        "water_need": "très élevé",
        "stages": ["Germination", "Levée", "Tallage", "Montaison", "Floraison", "Maturation"],
    },
    "arachide": {
        "label": "Arachide",
        "base_temp": 15.0,
        "opt_temp": 26.0,
        "max_temp": 35.0,
        "cycle_days": 120,
        "rain_min": 450,
        "rain_max": 700,
        "water_req_mm": 350,
        "yield_max_t_ha": 2.5,
        "kc": 0.40,
        "lai_max": 3.0,
        "ndvi_optimal": 0.60,
        "soils": ["sableux", "limono-sableux"],
        "water_need": "moyen",
        "stages": ["Germination", "Levée", "Croissance", "Floraison", "Épinglement", "Maturation"],
    },
    "niebe": {
        "label": "Niébé",
        "base_temp": 15.0,
        "opt_temp": 25.0,
        "max_temp": 35.0,
        "cycle_days": 75,
        "rain_min": 350,
        "rain_max": 600,
        "water_req_mm": 300,
        "yield_max_t_ha": 1.2,
        "kc": 0.35,
        "lai_max": 2.5,
        "ndvi_optimal": 0.55,
        "soils": ["sableux", "argilo-sableux"],
        "water_need": "faible",
        "stages": ["Germination", "Levée", "Croissance", "Floraison", "Remplissage", "Maturation"],
    },
    "manioc": {
        "label": "Manioc",
        "base_temp": 12.0,
        "opt_temp": 27.0,
        "max_temp": 32.0,
        "cycle_days": 300,
        "rain_min": 1000,
        "rain_max": 2000,
        "water_req_mm": 900,
        "yield_max_t_ha": 20.0,
        "kc": 0.50,
        "lai_max": 4.0,
        "ndvi_optimal": 0.65,
        "soils": ["sableux", "limono-sableux"],
        "water_need": "moyen",
        "stages": ["Reprise", "Croissance", "Tubérisation", "Grossissement", "Maturation"],
    },
    "tomate": {
        "label": "Tomate",
        "base_temp": 10.0,
        "opt_temp": 24.0,
        "max_temp": 30.0,
        "cycle_days": 90,
        "rain_min": 600,
        "rain_max": 1000,
        "water_req_mm": 550,
        "yield_max_t_ha": 40.0,
        "kc": 0.70,
        "lai_max": 4.0,
        "ndvi_optimal": 0.70,
        "soils": ["limoneux"],
        "water_need": "élevé",
        "stages": ["Pépinière", "Repiquage", "Croissance", "Floraison", "Nouaison", "Récolte"],
    },
    "oignon": {
        "label": "Oignon",
        "base_temp": 7.0,
        "opt_temp": 20.0,
        "max_temp": 28.0,
        "cycle_days": 120,
        "rain_min": 400,
        "rain_max": 700,
        "water_req_mm": 450,
        "yield_max_t_ha": 25.0,
        "kc": 0.65,
        "lai_max": 2.0,
        "ndvi_optimal": 0.60,
        "soils": ["limoneux", "argilo-sableux"],
        "water_need": "élevé",
        "stages": ["Pépinière", "Repiquage", "Croissance", "Bulbaison", "Maturation"],
    },
    "coton": {
        "label": "Coton",
        "base_temp": 15.0,
        "opt_temp": 28.0,
        "max_temp": 35.0,
        "cycle_days": 160,
        "rain_min": 600,
        "rain_max": 1000,
        "water_req_mm": 700,
        "yield_max_t_ha": 2.5,
        "kc": 0.60,
        "lai_max": 4.0,
        "ndvi_optimal": 0.65,
        "soils": ["argilo-sableux", "limoneux"],
        "water_need": "moyen",
        "stages": ["Levée", "Croissance", "Boutons floraux", "Floraison", "Capsulaison", "Maturation"],
    },
}

# Zones agro-écologiques (AgriSight_v2)
AGRO_ZONES = [
    {"id": "sahel", "label": "Sahel", "rain_min": 0, "rain_max": 400},
    {"id": "sahelo_soudanien", "label": "Sahélo-soudanien", "rain_min": 400, "rain_max": 600},
    {"id": "soudanien", "label": "Soudanien", "rain_min": 600, "rain_max": 900},
    {"id": "soudano_guineen", "label": "Soudano-guinéen", "rain_min": 900, "rain_max": 1200},
    {"id": "guineen", "label": "Guinéen", "rain_min": 1200, "rain_max": 10000},
]

SOIL_TYPES = ["sableux", "limono-sableux", "limoneux", "argilo-sableux", "argileux"]


class SeasonRequest(BaseModel):
    """Analyse agronomique d'une saison à partir du climat réel."""

    crop: str = Field(..., description="Identifiant de culture, voir /api/agriculture/crops")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    sowing_date: str = Field(..., description="Date de semis AAAA-MM-JJ")
    end_date: str | None = Field(None, description="Défaut : semis + durée du cycle")
    soil: str | None = Field(None, description="Type de sol, voir /api/agriculture/soils")

    @model_validator(mode="after")
    def _check(self) -> SeasonRequest:
        if self.crop not in CROPS:
            raise ValueError(f"Culture inconnue : {self.crop}. Disponibles : {list(CROPS)}")
        try:
            sowing = date.fromisoformat(self.sowing_date)
        except ValueError as exc:
            raise ValueError("sowing_date attendue au format AAAA-MM-JJ") from exc
        if self.end_date is None:
            self.end_date = (sowing + timedelta(days=CROPS[self.crop]["cycle_days"])).isoformat()
        else:
            try:
                end = date.fromisoformat(self.end_date)
            except ValueError as exc:
                raise ValueError("end_date attendue au format AAAA-MM-JJ") from exc
            if end <= sowing:
                raise ValueError("end_date doit suivre sowing_date")
        if self.soil is not None and self.soil not in SOIL_TYPES:
            raise ValueError(f"Sol inconnu : {self.soil}. Disponibles : {SOIL_TYPES}")
        return self


class SuitabilityRequest(BaseModel):
    """Classement des cultures adaptées à un climat et un sol donnés."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    year: int = Field(..., ge=1990, le=2100, description="Année de référence climatique")
    soil: str | None = None
    crops: list[str] | None = Field(None, description="Restreindre à certaines cultures")

    @model_validator(mode="after")
    def _check(self) -> SuitabilityRequest:
        if self.soil is not None and self.soil not in SOIL_TYPES:
            raise ValueError(f"Sol inconnu : {self.soil}. Disponibles : {SOIL_TYPES}")
        if self.crops:
            unknown = [c for c in self.crops if c not in CROPS]
            if unknown:
                raise ValueError(f"Cultures inconnues : {unknown}")
        return self


# ── Calculs agronomiques (repris d'AGRISIGHT, en Python pur) ───────
def growing_degree_days(temps: list[float], base_temp: float) -> list[float]:
    """Degrés-jours de croissance cumulés (méthode simple)."""
    total = 0.0
    cumulative: list[float] = []
    for t in temps:
        if t is not None:
            total += max(t - base_temp, 0.0)
        cumulative.append(round(total, 1))
    return cumulative


def phenological_stage(gdd_accumulated: float, gdd_target: float, stages: list[str]) -> tuple[str, float]:
    """Stade phénologique estimé par progression thermique."""
    if gdd_target <= 0:
        return stages[0], 0.0
    progress = min(gdd_accumulated / gdd_target * 100, 100.0)
    index = min(int(progress / 100 * len(stages)), len(stages) - 1)
    return stages[index], round(progress, 1)


def water_balance(precip: list[float], crop: dict[str, Any], eto_daily: float = 5.0) -> dict[str, Any]:
    """Bilan hydrique FAO-56 simplifié.

    ETc = ETo x Kc. Le déficit est ce qu'il faut apporter par irrigation.
    """
    valid = [p for p in precip if p is not None]
    total_rain = sum(valid)
    etc = eto_daily * len(valid) * crop["kc"]
    deficit = max(0.0, etc - total_rain)
    return {
        "rainfall_mm": round(total_rain, 1),
        "etc_mm": round(etc, 1),
        "deficit_mm": round(deficit, 1),
        "irrigation_needed": deficit > 0,
        "satisfaction_pct": round(min(total_rain / etc * 100, 100), 1) if etc > 0 else None,
    }


def stress_indices(temps: list[float], precip: list[float], crop: dict[str, Any]) -> dict[str, float]:
    """Indices de stress thermique et hydrique, en pourcentage du cycle."""
    valid_temps = [t for t in temps if t is not None]
    if not valid_temps:
        return {"heat": 0.0, "cold": 0.0, "water": 0.0, "combined": 0.0}

    heat = sum(1 for t in valid_temps if t > crop["max_temp"]) / len(valid_temps) * 100
    cold = sum(1 for t in valid_temps if t < crop["base_temp"]) / len(valid_temps) * 100

    balance = water_balance(precip, crop)
    required = crop["water_req_mm"]
    water = min(balance["deficit_mm"] / required * 100, 100.0) if required > 0 else 0.0

    return {
        "heat": round(heat, 1),
        "cold": round(cold, 1),
        "water": round(water, 1),
        "combined": round((heat + cold + water) / 3, 1),
    }


def yield_potential(gdd_total: float, rainfall: float, crop: dict[str, Any]) -> dict[str, Any]:
    """Rendement potentiel estimé, pondéré thermique (60 %) / hydrique (40 %)."""
    gdd_target = crop["cycle_days"] * (crop["opt_temp"] - crop["base_temp"]) * 0.8
    thermal = min(gdd_total / gdd_target, 1.0) if gdd_target > 0 else 0.0
    hydric = min(rainfall / crop["water_req_mm"], 1.0) if crop["water_req_mm"] > 0 else 0.0
    ratio = 0.6 * thermal + 0.4 * hydric
    return {
        "estimated_t_ha": round(crop["yield_max_t_ha"] * ratio, 2),
        "max_t_ha": crop["yield_max_t_ha"],
        "ratio_pct": round(ratio * 100, 1),
        "thermal_factor": round(thermal, 3),
        "hydric_factor": round(hydric, 3),
        "gdd_target": round(gdd_target, 1),
    }


def agro_zone_for(annual_rain_mm: float) -> dict[str, Any]:
    for zone in AGRO_ZONES:
        if zone["rain_min"] <= annual_rain_mm < zone["rain_max"]:
            return zone
    return AGRO_ZONES[-1]


# ── Endpoints ──────────────────────────────────────────────────────
@router.get("/crops", summary="Base de cultures")
def list_crops() -> dict[str, Any]:
    return {
        "crops": [{"id": key, **meta} for key, meta in CROPS.items()],
        "count": len(CROPS),
        "sources": ["AGRISIGHT (paramètres thermiques)", "AgriSight_v2 (seuils pluviométriques)"],
    }


@router.get("/crops/{crop_id}", summary="Paramètres d'une culture")
def crop_detail(crop_id: str) -> dict[str, Any]:
    if crop_id not in CROPS:
        raise HTTPException(404, f"Culture inconnue. Disponibles : {list(CROPS)}")
    return {"id": crop_id, **CROPS[crop_id]}


@router.get("/zones", summary="Zones agro-écologiques et types de sol")
def zones() -> dict[str, Any]:
    return {"agro_zones": AGRO_ZONES, "soil_types": SOIL_TYPES}


@router.post("/season", summary="Analyse agronomique d'une saison")
async def season(payload: SeasonRequest) -> dict[str, Any]:
    """Bilan complet d'une campagne à partir du climat réel NASA POWER.

    Contrairement à AGRISIGHT, aucune donnée n'est simulée : si le climat est
    indisponible, la requête échoue explicitement.
    """
    from .climate import ClimateRequest, timeseries

    crop = CROPS[payload.crop]

    climate = await timeseries(
        ClimateRequest(
            latitude=payload.latitude,
            longitude=payload.longitude,
            start=payload.sowing_date,
            end=payload.end_date,
            parameters=["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR"],
        )
    )

    temps = climate["series"].get("T2M", [])
    temps_max = climate["series"].get("T2M_MAX", temps)
    precip = climate["series"].get("PRECTOTCORR", [])

    gdd_series = growing_degree_days(temps, crop["base_temp"])
    gdd_total = gdd_series[-1] if gdd_series else 0.0
    gdd_target = crop["cycle_days"] * (crop["opt_temp"] - crop["base_temp"]) * 0.8
    stage, progress = phenological_stage(gdd_total, gdd_target, crop["stages"])

    balance = water_balance(precip, crop)
    stress = stress_indices(temps_max, precip, crop)
    yields = yield_potential(gdd_total, balance["rainfall_mm"], crop)

    soil_fit: dict[str, Any] | None = None
    if payload.soil:
        suitable = payload.soil in crop["soils"]
        soil_fit = {
            "soil": payload.soil,
            "suitable": suitable,
            "preferred": crop["soils"],
            "note": "Sol adapté" if suitable else f"Sol non optimal — préférer : {', '.join(crop['soils'])}",
        }

    alerts: list[dict[str, str]] = []
    if stress["heat"] > 20:
        alerts.append({
            "level": "warning",
            "message": f"Stress thermique sur {stress['heat']} % du cycle "
                       f"(température > {crop['max_temp']} °C)",
        })
    if stress["water"] > 30:
        alerts.append({
            "level": "warning",
            "message": f"Déficit hydrique de {balance['deficit_mm']} mm — irrigation recommandée",
        })
    if balance["rainfall_mm"] < crop["rain_min"]:
        alerts.append({
            "level": "danger",
            "message": f"Pluviométrie {balance['rainfall_mm']} mm sous le minimum "
                       f"de {crop['rain_min']} mm pour {crop['label']}",
        })
    if balance["rainfall_mm"] > crop["rain_max"]:
        alerts.append({
            "level": "warning",
            "message": f"Pluviométrie {balance['rainfall_mm']} mm au-dessus de l'optimum "
                       f"({crop['rain_max']} mm) — risque d'excès d'eau",
        })
    if not alerts:
        alerts.append({"level": "ok", "message": "Conditions favorables sur la période analysée"})

    return {
        "crop": {"id": payload.crop, "label": crop["label"]},
        "location": {"latitude": payload.latitude, "longitude": payload.longitude},
        "period": {
            "sowing": payload.sowing_date,
            "end": payload.end_date,
            "days": climate["period"]["days"],
        },
        "thermal": {
            "gdd_total": gdd_total,
            "gdd_target": round(gdd_target, 1),
            "stage": stage,
            "progress_pct": progress,
            "gdd_series": gdd_series,
        },
        "water": balance,
        "stress": stress,
        "yield": yields,
        "soil": soil_fit,
        "alerts": alerts,
        "climate_summary": climate["summary"],
        "dates": climate["dates"],
        "source": "NASA POWER (climat réel) — aucune donnée simulée",
    }


@router.post("/suitability", summary="Cultures adaptées à un lieu")
async def suitability(payload: SuitabilityRequest) -> dict[str, Any]:
    """Classe les cultures par adéquation au climat annuel réel du lieu."""
    from .climate import ClimateRequest, timeseries

    climate = await timeseries(
        ClimateRequest(
            latitude=payload.latitude,
            longitude=payload.longitude,
            start=f"{payload.year}-01-01",
            end=f"{payload.year}-12-31",
            parameters=["T2M", "T2M_MAX", "PRECTOTCORR"],
        )
    )

    rain_summary = climate["summary"].get("PRECTOTCORR", {})
    temp_summary = climate["summary"].get("T2M", {})
    annual_rain = rain_summary.get("total_mm", 0.0)
    mean_temp = temp_summary.get("mean", 0.0)
    zone = agro_zone_for(annual_rain)

    candidates = payload.crops or list(CROPS)
    results: list[dict[str, Any]] = []

    for crop_id in candidates:
        crop = CROPS[crop_id]

        # Adéquation pluviométrique : 100 dans la fourchette, décroissante hors bornes
        if crop["rain_min"] <= annual_rain <= crop["rain_max"]:
            rain_score = 100.0
        elif annual_rain < crop["rain_min"]:
            rain_score = max(0.0, 100 - (crop["rain_min"] - annual_rain) / crop["rain_min"] * 100)
        else:
            rain_score = max(0.0, 100 - (annual_rain - crop["rain_max"]) / crop["rain_max"] * 100)

        # Adéquation thermique : écart à la température optimale
        temp_gap = abs(mean_temp - crop["opt_temp"])
        temp_score = max(0.0, 100 - temp_gap * 8)

        # Adéquation pédologique
        if payload.soil:
            soil_score = 100.0 if payload.soil in crop["soils"] else 55.0
        else:
            soil_score = None

        weights = {"rain": 0.5, "temp": 0.3, "soil": 0.2}
        if soil_score is None:
            # Redistribution du poids du sol (principe repris de TerraCheck)
            active = weights["rain"] + weights["temp"]
            total = (rain_score * weights["rain"] + temp_score * weights["temp"]) / active
        else:
            total = (
                rain_score * weights["rain"]
                + temp_score * weights["temp"]
                + soil_score * weights["soil"]
            )

        if total >= 75:
            verdict = "très adaptée"
        elif total >= 55:
            verdict = "adaptée"
        elif total >= 35:
            verdict = "marginale"
        else:
            verdict = "déconseillée"

        results.append({
            "crop": crop_id,
            "label": crop["label"],
            "score": round(total, 1),
            "verdict": verdict,
            "breakdown": {
                "rainfall": round(rain_score, 1),
                "temperature": round(temp_score, 1),
                "soil": round(soil_score, 1) if soil_score is not None else None,
            },
            "requirements": {
                "rain_mm": [crop["rain_min"], crop["rain_max"]],
                "opt_temp_c": crop["opt_temp"],
                "cycle_days": crop["cycle_days"],
                "preferred_soils": crop["soils"],
            },
            "yield_max_t_ha": crop["yield_max_t_ha"],
        })

    results.sort(key=lambda r: r["score"], reverse=True)

    return {
        "location": {"latitude": payload.latitude, "longitude": payload.longitude},
        "year": payload.year,
        "climate": {
            "annual_rainfall_mm": annual_rain,
            "mean_temperature_c": mean_temp,
            "rainy_days": rain_summary.get("rainy_days"),
            "agro_zone": zone,
        },
        "soil": payload.soil,
        "ranking": results,
        "best": results[0] if results else None,
        "source": "NASA POWER",
    }


@router.post("/vegetation", summary="Suivi de végétation par satellite")
def vegetation(payload: dict[str, Any]) -> dict[str, Any]:
    """Redirige vers le module raster pour les indices réels.

    AGRISIGHT générait ici des courbes NDVI synthétiques (sinusoïde + bruit).
    Cet endpoint documente la marche à suivre pour obtenir des valeurs réelles.
    """
    raise HTTPException(
        400,
        "Les indices de végétation proviennent du module raster (Sentinel-2 réel). "
        "Utilisez POST /api/raster/timeseries avec dataset='sentinel2' et index='NDVI', "
        "ou POST /api/raster/tiles pour l'affichage cartographique. "
        "Aucune courbe NDVI n'est simulée par cette plateforme.",
    )
