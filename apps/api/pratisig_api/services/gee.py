"""Service Google Earth Engine — initialisation et catalogue partagés.

Trois initialisations GEE différentes existaient (`floodingsn` via secrets
Streamlit, `innondationSN` via service account JSON, `openmapagents` avec un
chemin de clé codé en dur et une adresse e-mail exposée dans le code).

Ici : une seule initialisation, configurée par variables d'environnement,
avec dégradation propre quand GEE n'est pas disponible.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import settings

log = logging.getLogger("pratisig.gee")

_state: dict[str, Any] = {"ready": False, "error": None, "checked": False}

DATASETS: dict[str, dict[str, Any]] = {
    "sentinel2": {
        "label": "Sentinel-2 SR (10 m)",
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "cloud_property": "CLOUDY_PIXEL_PERCENTAGE",
        "indices": ["RGB", "NDVI", "NDWI", "NDBI", "EVI", "NIR"],
        "revisit": "5 jours",
    },
    "sentinel1": {
        "label": "Sentinel-1 SAR (10 m)",
        "collection": "COPERNICUS/S1_GRD",
        "cloud_property": None,
        "indices": ["VV", "VH", "VV/VH"],
        "revisit": "6-12 jours",
    },
    "landsat9": {
        "label": "Landsat 9 (30 m)",
        "collection": "LANDSAT/LC09/C02/T1_L2",
        "cloud_property": "CLOUD_COVER",
        "indices": ["RGB", "NDVI", "NDWI", "LST"],
        "revisit": "16 jours",
    },
    "landsat8": {
        "label": "Landsat 8 (30 m)",
        "collection": "LANDSAT/LC08/C02/T1_L2",
        "cloud_property": "CLOUD_COVER",
        "indices": ["RGB", "NDVI", "NDWI", "LST"],
        "revisit": "16 jours",
    },
    "modis_ndvi": {
        "label": "MODIS NDVI (500 m)",
        "collection": "MODIS/061/MOD13A1",
        "cloud_property": None,
        "indices": ["NDVI", "EVI"],
        "revisit": "16 jours",
    },
    "modis_lst": {
        "label": "MODIS température de surface (1 km)",
        "collection": "MODIS/061/MOD11A1",
        "cloud_property": None,
        "indices": ["LST Jour", "LST Nuit"],
        "revisit": "1 jour",
    },
    "worldcover": {
        "label": "ESA WorldCover 2021 (10 m)",
        "collection": "ESA/WorldCover/v200",
        "cloud_property": None,
        "indices": ["Occupation du sol"],
        "revisit": "annuel",
        "static": True,
    },
    "srtm": {
        "label": "SRTM relief (30 m)",
        "collection": "USGS/SRTMGL1_003",
        "cloud_property": None,
        "indices": ["Élévation", "Pente", "Ombrage"],
        "revisit": "statique",
        "static": True,
        "image": True,
    },
    "era5": {
        "label": "ERA5-Land mensuel (11 km)",
        "collection": "ECMWF/ERA5_LAND/MONTHLY_AGGR",
        "cloud_property": None,
        "indices": ["Température", "Précipitations"],
        "revisit": "mensuel",
    },
    "worldpop": {
        "label": "WorldPop population (100 m)",
        "collection": "WorldPop/GP/100m/pop",
        "cloud_property": None,
        "indices": ["Population"],
        "revisit": "annuel",
    },
}

VIS_PARAMS: dict[tuple[str, str], dict[str, Any]] = {
    ("sentinel2", "RGB"): {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000, "gamma": 1.4},
    ("sentinel2", "NIR"): {"bands": ["B8", "B4", "B3"], "min": 0, "max": 5000},
    ("sentinel2", "NDVI"): {"palette": ["#d73027", "#fdae61", "#d9ef8b", "#1a9850"], "min": -0.2, "max": 0.8},
    ("sentinel2", "NDWI"): {"palette": ["#8B4513", "#ffffff", "#1A5276"], "min": -0.5, "max": 0.5},
    ("sentinel2", "NDBI"): {"palette": ["#1a9850", "#fee08b", "#d73027"], "min": -0.5, "max": 0.5},
    ("sentinel2", "EVI"): {"palette": ["#d73027", "#fdae61", "#d9ef8b", "#1a9850"], "min": -0.2, "max": 0.8},
    ("sentinel1", "VV"): {"bands": ["VV"], "min": -20, "max": 0},
    ("sentinel1", "VH"): {"bands": ["VH"], "min": -25, "max": -5},
    ("landsat9", "RGB"): {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 5000, "max": 25000, "gamma": 1.4},
    ("landsat8", "RGB"): {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 5000, "max": 25000, "gamma": 1.4},
    ("landsat9", "NDVI"): {"palette": ["#d73027", "#fdae61", "#d9ef8b", "#1a9850"], "min": -0.2, "max": 0.8},
    ("landsat8", "NDVI"): {"palette": ["#d73027", "#fdae61", "#d9ef8b", "#1a9850"], "min": -0.2, "max": 0.8},
    ("landsat9", "LST"): {"palette": ["#040274", "#3288bd", "#abdda4", "#fdae61", "#d53e4f"], "min": 270, "max": 320},
    ("landsat8", "LST"): {"palette": ["#040274", "#3288bd", "#abdda4", "#fdae61", "#d53e4f"], "min": 270, "max": 320},
    ("modis_ndvi", "NDVI"): {"palette": ["#d73027", "#fdae61", "#d9ef8b", "#1a9850"], "min": -2000, "max": 10000},
    ("modis_lst", "LST Jour"): {"palette": ["#040274", "#3288bd", "#abdda4", "#fdae61", "#d53e4f"], "min": 270, "max": 330},
    ("worldcover", "Occupation du sol"): {
        "min": 10,
        "max": 100,
        "palette": ["006400", "ffbb22", "ffff4c", "f096ff", "fa0000", "b4b4b4", "f0f0f0", "0064c8", "0096a0", "00cf75", "fae6a0"],
    },
    ("srtm", "Élévation"): {"palette": ["#313695", "#74add1", "#e0f3f8", "#fee090", "#f46d43", "#a50026"], "min": 0, "max": 3000},
    ("srtm", "Pente"): {"palette": ["#ffffff", "#fdae61", "#d73027"], "min": 0, "max": 60},
    ("era5", "Précipitations"): {"bands": ["total_precipitation_sum"], "palette": ["#ffffff", "#AED6F1", "#1A5276"], "min": 0, "max": 0.3},
    ("worldpop", "Population"): {"palette": ["#ffffcc", "#fd8d3c", "#800026"], "min": 0, "max": 100},
}


class GEEUnavailable(RuntimeError):
    """Google Earth Engine n'est pas configuré ou joignable."""


