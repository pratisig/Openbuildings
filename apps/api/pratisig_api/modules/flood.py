"""Module inondations — détection SAR et exposition.

Fusion de `pratisig/floodingsn` et `pratisig/innondationSN`, deux dépôts qui
faisaient la même chose (« FloodWatch WA ») à des stades différents :

  * floodingsn   : interface aboutie mais analyse en données factices ;
  * innondationSN: vraie logique SAR Sentinel-1 anti-surestimation + WorldPop.

C'est la logique SAR d'innondationSN qui est retenue, exposée en API, avec le
masque de pente, le filtre de bruit et le croisement infrastructures.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from ..core.schemas import AreaOfInterest
from ..services import gee

log = logging.getLogger("pratisig.flood")
router = APIRouter(prefix="/api/flood", tags=["inondations"])


class FloodAnalysisRequest(BaseModel):
    area: AreaOfInterest
    flood_start: str = Field(..., description="Début de la période de crue AAAA-MM-JJ")
    flood_end: str = Field(..., description="Fin de la période de crue AAAA-MM-JJ")
    reference_start: str | None = Field(None, description="Par défaut : même période l'année précédente")
    reference_end: str | None = None
    threshold_db: float = Field(
        1.3, ge=0.5, le=5.0, description="Baisse de rétrodiffusion VV (dB) indiquant de l'eau"
    )
    max_slope_deg: float = Field(
        5.0, ge=0, le=30, description="Pente maximale — évite les faux positifs en relief"
    )
    scale_m: int = Field(30, ge=10, le=500)
    include_population: bool = True
    include_geometry: bool = Field(False, description="Retourner le contour vectorisé (plus lent)")

    @model_validator(mode="after")
    def _defaults(self) -> FloodAnalysisRequest:
        if not self.reference_start:
            year = int(self.flood_start[:4]) - 1
            self.reference_start = f"{year}{self.flood_start[4:]}"
        if not self.reference_end:
            year = int(self.flood_end[:4]) - 1
            self.reference_end = f"{year}{self.flood_end[4:]}"
        return self


class ExposureRequest(BaseModel):
    """Croise un masque d'inondation avec des infrastructures fournies."""

    area: AreaOfInterest
    flood_start: str
    flood_end: str
    infrastructure: dict[str, Any] = Field(..., description="FeatureCollection à évaluer")
    threshold_db: float = Field(1.3, ge=0.5, le=5.0)
    max_slope_deg: float = Field(5.0, ge=0, le=30)


def _ee_or_503() -> Any:
    try:
        return gee.require()
    except gee.GEEUnavailable as exc:
        raise HTTPException(
            503,
            f"{exc} La détection d'inondations repose sur Sentinel-1 via Earth Engine.",
        ) from exc


def _region(area: AreaOfInterest) -> Any:
    ee = _ee_or_503()
    geometry = area.geometry()
    if geometry is not None:
        return gee.geojson_to_ee(geometry)
    bbox = area.resolve_bbox()
    return ee.Geometry.BBox(bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax)


def _flood_mask(
    ee: Any,
    region: Any,
    flood_start: str,
    flood_end: str,
    ref_start: str,
    ref_end: str,
    threshold_db: float,
    max_slope_deg: float,
) -> Any:
    """Masque d'eau par différence de rétrodiffusion VV (approche innondationSN).

    Principe : l'eau libre réfléchit le signal radar loin du capteur, donc la
    rétrodiffusion chute fortement. On compare la période de crue à une
    référence sèche, on exige une baisse supérieure au seuil, puis on filtre
    les zones en pente (l'eau ne stagne pas) et le bruit poivre-et-sel.
    """
    s1 = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(region)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )

    reference_col = s1.filterDate(ref_start, ref_end)
    flood_col = s1.filterDate(flood_start, flood_end)

    ref_size = reference_col.size().getInfo()
    flood_size = flood_col.size().getInfo()
    if flood_size == 0:
        raise HTTPException(
            422, f"Aucune image Sentinel-1 entre {flood_start} et {flood_end} sur cette zone"
        )
    if ref_size == 0:
        raise HTTPException(
            422,
            f"Aucune image Sentinel-1 de référence entre {ref_start} et {ref_end}. "
            "Précisez reference_start / reference_end.",
        )

    # Filtre speckle : médiane focale de 30 m
    reference = reference_col.median().focal_median(30, "circle", "meters")
    flood = flood_col.median().focal_median(30, "circle", "meters")

    difference = flood.subtract(reference)
    mask = difference.lt(-threshold_db)

    # Masque de pente : l'eau stagnante ne tient pas sur les fortes pentes
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
    mask = mask.updateMask(slope.lt(max_slope_deg))

    # Ouverture morphologique : supprime les pixels isolés
    mask = mask.focal_min(20, "circle", "meters").focal_max(20, "circle", "meters")

    # Exclut les eaux permanentes (JRC) pour ne garder que l'inondation
    try:
        permanent = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("seasonality").gte(10)
        mask = mask.updateMask(permanent.unmask(0).Not())
    except Exception:
        log.warning("Couche JRC eaux permanentes indisponible")

    return mask.selfMask().rename("flood"), {"reference_images": ref_size, "flood_images": flood_size}


