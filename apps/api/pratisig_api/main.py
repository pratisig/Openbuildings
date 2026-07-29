"""PratiSIG Platform — application FastAPI unifiée.

Point d'entrée unique remplaçant : 4 apps Streamlit autonomes, une API Flask,
deux backends FastAPI concurrents et plusieurs front-ends dispersés.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .core import cache
from .core.duckdb_engine import engine
from .core.http import UpstreamError, close_client
from .modules import (
    admin,
    agent,
    agriculture,
    buildings,
    catalog,
    climate,
    exports,
    flood,
    geocoding,
    land,
    osm,
    overture,
    raster,
    routing,
    spatial,
)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("pratisig")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Démarrage de %s v%s (%s)", settings.app_name, settings.version, settings.environment)
    settings.ensure_dirs()
    if engine.available:
        log.info("DuckDB opérationnel")
    else:
        log.warning("DuckDB indisponible — les modules Overture et Open Buildings seront limités")
    yield
    engine.close()
    await close_client()
    log.info("Arrêt de la plateforme")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "API géospatiale unifiée pour le Sénégal et l'Afrique de l'Ouest.\n\n"
        "Rassemble en un seul service les projets auparavant dispersés : "
        "Open Buildings, Overture Maps, OpenStreetMap, découpage administratif, "
        "géocodage, itinéraires, analyse spatiale, imagerie satellite, "
        "inondations, climat, exports et agent cartographique.\n\n"
        "Voir `/api/catalog` pour la liste des modules et "
        "`/api/catalog/migration` pour la traçabilité des dépôts d'origine."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Feature-Count"],
)


@app.exception_handler(UpstreamError)
async def upstream_error_handler(request: Request, exc: UpstreamError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "Service externe indisponible", "service": exc.service, "detail": exc.detail},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Requête invalide", "detail": str(exc)})


# ── Routeurs des modules ───────────────────────────────────────────
for module in (
    catalog,
    buildings,
    overture,
    osm,
    admin,
    geocoding,
    routing,
    spatial,
    raster,
    flood,
    climate,
    agriculture,
    land,
    exports,
    agent,
):
    app.include_router(module.router)


@app.get("/", tags=["système"], summary="Présentation de la plateforme")
def root() -> dict[str, Any]:
    return {
        "platform": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "documentation": "/docs",
        "catalog": "/api/catalog",
        "migration": "/api/catalog/migration",
        "health": "/health",
        "modules": [m["id"] for m in catalog.MODULES],
    }


@app.get("/health", tags=["système"], summary="État de santé des services")
def health() -> dict[str, Any]:
    from .services import gee

    duckdb_health = engine.health()
    gee_health = gee.status()

    services = {
        "duckdb": {
            "status": "ok" if duckdb_health.get("status") == "ok" else "unavailable",
            "detail": duckdb_health.get("version") or duckdb_health.get("detail"),
            "powers": ["buildings", "overture"],
        },
        "earthengine": {
            "status": "ok" if gee_health["ready"] else "unavailable",
            "detail": gee_health.get("error") or "prêt",
            "powers": ["raster", "flood"],
        },
        "shapely": {
            "status": "ok" if spatial.SHAPELY else "degraded",
            "detail": "opérations géométriques avancées" if spatial.SHAPELY else "repli pur Python",
            "powers": ["spatial"],
        },
        "geopandas": {
            "status": "ok" if exports.GEOPANDAS else "degraded",
            "detail": "tous formats" if exports.GEOPANDAS else "GeoJSON/CSV uniquement",
            "powers": ["exports"],
        },
        "llm": {
            "status": "ok" if (settings.llm_enabled and settings.llm_api_key) else "unavailable",
            "detail": settings.llm_model if settings.llm_enabled else "désactivé",
            "powers": ["agent"],
        },
    }

    degraded = [k for k, v in services.items() if v["status"] != "ok"]
    return {
        "status": "ok" if not degraded else "degraded",
        "version": settings.version,
        "services": services,
        "degraded": degraded,
        "cache": cache.stats(),
    }


@app.post("/api/cache/clear", tags=["système"], summary="Vider le cache")
def clear_cache(namespace: str | None = None) -> dict[str, Any]:
    removed = cache.clear(namespace)
    return {"cleared": removed, "namespace": namespace or "tous"}