def initialize() -> bool:
    """Initialise GEE via compte de service. Idempotent."""
    if _state["ready"]:
        return True
    if _state["checked"] and _state["error"]:
        return False

    _state["checked"] = True
    try:
        import ee
    except ImportError:
        _state["error"] = "Le paquet `earthengine-api` n'est pas installé"
        log.info("GEE désactivé : %s", _state["error"])
        return False

    try:
        credentials = None
        if settings.gee_service_account_email and settings.gee_service_account_key_json:
            credentials = ee.ServiceAccountCredentials(
                settings.gee_service_account_email,
                key_data=settings.gee_service_account_key_json,
            )
        elif settings.gee_service_account_email and settings.gee_service_account_key_file:
            credentials = ee.ServiceAccountCredentials(
                settings.gee_service_account_email,
                key_file=settings.gee_service_account_key_file,
            )

        if credentials is not None:
            ee.Initialize(credentials)
        else:
            ee.Initialize()  # identifiants utilisateur locaux

        ee.Number(1).getInfo()  # test de connectivité
        _state["ready"] = True
        _state["error"] = None
        log.info("Google Earth Engine initialisé")
        return True
    except Exception as exc:
        _state["error"] = str(exc)
        log.warning("GEE indisponible : %s", exc)
        return False


def require() -> Any:
    """Retourne le module `ee` initialisé ou lève GEEUnavailable."""
    if not initialize():
        raise GEEUnavailable(
            _state["error"]
            or "Google Earth Engine non configuré. "
            "Renseigner PRATISIG_GEE_SERVICE_ACCOUNT_EMAIL et PRATISIG_GEE_SERVICE_ACCOUNT_KEY_FILE."
        )
    import ee

    return ee


