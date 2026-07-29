"""Catalogue central des modules de la plateforme.

C'est la réponse directe au problème « je ne me rappelle plus la fonction de
certains projets » : chaque module déclare son origine (dépôt d'origine), son
rôle, ses endpoints et ses dépendances. Le front l'utilise pour construire
sa navigation dynamiquement.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/catalog", tags=["catalogue"])

MODULES: list[dict[str, Any]] = [
    {
        "id": "buildings",
        "label": "Empreintes de bâtiments",
        "icon": "building",
        "group": "Données",
        "summary": (
            "Téléchargement et analyse des empreintes Google + Microsoft Open Buildings "
            "(2,5 milliards de bâtiments, 185 pays) via GeoParquet cloud-native."
        ),
        "origin": ["pratisig/Openbuildings", "pratisig/openbuildings_app"],
        "endpoints": [
            "GET /api/buildings/countries",
            "POST /api/buildings/query",
            "POST /api/buildings/stats",
        ],
        "requires": ["duckdb", "réseau"],
        "status": "actif",
    },
    {
        "id": "overture",
        "label": "Overture Maps",
        "icon": "layers",
        "group": "Données",
        "summary": (
            "Requêtes directes sur les thèmes Overture (places, buildings, transportation, "
            "divisions, base, addresses) en SQL DuckDB sur S3."
        ),
        "origin": ["pratisig/openmapagents"],
        "endpoints": [
            "GET /api/overture/themes",
            "POST /api/overture/query",
            "POST /api/overture/stats",
        ],
        "requires": ["duckdb", "réseau"],
        "status": "actif",
    },
    {
        "id": "osm",
        "label": "OpenStreetMap / Overpass",
        "icon": "road",
        "group": "Données",
        "summary": (
            "Extraction de réseaux routiers, bâtiments et POI OSM par zone. "
            "Reprend la logique de requêtage de city-roads côté serveur."
        ),
        "origin": ["pratisig/city-roads", "pratisig/innondationSN"],
        "endpoints": [
            "GET /api/osm/presets",
            "POST /api/osm/query",
            "POST /api/osm/roads",
        ],
        "requires": ["réseau"],
        "status": "actif",
    },
    {
        "id": "admin",
        "label": "Découpage administratif",
        "icon": "map",
        "group": "Données",
        "summary": (
            "Limites administratives : pays (Natural Earth/local), niveaux GADM 0-4, "
            "et les 4 niveaux du Sénégal (régions, départements, arrondissements, communes)."
        ),
        "origin": ["pratisig/Carto-facileSN", "pratisig/floodingsn"],
        "endpoints": [
            "GET /api/admin/countries",
            "GET /api/admin/gadm/{iso3}/{level}",
            "GET /api/admin/senegal/{niveau}",
        ],
        "requires": ["réseau"],
        "status": "actif",
    },
    {
        "id": "geocoding",
        "label": "Géocodage",
        "icon": "search",
        "group": "Services",
        "summary": "Recherche de lieux et géocodage inverse via Nominatim, avec cache partagé.",
        "origin": ["pratisig/openmapagents", "pratisig/city-roads"],
        "endpoints": ["GET /api/geocoding/search", "GET /api/geocoding/reverse"],
        "requires": ["réseau"],
        "status": "actif",
    },
    {
        "id": "routing",
        "label": "Itinéraires & isochrones",
        "icon": "route",
        "group": "Analyse",
        "summary": (
            "Calcul d'itinéraires plus courts, matrices de distances et zones "
            "d'accessibilité (isochrones) — socle des cas d'usage santé/accessibilité."
        ),
        "origin": ["pratisig/GeoRouteX", "pratisig/openmapagents", "pratisig/sante-isochrones-app"],
        "endpoints": [
            "POST /api/routing/route",
            "POST /api/routing/isochrone",
            "POST /api/routing/accessibility",
        ],
        "requires": ["réseau"],
        "status": "actif",
    },
    {
        "id": "spatial",
        "label": "Analyse spatiale",
        "icon": "sparkles",
        "group": "Analyse",
        "summary": (
            "Opérations vectorielles serveur : buffer, clip, points-dans-polygone, "
            "centroïdes, enveloppe convexe, dissolve, statistiques de couche."
        ),
        "origin": ["pratisig/openmapagents"],
        "endpoints": ["GET /api/spatial/operations", "POST /api/spatial/run"],
        "requires": [],
        "status": "actif",
    },
    {
        "id": "raster",
        "label": "Imagerie & indices (GEE)",
        "icon": "satellite",
        "group": "Analyse",
        "summary": (
            "Catalogue Sentinel-1/2, Landsat, MODIS, WorldCover, SRTM, ERA5 avec calcul "
            "d'indices (NDVI, NDWI, NDBI, EVI, LST) et génération de tuiles."
        ),
        "origin": ["pratisig/openmapagents", "pratisig/AgriSight_v2"],
        "endpoints": [
            "GET /api/raster/datasets",
            "POST /api/raster/tiles",
            "POST /api/raster/timeseries",
        ],
        "requires": ["earthengine-api", "compte GEE"],
        "status": "optionnel",
    },
    {
        "id": "flood",
        "label": "Inondations",
        "icon": "waves",
        "group": "Thématiques",
        "summary": (
            "Détection de zones inondées par comparaison SAR Sentinel-1 (référence vs crue), "
            "population exposée WorldPop et infrastructures impactées."
        ),
        "origin": ["pratisig/floodingsn", "pratisig/innondationSN"],
        "endpoints": ["POST /api/flood/analyze", "POST /api/flood/exposure"],
        "requires": ["earthengine-api", "compte GEE"],
        "status": "optionnel",
    },
    {
        "id": "climate",
        "label": "Climat",
        "icon": "cloud",
        "group": "Thématiques",
        "summary": "Séries climatiques journalières NASA POWER (pluie, température) par point.",
        "origin": ["pratisig/floodingsn"],
        "endpoints": ["POST /api/climate/timeseries"],
        "requires": ["réseau"],
        "status": "actif",
    },
    {
        "id": "exports",
        "label": "Exports",
        "icon": "download",
        "group": "Services",
        "summary": (
            "Export unifié de toute couche : GeoJSON, CSV, GeoPackage, Shapefile (ZIP), "
            "GeoParquet — au lieu d'un exporteur réécrit par projet."
        ),
        "origin": ["pratisig/Openbuildings", "pratisig/Carto-facileSN"],
        "endpoints": ["GET /api/exports/formats", "POST /api/exports/create"],
        "requires": [],
        "status": "actif",
    },
    {
        "id": "agent",
        "label": "Agent cartographique",
        "icon": "bot",
        "group": "Services",
        "summary": (
            "Assistant en langage naturel qui pilote les modules de la plateforme "
            "(géocoder, requêter, analyser, styler) via appel d'outils."
        ),
        "origin": ["pratisig/openmapagents"],
        "endpoints": ["GET /api/agent/tools", "POST /api/agent/chat"],
        "requires": ["clé API LLM"],
        "status": "optionnel",
    },
]

# Traçabilité : ce que chaque dépôt d'origine est devenu dans la plateforme.
MIGRATION_MAP: list[dict[str, Any]] = [
    {
        "repo": "pratisig/Openbuildings",
        "type": "personnel",
        "role_origine": "App Streamlit de téléchargement Open Buildings par pays (GeoParquet VIDA).",
        "destination": "modules/buildings.py + modules/exports.py",
        "note": "Le code de création Shapefile/GPKG devient le service d'export commun.",
    },
    {
        "repo": "pratisig/openbuildings_app",
        "type": "personnel",
        "role_origine": "Première version Streamlit Open Buildings (sélection WKT, tuiles S2 v3).",
        "destination": "modules/buildings.py (mode WKT/GeoJSON)",
        "note": "Doublon de Openbuildings — fusionné, la sélection par polygone est conservée.",
    },
    {
        "repo": "pratisig/floodingsn",
        "type": "personnel",
        "role_origine": "FloodWatch WA : sélection de zone + climat NASA POWER + placeholder GEE.",
        "destination": "modules/flood.py + modules/climate.py + modules/admin.py",
        "note": "Le mode démo est remplacé par une dégradation explicite quand GEE est absent.",
    },
    {
        "repo": "pratisig/innondationSN",
        "type": "personnel",
        "role_origine": "FloodWatch WA v2 : masque SAR Sentinel-1, WorldPop, impact OSM.",
        "destination": "modules/flood.py",
        "note": "Doublon fonctionnel de floodingsn — c'est cette logique SAR qui est retenue.",
    },
    {
        "repo": "pratisig/Carto-facileSN",
        "type": "personnel",
        "role_origine": "Plateforme Flask + React de cartographie du Sénégal (557 communes).",
        "destination": "modules/admin.py (Sénégal) + modules/exports.py + front unifié",
        "note": "L'API Flask est portée en routeur FastAPI ; le front React est fusionné.",
    },
    {
        "repo": "pratisig/routine",
        "type": "personnel",
        "role_origine": "Dépôt vide.",
        "destination": "—",
        "note": "Aucun code à récupérer.",
    },
    {
        "repo": "pratisig/openmapagents",
        "type": "fork (diouck/openmapagents)",
        "role_origine": "Explorateur Overture + agent LiteLLM + DuckDB + GEE + DB externe.",
        "destination": "modules/overture.py, agent.py, raster.py, spatial.py, core/duckdb_engine.py",
        "note": "Fork servant de référence d'architecture : c'est son modèle qui structure la plateforme.",
    },
    {
        "repo": "pratisig/city-roads",
        "type": "fork (anvaka/city-roads)",
        "role_origine": "Rendu WebGL de toutes les routes d'une ville via Overpass.",
        "destination": "modules/osm.py (requêtes Overpass) + front (rendu réseau)",
        "note": "Les gabarits de requêtes Overpass sont réutilisés côté serveur avec cache.",
    },
    {
        "repo": "pratisig/GeoRouteX",
        "type": "fork (Suman-hulk/GeoRouteX)",
        "role_origine": "Plugin QGIS de routage Dijkstra sur couches réseau.",
        "destination": "modules/routing.py",
        "note": "Le routage devient un service web ; le plugin QGIS reste un client possible.",
    },
    {
        "repo": "pratisig/GIS-Web-Development",
        "type": "fork (Omariu/GIS-Web-Development)",
        "role_origine": "Exemples pédagogiques ArcGIS JS API (rendus, widgets, requêtes).",
        "destination": "docs/ (référence de patrons UI)",
        "note": "Pas de code intégré : sert de catalogue de patrons cartographiques.",
    },
    {
        "repo": "pratisig/Zone",
        "type": "inaccessible",
        "role_origine": "Inconnu — dépôt privé ou supprimé au moment de la migration.",
        "destination": "—",
        "note": "À rattacher au module `admin` (sélection de zone) une fois accessible.",
    },
    {
        "repo": "pratisig/AGRISIGHT",
        "type": "inaccessible",
        "role_origine": "Inconnu — supposé suivi agricole par télédétection.",
        "destination": "—",
        "note": "Emplacement réservé dans le module `raster` (indices de végétation).",
    },
    {
        "repo": "pratisig/AgriSight_v2",
        "type": "inaccessible",
        "role_origine": "Inconnu — v2 du précédent.",
        "destination": "—",
        "note": "Emplacement réservé dans le module `raster`.",
    },
    {
        "repo": "pratisig/terracheck-senegal",
        "type": "inaccessible",
        "role_origine": "Inconnu — supposé vérification foncière au Sénégal.",
        "destination": "—",
        "note": "À rattacher aux modules `admin` + `buildings`.",
    },
    {
        "repo": "pratisig/sante-isochrones-app",
        "type": "inaccessible",
        "role_origine": "Inconnu — supposé accessibilité aux structures de santé.",
        "destination": "—",
        "note": "Le cas d'usage est déjà couvert par /api/routing/accessibility.",
    },
]


@router.get("", summary="Catalogue des modules de la plateforme")
def get_catalog() -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for module in MODULES:
        groups.setdefault(module["group"], []).append(module)
    return {
        "modules": MODULES,
        "groups": [{"name": name, "modules": items} for name, items in groups.items()],
        "count": len(MODULES),
    }


@router.get("/modules/{module_id}", summary="Détail d'un module")
def get_module(module_id: str) -> dict[str, Any]:
    for module in MODULES:
        if module["id"] == module_id:
            return module
    return {"error": "module inconnu", "available": [m["id"] for m in MODULES]}


@router.get("/migration", summary="Traçabilité des dépôts d'origine")
def get_migration() -> dict[str, Any]:
    return {
        "sources": MIGRATION_MAP,
        "count": len(MIGRATION_MAP),
        "personnels": sum(1 for m in MIGRATION_MAP if m["type"] == "personnel"),
        "forks": sum(1 for m in MIGRATION_MAP if m["type"].startswith("fork")),
        "inaccessibles": sum(1 for m in MIGRATION_MAP if m["type"] == "inaccessible"),
    }