@router.get("/status", summary="État du module inondations")
def status() -> dict[str, Any]:
    gee_status = gee.status()
    return {
        "module": "flood",
        "available": gee_status["ready"],
        "method": "Différence de rétrodiffusion Sentinel-1 VV avec masque de pente",
        "datasets": [
            "COPERNICUS/S1_GRD",
            "USGS/SRTMGL1_003",
            "JRC/GSW1_4/GlobalSurfaceWater",
            "WorldPop/GP/100m/pop",
        ],
        "gee": gee_status,
    }


@router.post("/analyze", summary="Détecter les zones inondées")
def analyze(payload: FloodAnalysisRequest) -> dict[str, Any]:
    ee = _ee_or_503()
    region = _region(payload.area)

    try:
        mask, image_counts = _flood_mask(
            ee,
            region,
            payload.flood_start,
            payload.flood_end,
            payload.reference_start,
            payload.reference_end,
            payload.threshold_db,
            payload.max_slope_deg,
        )

        # Surface inondée
        area_image = mask.multiply(ee.Image.pixelArea())
        flooded_m2 = (
            area_image.reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=region,
                scale=payload.scale_m,
                maxPixels=1e10,
                bestEffort=True,
            ).get("flood").getInfo()
            or 0
        )
        total_m2 = region.area(maxError=10).getInfo() or 0

        result: dict[str, Any] = {
            "period": {
                "flood": [payload.flood_start, payload.flood_end],
                "reference": [payload.reference_start, payload.reference_end],
            },
            "parameters": {
                "threshold_db": payload.threshold_db,
                "max_slope_deg": payload.max_slope_deg,
                "scale_m": payload.scale_m,
            },
            "images": image_counts,
            "flooded_area_km2": round(flooded_m2 / 1e6, 3),
            "total_area_km2": round(total_m2 / 1e6, 3),
            "flooded_ratio_pct": round(flooded_m2 / total_m2 * 100, 2) if total_m2 else 0,
            "tile_url": gee.tile_url(mask, {"palette": ["#1a5276"], "min": 0, "max": 1}),
        }

        if payload.include_population:
            try:
                pop = ee.ImageCollection("WorldPop/GP/100m/pop").mosaic()
                total_pop = (
                    pop.reduceRegion(
                        reducer=ee.Reducer.sum(),
                        geometry=region,
                        scale=100,
                        maxPixels=1e10,
                        bestEffort=True,
                    ).get("population").getInfo()
                    or 0
                )
                exposed_pop = (
                    pop.updateMask(mask)
                    .reduceRegion(
                        reducer=ee.Reducer.sum(),
                        geometry=region,
                        scale=100,
                        maxPixels=1e10,
                        bestEffort=True,
                    ).get("population").getInfo()
                    or 0
                )
                result["population"] = {
                    "total": int(total_pop),
                    "exposed": int(exposed_pop),
                    "exposed_pct": round(exposed_pop / total_pop * 100, 2) if total_pop else 0,
                    "source": "WorldPop GP 100m",
                }
            except Exception as exc:
                log.warning("Estimation de population impossible : %s", exc)
                result["population"] = {"error": str(exc)}

        if payload.include_geometry:
            try:
                vectors = mask.reduceToVectors(
                    geometry=region,
                    scale=max(payload.scale_m, 50),
                    maxPixels=1e9,
                    bestEffort=True,
                    geometryType="polygon",
                )
                result["geojson"] = vectors.limit(500).getInfo()
            except Exception as exc:
                log.warning("Vectorisation impossible : %s", exc)
                result["geojson_error"] = str(exc)

        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Erreur Earth Engine : {exc}") from exc


@router.post("/exposure", summary="Infrastructures exposées à l'inondation")
def exposure(payload: ExposureRequest) -> dict[str, Any]:
    ee = _ee_or_503()
    region = _region(payload.area)

    features = [f for f in payload.infrastructure.get("features", []) if f.get("geometry")]
    if not features:
        raise HTTPException(400, "`infrastructure` ne contient aucune entité géométrique")
    if len(features) > 2000:
        raise HTTPException(400, "Limité à 2000 entités par requête")

    ref_start = f"{int(payload.flood_start[:4]) - 1}{payload.flood_start[4:]}"
    ref_end = f"{int(payload.flood_end[:4]) - 1}{payload.flood_end[4:]}"

    try:
        mask, _ = _flood_mask(
            ee,
            region,
            payload.flood_start,
            payload.flood_end,
            ref_start,
            ref_end,
            payload.threshold_db,
            payload.max_slope_deg,
        )

        ee_features = []
        for idx, f in enumerate(features):
            try:
                ee_features.append(ee.Feature(gee.geojson_to_ee(f["geometry"]), {"_idx": idx}))
            except Exception:
                continue
        collection = ee.FeatureCollection(ee_features)

        stats = mask.unmask(0).reduceRegions(
            collection=collection, reducer=ee.Reducer.mean(), scale=30
        ).getInfo()

        impacted_indices = {
            f["properties"]["_idx"]
            for f in stats.get("features", [])
            if (f["properties"].get("mean") or 0) > 0.1
        }

        out_features = []
        for idx, f in enumerate(features):
            props = {**(f.get("properties") or {}), "flood_impacted": idx in impacted_indices}
            out_features.append({"type": "Feature", "geometry": f["geometry"], "properties": props})

        return {
            "type": "FeatureCollection",
            "features": out_features,
            "metadata": {
                "total": len(out_features),
                "impacted": len(impacted_indices),
                "impacted_pct": round(len(impacted_indices) / len(out_features) * 100, 2),
                "period": [payload.flood_start, payload.flood_end],
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Erreur Earth Engine : {exc}") from exc