def status() -> dict[str, Any]:
    ready = initialize()
    return {
        "ready": ready,
        "error": _state["error"],
        "configured": bool(settings.gee_service_account_email),
        "datasets": len(DATASETS),
    }


def geojson_to_ee(geometry: dict[str, Any]) -> Any:
    """Convertit une géométrie GeoJSON en ee.Geometry."""
    ee = require()
    gtype = geometry.get("type")
    if gtype == "Polygon":
        return ee.Geometry.Polygon(geometry["coordinates"])
    if gtype == "MultiPolygon":
        return ee.Geometry.MultiPolygon(geometry["coordinates"])
    if gtype == "Point":
        return ee.Geometry.Point(geometry["coordinates"])
    if gtype == "GeometryCollection":
        parts = [geojson_to_ee(g) for g in geometry.get("geometries", [])]
        return ee.Geometry.MultiPolygon([p for p in parts])
    from ..core.geo import BBox

    bbox = BBox.from_geojson(geometry)
    return ee.Geometry.BBox(bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax)


def compute_index(image: Any, dataset: str, index: str) -> Any:
    """Calcule un indice spectral. Consolidé depuis openmapagents/gee_routes.py."""
    ee = require()
    if index == "NDVI":
        if dataset == "sentinel2":
            return image.normalizedDifference(["B8", "B4"]).rename("NDVI")
        if dataset in ("landsat8", "landsat9"):
            return image.normalizedDifference(["SR_B5", "SR_B4"]).rename("NDVI")
        if dataset == "modis_ndvi":
            return image.select("NDVI")
    if index == "NDWI":
        if dataset == "sentinel2":
            return image.normalizedDifference(["B3", "B8"]).rename("NDWI")
        if dataset in ("landsat8", "landsat9"):
            return image.normalizedDifference(["SR_B3", "SR_B5"]).rename("NDWI")
    if index == "NDBI" and dataset == "sentinel2":
        return image.normalizedDifference(["B11", "B8"]).rename("NDBI")
    if index == "EVI":
        if dataset == "sentinel2":
            nir = image.select("B8").multiply(0.0001)
            red = image.select("B4").multiply(0.0001)
            blue = image.select("B2").multiply(0.0001)
            return (
                nir.subtract(red)
                .multiply(2.5)
                .divide(nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1))
                .rename("EVI")
            )
        if dataset == "modis_ndvi":
            return image.select("EVI")
    if index in ("LST", "LST Jour", "LST Nuit"):
        if dataset in ("landsat8", "landsat9"):
            return image.select("ST_B10").multiply(0.00341802).add(149.0).rename("LST")
        if dataset == "modis_lst":
            band = "LST_Night_1km" if "Nuit" in index else "LST_Day_1km"
            return image.select(band).multiply(0.02).rename("LST")
    if index == "Pente":
        return ee.Terrain.slope(image).rename("slope")
    if index == "Ombrage":
        return ee.Terrain.hillshade(image).rename("hillshade")
    if index in ("VV", "VH"):
        return image.select(index)
    if index == "VV/VH":
        return image.select("VV").divide(image.select("VH")).rename("VV_VH")
    return image


def tile_url(image: Any, vis: dict[str, Any]) -> str:
    """Génère l'URL de tuiles XYZ d'une image GEE."""
    map_id = image.getMapId(vis)
    fetcher = map_id.get("tile_fetcher")
    if fetcher is not None and hasattr(fetcher, "url_format"):
        return fetcher.url_format
    return map_id.get("urlFormat", "")
