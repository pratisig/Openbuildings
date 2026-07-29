"""Module climat — NASA POWER.

Repris de `pratisig/floodingsn` (fonction `get_climate_data`), avec gestion
d'erreurs explicite, statistiques dérivées et cache.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from ..config import settings
from ..core import cache
from ..core.http import UpstreamError, get_json

log = logging.getLogger("pratisig.climate")
router = APIRouter(prefix="/api/climate", tags=["climat"])

CACHE_NS = "climate"

PARAMETERS: dict[str, dict[str, str]] = {
    "PRECTOTCORR": {"label": "Précipitations", "unit": "mm/jour"},
    "T2M": {"label": "Température moyenne à 2 m", "unit": "°C"},
    "T2M_MAX": {"label": "Température maximale", "unit": "°C"},
    "T2M_MIN": {"label": "Température minimale", "unit": "°C"},
    "RH2M": {"label": "Humidité relative", "unit": "%"},
    "WS2M": {"label": "Vitesse du vent à 2 m", "unit": "m/s"},
    "ALLSKY_SFC_SW_DWN": {"label": "Rayonnement solaire", "unit": "kWh/m²/jour"},
}


class ClimateRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    start: str = Field(..., description="Date de début AAAA-MM-JJ")
    end: str = Field(..., description="Date de fin AAAA-MM-JJ")
    parameters: list[str] = Field(default_factory=lambda: ["PRECTOTCORR", "T2M"])

    @model_validator(mode="after")
    def _check(self) -> ClimateRequest:
        try:
            start = date.fromisoformat(self.start)
            end = date.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError("Dates attendues au format AAAA-MM-JJ") from exc
        if start > end:
            raise ValueError("La date de début doit précéder la date de fin")
        if (end - start) > timedelta(days=366 * 15):
            raise ValueError("Période limitée à 15 ans")
        unknown = [p for p in self.parameters if p not in PARAMETERS]
        if unknown:
            raise ValueError(f"Paramètres inconnus : {unknown}. Disponibles : {list(PARAMETERS)}")
        return self


def _summarize(values: list[float | None], param: str) -> dict[str, Any]:
    clean = [v for v in values if v is not None and v > -900]
    if not clean:
        return {"count": 0}
    ordered = sorted(clean)
    mid = len(ordered) // 2
    summary: dict[str, Any] = {
        "count": len(clean),
        "min": round(min(clean), 2),
        "max": round(max(clean), 2),
        "mean": round(sum(clean) / len(clean), 2),
        "median": round(
            ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2, 2
        ),
    }
    if param == "PRECTOTCORR":
        summary["total_mm"] = round(sum(clean), 1)
        summary["rainy_days"] = sum(1 for v in clean if v >= 1.0)
        summary["heavy_rain_days"] = sum(1 for v in clean if v >= 20.0)
    return summary


@router.get("/parameters", summary="Paramètres climatiques disponibles")
def parameters() -> dict[str, Any]:
    return {
        "parameters": [{"id": key, **meta} for key, meta in PARAMETERS.items()],
        "source": "NASA POWER (daily point)",
    }


@router.post("/timeseries", summary="Série climatique journalière")
async def timeseries(payload: ClimateRequest) -> dict[str, Any]:
    start = payload.start.replace("-", "")
    end = payload.end.replace("-", "")
    params_str = ",".join(payload.parameters)

    key = cache.cache_key(
        "power", round(payload.latitude, 3), round(payload.longitude, 3), start, end, params_str
    )
    cached = cache.get(CACHE_NS, key, ttl=0)
    if cached is not None:
        return cached

    try:
        raw = await get_json(
            "nasa-power",
            settings.nasa_power_url,
            params={
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "start": start,
                "end": end,
                "parameters": params_str,
                "community": "AG",
                "format": "JSON",
            },
        )
    except UpstreamError as exc:
        raise HTTPException(exc.status_code, f"NASA POWER : {exc.detail}") from exc

    try:
        raw_params = raw["properties"]["parameter"]
    except (KeyError, TypeError) as exc:
        raise HTTPException(502, "Réponse NASA POWER inattendue") from exc

    dates = sorted(next(iter(raw_params.values())).keys())
    series: dict[str, list[float | None]] = {}
    summaries: dict[str, Any] = {}
    for param, values in raw_params.items():
        ordered = [
            (None if values.get(d) is None or values.get(d) <= -900 else round(values[d], 2))
            for d in dates
        ]
        series[param] = ordered
        summaries[param] = {**_summarize(ordered, param), **PARAMETERS.get(param, {})}

    result = {
        "location": {"latitude": payload.latitude, "longitude": payload.longitude},
        "period": {"start": payload.start, "end": payload.end, "days": len(dates)},
        "dates": [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates],
        "series": series,
        "summary": summaries,
        "source": "NASA POWER",
    }
    cache.set(CACHE_NS, key, result)
    return result
