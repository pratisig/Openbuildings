"""Module imagerie satellite & indices — Google Earth Engine.

Consolidé depuis `openmapagents/backend/gee_routes.py`, avec les corrections
suivantes : plus d'identifiants codés en dur, dégradation explicite (503 avec
message d'action) au lieu d'un plantage, et séries temporelles d'indices.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import cache
from ..core.schemas import AreaOfInterest
from ..services import gee

log = logging.getLogger("pratisig.raster")
router = APIRouter(prefix="/api/raster", tags=["imagerie"])

CACHE_NS = "raster"


class TileRequest(BaseModel):
    dataset: str = Field(..., description="Voir /api/raster/datasets")
    index: str = Field(..., description="Indice ou composition, ex: NDVI, RGB")
    area: AreaOfInterest
    date_start: str = Field(..., description="AAAA-MM-JJ")
    date_end: str = Field(..., description="AAAA-MM-JJ")
    cloud_max: float = Field(20.0, ge=0, le=100)
    composite: str = Field("median", description="median | mosaic | least_cloudy")
    clip: bool = True
    vis_override: dict[str, Any] | None = None


class TimeSeriesRequest(BaseModel):
    dataset: str
    index: str
    area: AreaOfInterest
    date_start: str
    date_end: str
    cloud_max: float = Field(30.0, ge=0, le=100)
    scale: int = Field(100, ge=10, le=5000, description="Résolution d'échantillonnage en mètres")
    reducer: str = Field("mean", description="mean | median | max | min")


def _dataset_or_404(dataset: str) -> dict[str, Any]:
    if dataset not in gee.DATASETS:
        raise HTTPException(404, f"Jeu de données inconnu. Disponibles : {list(gee.DATASETS)}")
    return gee.DATASETS[dataset]


def _ee_or_503() -> Any:
    try:
        return gee.require()
    except gee.GEEUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


def _region(area: AreaOfInterest) -> Any:
    ee = _ee_or_503()
    geometry = area.geometry()
    if geometry is not None:
        return gee.geojson_to_ee(geometry)
    bbox = area.resolve_bbox()
    return ee.Geometry.BBox(bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax)


def _build_image(ee: Any, meta: dict[str, Any], payload: TileRequest | TimeSeriesRequest, region: Any) -> Any:
    if meta.get("image"):
        return ee.Image(meta["collection"])

    collection = ee.ImageCollection(meta["collection"]).filterBounds(region.bounds())
    if not meta.get("static"):
        collection = collection.filterDate(payload.date_start, payload.date_end)
    if meta.get("cloud_property") and payload.cloud_max < 100:
        prop = meta["cloud_property"]
        filtered = collection.filter(
            ee.Filter.And(ee.Filter.notNull([prop]), ee.Filter.lte(prop, payload.cloud_max))
        )
        if filtered.size().getInfo() > 0:
            collection = filtered

    size = collection.size().getInfo()
    if size == 0:
        raise HTTPException(
            422,
            f"Aucune image {meta['label']} entre {payload.date_start} et {payload.date_end} "
            "sur cette zone. Élargissez la période ou augmentez le seuil de nuages.",
        )

    composite = getattr(payload, "composite", "median")
    if meta.get("static"):
        return collection.first()
    if composite == "mosaic":
        return collection.mosaic()
    if composite == "least_cloudy" and meta.get("cloud_property"):
        return collection.sort(meta["cloud_property"]).first()
    return collection.median()


@router.get("/status", summary="État du service Earth Engine")
def status() -> dict[str, Any]:
    return gee.status()


@router.get("/datasets", summary="Catalogue des jeux de données")
def datasets() -> dict[str, Any]:
    return {
        "datasets": [{"id": key, **meta} for key, meta in gee.DATASETS.items()],
        "count": len(gee.DATASETS),
        "gee": gee.status(),
    }


@router.post("/tiles", summary="Générer des tuiles pour un indice")
def tiles(payload: TileRequest) -> dict[str, Any]:
    meta = _dataset_or_404(payload.dataset)
    if payload.index not in meta["indices"]:
        raise HTTPException(
            400, f"Indice '{payload.index}' indisponible pour {payload.dataset}. Choisir : {meta['indices']}"
        )
    ee = _ee_or_503()
    region = _region(payload.area)

    try:
        image = _build_image(ee, meta, payload, region)
        image = gee.compute_index(image, payload.dataset, payload.index)
        if payload.clip:
            image = image.clip(region)

        vis = {**gee.VIS_PARAMS.get((payload.dataset, payload.index), {}), **(payload.vis_override or {})}
        url = gee.tile_url(image, vis)
        if not url:
            raise HTTPException(500, "Impossible de générer l'URL de tuiles")

        try:
            image_date = image.date().format("YYYY-MM-dd").getInfo()
        except Exception:
            image_date = payload.date_start

        return {
            "tile_url": url,
            "dataset": payload.dataset,
            "label": meta["label"],
            "index": payload.index,
            "date": image_date,
            "vis_params": vis,
            "bbox": payload.area.resolve_bbox().to_list(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Erreur Earth Engine : {exc}") from exc


@router.post("/timeseries", summary="Série temporelle d'un indice sur une zone")
def timeseries(payload: TimeSeriesRequest) -> dict[str, Any]:
    meta = _dataset_or_404(payload.dataset)
    if meta.get("static"):
        raise HTTPException(400, f"{meta['label']} est un jeu statique, sans série temporelle")
    ee = _ee_or_503()
    region = _region(payload.area)

    key = cache.cache_key(
        "timeseries",
        payload.dataset,
        payload.index,
        payload.date_start,
        payload.date_end,
        payload.scale,
        payload.reducer,
        payload.area.resolve_bbox().to_list(),
    )
    cached = cache.get(CACHE_NS, key)
    if cached is not None:
        return cached

    try:
        collection = (
            ee.ImageCollection(meta["collection"])
            .filterBounds(region.bounds())
            .filterDate(payload.date_start, payload.date_end)
        )
        if meta.get("cloud_property") and payload.cloud_max < 100:
            prop = meta["cloud_property"]
            collection = collection.filter(
                ee.Filter.And(ee.Filter.notNull([prop]), ee.Filter.lte(prop, payload.cloud_max))
            )

        size = collection.size().getInfo()
        if size == 0:
            raise HTTPException(422, "Aucune image sur cette période et cette zone")
        if size > 300:
            collection = collection.limit(300)

        reducers = {
            "mean": ee.Reducer.mean(),
            "median": ee.Reducer.median(),
            "max": ee.Reducer.max(),
            "min": ee.Reducer.min(),
        }
        reducer = reducers.get(payload.reducer, ee.Reducer.mean())
        dataset_id = payload.dataset
        index_id = payload.index

        def reduce_image(image):
            computed = gee.compute_index(image, dataset_id, index_id)
            stats = computed.reduceRegion(
                reducer=reducer, geometry=region, scale=payload.scale, maxPixels=1e9, bestEffort=True
            )
            return ee.Feature(
                None,
                {
                    "date": image.date().format("YYYY-MM-dd"),
                    "value": stats.values().get(0),
                },
            )

        results = collection.map(reduce_image).getInfo()
        points = [
            {"date": f["properties"]["date"], "value": f["properties"].get("value")}
            for f in results.get("features", [])
            if f["properties"].get("value") is not None
        ]
        points.sort(key=lambda p: p["date"])

        values = [p["value"] for p in points]
        summary = {}
        if values:
            ordered = sorted(values)
            mid = len(ordered) // 2
            summary = {
                "count": len(values),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "mean": round(sum(values) / len(values), 4),
                "median": round(
                    ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2, 4
                ),
            }

        result = {
            "dataset": payload.dataset,
            "label": meta["label"],
            "index": payload.index,
            "period": {"start": payload.date_start, "end": payload.date_end},
            "scale_m": payload.scale,
            "reducer": payload.reducer,
            "points": points,
            "summary": summary,
        }
        cache.set(CACHE_NS, key, result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Erreur Earth Engine : {exc}") from exc
