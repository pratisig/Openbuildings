# PratiSIG Platform

> Plateforme géospatiale unifiée pour le Sénégal et l'Afrique de l'Ouest.
> Un seul dépôt, une seule API, une seule interface — à la place de quinze projets dispersés.

[![API](https://img.shields.io/badge/API-FastAPI-009688)](apps/api)
[![Front](https://img.shields.io/badge/Front-React%20%2B%20MapLibre-61dafb)](apps/web)
[![Tests](https://img.shields.io/badge/tests-84%20passants-2a9d8f)](apps/api/tests)
[![Licence](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)

---

## Pourquoi cette plateforme

Quinze dépôts coexistaient, avec les problèmes classiques de l'éparpillement :

| Problème constaté | Exemple concret | Réponse apportée |
|---|---|---|
| **Projets dupliqués** | `Openbuildings` et `openbuildings_app` téléchargent les mêmes données ; `floodingsn` et `innondationSN` sont deux versions de « FloodWatch WA » | Fusionnés en un module unique par domaine |
| **Appels API épars** | Nominatim appelé depuis 3 projets, chacun avec son timeout et sans User-Agent conforme | Un client HTTP partagé, avec cache |
| **Code recopié** | DuckDB initialisé à l'identique dans `backend.py` et `agent.py` ; 3 initialisations GEE différentes | Un moteur DuckDB, un service GEE |
| **Sites éparpillés** | Streamlit Cloud ×4, Render, Vercel, PythonAnywhere | Un `docker compose up` |
| **Objectif oublié** | « Je ne me rappelle plus à quoi sert ce dépôt » | `/api/catalog/migration` documente chaque dépôt d'origine |
| **Secrets exposés** | Compte de service GEE en dur dans `gee_routes.py` | Tout par variables d'environnement |

---

## Démarrage

### Avec Docker (recommandé)

```bash
git clone https://github.com/pratisig/Openbuildings.git pratisig-platform
cd pratisig-platform
cp .env.example .env          # optionnel : tout fonctionne sans
docker compose up -d
```

Interface : <http://localhost:8080> · API : <http://localhost:8000/docs>

### En développement

```bash
# API
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # socle léger
# pip install -r requirements-full.txt   # + exports SIG, GEE, agent
uvicorn pratisig_api.main:app --reload

# Interface (autre terminal)
cd apps/web
npm install && npm run dev
```

---

## Ce que fait la plateforme

### Dégradation maîtrisée

La plateforme **démarre toujours**, même sans aucune dépendance optionnelle.
Les modules concernés renvoient un `503` explicite indiquant quoi configurer,
et `/health` liste précisément ce qui est actif :

```bash
curl localhost:8000/health
```

```json
{
  "status": "degraded",
  "services": {
    "duckdb":      { "status": "ok",          "powers": ["buildings", "overture"] },
    "earthengine": { "status": "unavailable", "detail": "earthengine-api non installé" },
    "geopandas":   { "status": "degraded",    "detail": "GeoJSON/CSV uniquement" }
  },
  "degraded": ["earthengine", "geopandas"]
}
```

C'est l'inverse du comportement d'origine : `floodingsn` affichait des chiffres
**inventés** quand Earth Engine était absent (`'population': 1500000` en dur).

### Modules

| Module | Rôle | Vient de |
|---|---|---|
| **buildings** | Empreintes Open Buildings (Google + Microsoft), 185 pays | `Openbuildings`, `openbuildings_app` |
| **overture** | POI, bâtiments, routes, divisions Overture via DuckDB/S3 | `openmapagents` |
| **osm** | Réseaux routiers, équipements, hydrographie via Overpass | `city-roads`, `innondationSN` |
| **admin** | Limites administratives GADM + 4 niveaux du Sénégal | `Carto-facileSN`, `floodingsn` |
| **geocoding** | Recherche de lieux et géocodage inverse | `openmapagents`, `city-roads` |
| **routing** | Itinéraires, isochrones, accessibilité aux équipements | `GeoRouteX`, `sante-isochrones-app` |
| **spatial** | Buffer, clip, dissolve, points-dans-polygone, statistiques | `openmapagents` |
| **raster** | Sentinel, Landsat, MODIS, indices NDVI/NDWI/LST | `openmapagents`, `AgriSight` |
| **flood** | Détection SAR d'inondations, population exposée | `floodingsn`, `innondationSN` |
| **climate** | Séries pluie/température NASA POWER | `floodingsn` |
| **exports** | GeoJSON, CSV, GeoPackage, Shapefile, GeoParquet | `Openbuildings`, `Carto-facileSN` |
| **agent** | Pilotage en langage naturel de tous les modules | `openmapagents` |

Catalogue vivant : `GET /api/catalog` · Traçabilité : `GET /api/catalog/migration`

---

## Architecture

```
pratisig-platform/
├── apps/
│   ├── api/                       # API FastAPI unifiée
│   │   ├── pratisig_api/
│   │   │   ├── config.py          # Configuration unique (variables d'env.)
│   │   │   ├── main.py            # Assemblage des routeurs
│   │   │   ├── core/              # Socle partagé
│   │   │   │   ├── cache.py       #   ← remplace 3 caches dupliqués
│   │   │   │   ├── duckdb_engine.py #  ← remplace 2 moteurs identiques
│   │   │   │   ├── geo.py         #   ← primitives sans dépendance lourde
│   │   │   │   ├── http.py        #   ← client HTTP unique
│   │   │   │   └── schemas.py     #   ← AreaOfInterest : zone unifiée
│   │   │   ├── modules/           # Un routeur par domaine métier
│   │   │   └── services/gee.py    # ← remplace 3 init. Earth Engine
│   │   └── tests/                 # 84 tests
│   └── web/                       # Interface React + MapLibre
│       └── src/
│           ├── lib/api.js         # ← remplace les URLs en dur éparpillées
│           ├── components/        # Carte, couches, à propos
│           └── modules/           # Un panneau par groupe de modules
├── data/reference/                # countries.geojson (hérité)
├── legacy/                        # Applications d'origine, conservées
├── docs/                          # Migration, API, décisions techniques
└── docker-compose.yml
```

### Le concept clé : `AreaOfInterest`

Chaque ancien projet définissait sa propre notion de « zone d'étude » : WKT
dans `openbuildings_app`, bbox dans `Openbuildings`, GADM dans `floodingsn`,
polygone dessiné dans `innondationSN`. Un seul schéma les remplace, accepté
par **tous** les modules :

```json
{ "bbox": [-17.5, 14.6, -17.4, 14.7] }
{ "center": [-17.44, 14.69], "radius_m": 2000 }
{ "geojson": { "type": "Polygon", "coordinates": [...] } }
{ "admin_code": "SEN.1.2_1" }
```

C'est ce qui rend les modules composables : la zone renvoyée par `admin`
alimente directement `buildings`, `flood` ou `raster`.

---

## Exemples

**Bâtiments d'un quartier de Dakar, exportés en GeoPackage**

```bash
curl -X POST localhost:8000/api/buildings/query \
  -H 'Content-Type: application/json' \
  -d '{"country_iso3":"SEN","area":{"center":[-17.44,14.69],"radius_m":1500},
       "min_confidence":0.75,"limit":5000}' > batiments.json

curl -X POST localhost:8000/api/exports/create \
  -H 'Content-Type: application/json' \
  -d "{\"format\":\"gpkg\",\"data\":$(cat batiments.json),\"filename\":\"dakar\"}" \
  -o dakar.gpkg
```

**Écoles à plus de 30 minutes d'un hôpital** — enchaînement de trois modules :

```bash
# 1. Écoles et hôpitaux depuis OSM
curl -X POST localhost:8000/api/osm/query -H 'Content-Type: application/json' \
  -d '{"preset":"education","area":{"bbox":[-17.55,14.63,-17.33,14.82]}}' > ecoles.json
curl -X POST localhost:8000/api/osm/query -H 'Content-Type: application/json' \
  -d '{"preset":"health","area":{"bbox":[-17.55,14.63,-17.33,14.82]}}' > sante.json

# 2. Accessibilité (le champ `reachable` distingue les écoles isolées)
curl -X POST localhost:8000/api/routing/accessibility -H 'Content-Type: application/json' \
  -d '{"origins":[[-17.44,14.69]],"facilities":'"$(cat sante.json)"',"max_minutes":30}'
```

**Surface inondée et population exposée**

```bash
curl -X POST localhost:8000/api/flood/analyze -H 'Content-Type: application/json' \
  -d '{"area":{"bbox":[-16.5,15.9,-16.2,16.1]},
       "flood_start":"2024-09-01","flood_end":"2024-10-15"}'
```

---

## Documentation

- [`docs/MIGRATION.md`](docs/MIGRATION.md) — ce qu'est devenu chaque dépôt, dépôt par dépôt
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — décisions techniques et leurs raisons
- [`docs/API.md`](docs/API.md) — référence des endpoints
- `/docs` (Swagger) et `/redoc` sur l'API en fonctionnement

---

## Tests

```bash
cd apps/api && python -m pytest tests/ -v
```

84 tests couvrent le socle géométrique, la validation des entrées, les
opérations spatiales, les exports et la dégradation des services.

---

## État des dépôts d'origine

**Fusionnés** : `Openbuildings`, `openbuildings_app`, `floodingsn`,
`innondationSN`, `Carto-facileSN`

**Références intégrées** (forks) : `openmapagents` (modèle d'architecture),
`city-roads` (requêtes Overpass), `GeoRouteX` (routage),
`GIS-Web-Development` (patrons cartographiques)

**Sans code** : `routine` (dépôt vide)

**Inaccessibles au moment de la migration** (privés ou supprimés) :
`Zone`, `AGRISIGHT`, `AgriSight_v2`, `terracheck-senegal`, `sante-isochrones-app`.
Des emplacements leur sont réservés — voir [`docs/MIGRATION.md`](docs/MIGRATION.md).

---

## Licence

MIT — voir [LICENSE](LICENSE).

Données : OpenStreetMap (ODbL) · Overture Maps (ODbL/CDLA) ·
Open Buildings (CC BY-4.0) · GADM (usage non commercial) · NASA POWER (domaine public)
