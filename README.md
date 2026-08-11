# PratiSIG Platform

> Plateforme géospatiale unifiée pour le Sénégal et l'Afrique de l'Ouest.
> Un dépôt, une API, une interface — à la place de quinze projets dispersés.

[![API](https://img.shields.io/badge/API-FastAPI-009688)](apps/api)
[![Front](https://img.shields.io/badge/Interface-React%20%2B%20MapLibre-61dafb)](apps/web)
[![Tests](https://img.shields.io/badge/tests-227%20passants-14b8a6)](apps/api/tests)
[![Validé](https://img.shields.io/badge/valid%C3%A9-20%2F20%20modules-0d9488)](#validation-en-conditions-réelles)
[![Licence](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)

---

## Sommaire

- [Pourquoi cette plateforme](#pourquoi-cette-plateforme)
- [Démarrage rapide](#démarrage-rapide)
- [Fonctionnalités](#fonctionnalités)
  - [Données](#données) · [Analyse](#analyse) · [Thématiques](#thématiques) · [Services](#services)
- [Interface](#interface)
- [Configuration](#configuration)
- [Déploiement](#déploiement)
- [Référence API](#référence-api)
- [Architecture](#architecture)
- [Développement](#développement)
- [Origine des projets](#origine-des-projets)

---

## Pourquoi cette plateforme

Quinze dépôts coexistaient, avec les problèmes classiques de l'éparpillement :

| Problème | Exemple constaté | Réponse |
|---|---|---|
| **Projets dupliqués** | 3 paires faisaient la même chose : `Openbuildings`/`openbuildings_app`, `floodingsn`/`innondationSN`, `AGRISIGHT`/`AgriSight_v2` | Un module unique par domaine |
| **Appels API épars** | Nominatim appelé depuis 3 projets, chacun avec son timeout | Un client HTTP partagé, avec cache |
| **Code recopié** | DuckDB initialisé à l'identique dans 2 fichiers ; 3 initialisations Earth Engine différentes | Un moteur, un service |
| **Sites éparpillés** | Streamlit Cloud ×4, Render, Vercel, PythonAnywhere | Un `docker compose up` |
| **Objectif oublié** | « Je ne me rappelle plus à quoi sert ce dépôt » | Onglet **Guide** et `/api/catalog/migration` |
| **Secrets exposés** | Compte de service GEE en clair dans le code | Variables d'environnement ou onglet **Comptes** |

---

## Démarrage rapide

**Prérequis** : Python 3.10+ et Node.js 18+.

### Windows

```powershell
git clone https://github.com/pratisig/Openbuildings.git pratisig-platform
cd pratisig-platform
.\scripts\dev.ps1
```

### macOS / Linux

```bash
git clone https://github.com/pratisig/Openbuildings.git pratisig-platform
cd pratisig-platform
./scripts/dev.sh
```

Le script installe les dépendances au premier lancement, puis démarre les deux
services.

- **Interface** : <http://localhost:5173>
- **API et documentation interactive** : <http://localhost:8000/docs>

### Vérifier que tout fonctionne

```bash
python scripts/smoke_test.py
```

Le script teste les 20 modules et distingue trois verdicts : **OK**,
**INACTIF** (configuration manquante, normal) et **ERREUR**.

### Avec Docker

```bash
cp .env.example .env      # optionnel
docker compose up -d
```

Tout est servi sur <http://localhost:8080>, API comprise.

---

## Fonctionnalités

15 modules, tous accessibles par API et par l'interface.

### Données

#### Bâtiments — Open Buildings

Empreintes Google + Microsoft : 2,5 milliards de bâtiments sur 185 pays
(Afrique, Asie du Sud, Amérique latine).

- Extraction par pays, avec restriction à une zone (bbox, rayon ou polygone)
- Filtres : confiance minimale, surface minimale
- Statistiques sans téléchargement des géométries (total, surfaces, densité)
- Requêtes DuckDB avec élagage : seuls les fragments utiles sont transférés

#### Overture Maps

Six thèmes interrogés en SQL sur S3 : `places`, `buildings`, `transportation`,
`divisions`, `base`, `addresses`.

- Filtres par catégorie, nom, hauteur, pays, confiance
- Agrégations par attribut (`group_by`)
- Version résolue automatiquement — Overture supprime ses versions après 60 jours

#### OpenStreetMap

Dix gabarits prêts à l'emploi : `roads_all`, `roads_main`, `roads_strict`,
`buildings`, `waterways`, `water_bodies`, `health`, `education`, `markets`,
`landuse`. Filtre Overpass personnalisé également accepté.

- Mode réseau routier : longueurs par tronçon et cumuls par classe
- Bascule automatique entre 4 miroirs Overpass

#### Découpage administratif

- Limites GADM 4.1 pour tous les pays, niveaux 0 à 5
- Sénégal : 14 régions, 46 départements, 133 arrondissements, 557 communes
- Résolution d'un code administratif en zone réutilisable par les autres modules

### Analyse

#### Analyse spatiale

Dix opérations exécutées côté serveur : `buffer`, `centroid`, `convex_hull`,
`dissolve`, `clip`, `intersection`, `difference`, `points_in_polygon`,
`nearest`, `stats`.

#### Itinéraires et accessibilité

- Itinéraires à pied, à vélo ou en voiture, avec instructions détaillées
- **Isochrones** par interpolation radiale du front sur la matrice de temps
  réelle, contour en alpha-shape (concave, épouse le réseau)
- **Accessibilité** : pour chaque origine, l'équipement le plus proche, son
  temps de trajet et un taux de couverture global

#### Géocodage

Recherche de lieux et géocodage inverse, avec cache partagé.

### Thématiques

#### Imagerie satellite *(nécessite Earth Engine)*

Dix jeux de données : `sentinel2`, `sentinel1`, `landsat8`, `landsat9`,
`modis_ndvi`, `modis_lst`, `worldcover`, `srtm`, `era5`, `worldpop`.

- Indices calculés à la volée : NDVI, NDWI, NDBI, EVI, LST, VV/VH
- Tuiles XYZ affichables sur la carte
- Séries temporelles d'un indice sur une zone

#### Inondations *(nécessite Earth Engine)*

Détection par comparaison radar Sentinel-1 entre période de crue et référence.

- Masque de pente (SRTM) écartant les faux positifs en relief
- Exclusion des eaux permanentes (JRC)
- Population exposée (WorldPop) et infrastructures impactées

#### Agriculture

Dix cultures : mil, sorgho, maïs, riz, arachide, niébé, manioc, tomate,
oignon, coton.

- Degrés-jours cumulés et stade phénologique
- Bilan hydrique FAO-56 : ETc, déficit, besoin d'irrigation
- Indices de stress thermique, hydrique et de froid
- Rendement potentiel estimé
- Classement des cultures adaptées à un lieu (climat réel + type de sol)

#### Analyse foncière

Évaluation d'une parcelle sur six critères pondérés : inondation (30 %),
topographie (15 %), occupation du sol (15 %), accès routier (15 %), services
de proximité (15 %), distance à la ville (10 %).

- **Redistribution des poids** : une source indisponible ne pénalise pas la
  parcelle, son poids est réparti sur les autres
- **Seuil de fiabilité** : en dessous de 50 % de couverture, le score est
  étiqueté « non concluant » plutôt que présenté comme un verdict
- Comparaison de 2 à 8 parcelles

#### Climat

Séries journalières NASA POWER : précipitations, températures, humidité, vent,
rayonnement. Pour la pluie : cumul, jours de pluie, jours de pluie forte.

### Services

#### Convertisseur de données et BBox

Import de fichiers `geojson`, `geojsonl`, `csv`/TSV, `kml`, `gpx` et `wkt`,
plus `gpkg`, `shapefile` (ZIP) et `geoparquet` lorsque GeoPandas est installé.
Les données sont normalisées en GeoJSON WGS 84, prévisualisées sur la carte et
réutilisables par tous les modules.

Le générateur de BBox permet de dessiner une emprise rectangulaire ou de saisir
ses quatre bornes. Il fournit les représentations BBox, tableau JSON, Overpass
et WKT, avec copie, affichage comme couche et téléchargement.

#### Exports

Huit formats : `geojson`, `geojsonl`, `csv` (géométrie WKT), `wkt`, `kml`,
`gpkg`, `shapefile` (ZIP), `geoparquet`. N'importe quelle couche affichée est
exportable.

#### Assistant cartographique *(nécessite une clé LLM)*

Dialogue en français pour piloter la carte : « montre les pharmacies autour du
centre de Dakar », « calcule un itinéraire vers Thiès ». L'assistant appelle
les modules de la plateforme et renvoie des couches directement affichables.

#### Comptes & clés

Configuration des services externes depuis l'interface, sans éditer de fichier
ni redémarrer. Voir [Configuration](#configuration).

---

## Interface

```
┌──────────────────────────────────────────────────────────────┐
│ PratiSIG   [recherche]        [fond] [thème] [● Opérationnel]│
├────┬─────────────────────────────────────────────────────────┤
│    │                                                          │
│ C  │  Panneau           │         Carte plein écran           │
│ a  │  contextuel        │                                     │
│ r  │                    │   [Point] [Zone]  ← outils          │
│ t  │                    │                                     │
│ e  │                    │                                     │
│    │                    │                    ┌──────────────┐ │
│ É  │                    │                    │ Inspecteur   │ │
│ t  │                    │                    └──────────────┘ │
│ c. │                    │                                     │
└────┴─────────────────────────────────────────────────────────┘
```

**Navigation groupée par intention** :

| Groupe | Onglets |
|---|---|
| Carte | Données, Couches |
| Étudier | Analyse, Satellite, Agriculture, Foncier |
| Outils | Convertir, Assistant |
| *(bas du rail)* | Comptes, Guide |

**Outils de carte** — en haut à gauche :

- **Point** : cliquez pour désigner un lieu (Foncier, Agriculture, Climat)
- **Zone** : maintenez et faites glisser pour délimiter une emprise
  (Données, Satellite). `Échap` pour annuler.

Sans sélection, les modules utilisent le centre ou l'emprise visible.

**Gestionnaire de couches** : chaque couche chargée — quelle que soit sa
source — est stylable (couleur, opacité), zoomable et exportable.

**Thèmes** : sombre par défaut, bascule clair dans l'en-tête.

**Bannière d'état** : rouge si l'API ne répond pas, avec la commande à lancer ;
jaune si des modules optionnels sont inactifs.

---

## Configuration

### Par l'interface (recommandé en local)

Onglet **Comptes** (icône clé, en bas du rail). Chaque service expose sa
procédure d'inscription, ses liens officiels, ses champs et un bouton de test.
Prise en compte immédiate.

| Service | Débloque | Coût |
|---|---|---|
| Google Earth Engine | Imagerie satellite, inondations | Gratuit (recherche, non commercial) |
| Fournisseur LLM | Assistant cartographique | Facturé à l'usage |
| Mapbox | Fonds de carte supplémentaires | Facultatif |

Deux garanties, vérifiées par tests :

- **Aucun secret ne revient en clair** — l'interface n'affiche qu'un masque
  (`sk-p…cdef`)
- **Rien n'est écrit sur disque** sauf si vous cochez « Conserver après
  redémarrage ». Le fichier `data/credentials.json` est exclu du dépôt Git.

### Par variables d'environnement (recommandé en production)

Toutes les variables portent le préfixe `PRATISIG_`. Copiez `.env.example`
en `.env`.

#### Application

| Variable | Défaut | Rôle |
|---|---|---|
| `PRATISIG_ENVIRONMENT` | `development` | Environnement déclaré |
| `PRATISIG_DEBUG` | `true` | Journalisation détaillée |
| `PRATISIG_CORS_ORIGINS` | `["http://localhost:5173", …]` | Origines autorisées |
| `PRATISIG_CORS_ORIGIN_REGEX` | — | Ex. `https://.*\.vercel\.app` |

#### Stockage et cache

| Variable | Défaut | Rôle |
|---|---|---|
| `PRATISIG_DATA_DIR` | `./data` | Données de référence |
| `PRATISIG_CACHE_DIR` | `./data/cache` | Cache disque |
| `PRATISIG_CACHE_ENABLED` | `true` | Activer le cache |
| `PRATISIG_CACHE_TTL_SECONDS` | `86400` | Durée de vie (24 h) |

#### Moteur DuckDB

| Variable | Défaut | Rôle |
|---|---|---|
| `PRATISIG_DUCKDB_MEMORY_LIMIT` | `4GB` | **Mettre `300MB` sur un plan gratuit 512 Mo** |
| `PRATISIG_DUCKDB_THREADS` | `4` | Threads de calcul |

#### Overture Maps

| Variable | Défaut | Rôle |
|---|---|---|
| `PRATISIG_OVERTURE_RELEASE_PINNED` | — | Figer une version (désactive la résolution auto) |
| `PRATISIG_OVERTURE_RELEASE_FALLBACK` | `2026-07-22.0` | Repli si le catalogue est injoignable |
| `PRATISIG_OVERTURE_USE_S3` | `true` | S3 anonyme (seul mode résolvant les jokers) |

#### Services externes

| Variable | Défaut |
|---|---|
| `PRATISIG_NOMINATIM_URL` | `https://nominatim.openstreetmap.org` |
| `PRATISIG_OVERPASS_MIRRORS` | 4 miroirs, essayés dans l'ordre |
| `PRATISIG_OSRM_URL` | `https://router.project-osrm.org` |
| `PRATISIG_GADM_BASE_URL` | `https://geodata.ucdavis.edu/gadm/gadm4.1/json` |
| `PRATISIG_HTTP_TIMEOUT` | `30.0` |

#### Earth Engine *(optionnel)*

| Variable | Rôle |
|---|---|
| `PRATISIG_GEE_SERVICE_ACCOUNT_EMAIL` | Adresse du compte de service |
| `PRATISIG_GEE_SERVICE_ACCOUNT_KEY_JSON` | Contenu JSON de la clé |
| `PRATISIG_GEE_SERVICE_ACCOUNT_KEY_FILE` | Ou chemin du fichier |

#### Assistant *(optionnel)*

| Variable | Défaut |
|---|---|
| `PRATISIG_LLM_ENABLED` | `false` |
| `PRATISIG_LLM_PROVIDER` | `openai` |
| `PRATISIG_LLM_MODEL` | `gpt-4o-mini` |
| `PRATISIG_LLM_API_KEY` | — |

### Dépendances optionnelles

Le socle (`requirements.txt`) reste léger. Pour tout activer :

```bash
pip install -r apps/api/requirements-full.txt
```

| Extra | Active |
|---|---|
| `geopandas`, `pyogrio`, `pyarrow` | Exports GeoPackage, Shapefile, GeoParquet |
| `earthengine-api`, `google-auth` | Imagerie satellite et inondations |
| `litellm` | Assistant cartographique |

### Dégradation maîtrisée

La plateforme **démarre toujours**, même sans aucune dépendance optionnelle.
Les modules concernés renvoient un `503` indiquant quoi configurer, et
`/health` liste précisément ce qui est actif :

```json
{
  "status": "degraded",
  "services": {
    "duckdb":      { "status": "ok",          "powers": ["buildings", "overture"] },
    "earthengine": { "status": "unavailable", "detail": "earthengine-api non installé" }
  },
  "degraded": ["earthengine", "llm"]
}
```

Les rares replis sont **signalés dans la réponse** (`approximate: true`).
Aucune donnée n'est jamais inventée.

---

## Déploiement

**API sur Render, interface sur Vercel** — les deux en plan gratuit.

Guide complet : [`docs/DEPLOIEMENT.md`](docs/DEPLOIEMENT.md).

| Plateforme | Verdict |
|---|---|
| **Render** | ✅ pour l'API — vrai conteneur, disque persistant |
| **Vercel** | ✅ pour l'interface — ❌ pour l'API |
| **Streamlit Cloud** | ❌ la plateforme n'est plus une app Streamlit |

**Pourquoi pas Vercel pour l'API** : fonctions éphémères (DuckDB rebâti à
chaque appel), limite de 10 s, pas de disque persistant, blocage d'IP sortante.

### API sur Render

1. **New → Blueprint**, sélectionnez le dépôt — `render.yaml` est détecté
2. Attendez la construction Docker (5 à 10 min)
3. Vérifiez `https://<votre-api>/health`

Sur le plan gratuit : 512 Mo de RAM et mise en veille après 15 min. Le
`render.yaml` plafonne déjà DuckDB à 300 Mo.

### Interface sur Vercel

1. **Add New → Project**, importez le dépôt
2. **Root Directory : `apps/web`** ← indispensable (monorepo)
3. Variable : `VITE_API_URL = https://<votre-api>.onrender.com`

Puis, côté Render : `PRATISIG_CORS_ORIGINS = ["https://<votre-front>.vercel.app"]`.

---

## Référence API

**57 chemins, 58 opérations.** Documentation interactive sur `/docs`,
schéma sur `/openapi.json`. Référence détaillée : [`docs/API.md`](docs/API.md).

### La zone d'étude

Tous les endpoints spatiaux acceptent le même objet `area`, sous quatre formes :

```jsonc
{ "bbox": [-17.55, 14.63, -17.33, 14.82] }              // emprise
{ "center": [-17.44, 14.69], "radius_m": 2000 }         // centre + rayon
{ "geojson": { "type": "Polygon", "coordinates": [] } } // polygone exact
{ "admin_code": "SEN.1.2_1" }                           // entité administrative
```

C'est ce qui rend les modules composables : la zone renvoyée par `admin`
alimente directement `buildings`, `flood` ou `raster`.

### Endpoints par module

<details>
<summary><b>Système</b> (5)</summary>

| Méthode | Endpoint |
|---|---|
| `GET` | `/` — présentation |
| `GET` | `/health` — état des services |
| `GET` | `/api/catalog` — catalogue des modules |
| `GET` | `/api/catalog/migration` — traçabilité des dépôts |
| `POST` | `/api/cache/clear` |
</details>

<details>
<summary><b>Bâtiments</b> (4)</summary>

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/buildings/countries` |
| `GET` | `/api/buildings/countries/{iso3}` |
| `POST` | `/api/buildings/query` |
| `POST` | `/api/buildings/stats` |

```jsonc
{
  "country_iso3": "SEN",
  "area": { "center": [-17.44, 14.69], "radius_m": 1500 },
  "min_confidence": 0.75,
  "limit": 5000
}
```
</details>

<details>
<summary><b>Overture, OSM, Administratif</b> (11)</summary>

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/overture/themes` |
| `POST` | `/api/overture/query` · `/api/overture/stats` |
| `GET` | `/api/osm/presets` |
| `POST` | `/api/osm/query` · `/api/osm/roads` |
| `GET` | `/api/admin/countries` |
| `GET` | `/api/admin/gadm/{iso3}/{level}` |
| `GET` | `/api/admin/senegal` · `/api/admin/senegal/{niveau}` |
| `GET` | `/api/admin/resolve?code=SEN.1.2_1` |
</details>

<details>
<summary><b>Analyse, routage, géocodage</b> (8)</summary>

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/spatial/operations` |
| `POST` | `/api/spatial/run` |
| `GET` | `/api/routing/profiles` |
| `POST` | `/api/routing/route` · `/api/routing/isochrone` · `/api/routing/accessibility` |
| `GET` | `/api/geocoding/search` · `/api/geocoding/reverse` |
</details>

<details>
<summary><b>Thématiques</b> (13)</summary>

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/raster/status` · `/api/raster/datasets` |
| `POST` | `/api/raster/tiles` · `/api/raster/timeseries` |
| `GET` | `/api/flood/status` |
| `POST` | `/api/flood/analyze` · `/api/flood/exposure` |
| `GET` | `/api/climate/parameters` |
| `POST` | `/api/climate/timeseries` |
| `GET` | `/api/agriculture/crops` · `/api/agriculture/zones` |
| `POST` | `/api/agriculture/season` · `/api/agriculture/suitability` |
| `GET` | `/api/land/criteria` · `/api/land/references` |
| `POST` | `/api/land/analyze` · `/api/land/compare` |
</details>

<details>
<summary><b>Conversion, exports, assistant, identifiants</b> (11)</summary>

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/converter/formats` |
| `POST` | `/api/converter/import` — envoi multipart d’un fichier |
| `GET` | `/api/exports/formats` |
| `POST` | `/api/exports/create` |
| `GET` | `/api/agent/tools` |
| `POST` | `/api/agent/chat` |
| `GET` | `/api/credentials` |
| `POST` | `/api/credentials/{provider}` · `/api/credentials/{provider}/test` |
| `DELETE` | `/api/credentials/{provider}` |
</details>

### Codes d'erreur

| Code | Signification |
|---|---|
| `400` | Requête invalide (zone trop vaste, paramètre manquant) |
| `404` | Ressource inconnue |
| `422` | Validation échouée, ou aucune donnée pour la période |
| `501` | Dépendance non installée |
| `502` / `504` | Service externe en erreur ou trop lent |
| `503` | Service non configuré — le message indique quoi renseigner |

### Exemple : enchaîner trois modules

```bash
# 1. Écoles et structures de santé depuis OSM
curl -X POST localhost:8000/api/osm/query -H 'Content-Type: application/json' \
  -d '{"preset":"education","area":{"bbox":[-17.55,14.63,-17.33,14.82]}}' > ecoles.json
curl -X POST localhost:8000/api/osm/query -H 'Content-Type: application/json' \
  -d '{"preset":"health","area":{"bbox":[-17.55,14.63,-17.33,14.82]}}' > sante.json

# 2. Quelles écoles sont à plus de 30 min d'un centre de santé ?
curl -X POST localhost:8000/api/routing/accessibility -H 'Content-Type: application/json' \
  -d '{"origins":[[-17.44,14.69]],"facilities":'"$(cat sante.json)"',"max_minutes":30}'

# 3. Exporter en GeoPackage
curl -X POST localhost:8000/api/exports/create -H 'Content-Type: application/json' \
  -d "{\"format\":\"gpkg\",\"data\":$(cat ecoles.json),\"filename\":\"ecoles\"}" -o ecoles.gpkg
```

---

## Architecture

```
pratisig-platform/
├── apps/
│   ├── api/                       # API FastAPI
│   │   ├── pratisig_api/
│   │   │   ├── config.py          # Configuration unique
│   │   │   ├── main.py            # Assemblage des routeurs
│   │   │   ├── core/              # Socle partagé
│   │   │   │   ├── cache.py       #   remplace 3 caches dupliqués
│   │   │   │   ├── duckdb_engine.py #  remplace 2 moteurs identiques
│   │   │   │   ├── geo.py         #   primitives sans dépendance lourde
│   │   │   │   ├── http.py        #   client unique + bascule de miroirs
│   │   │   │   ├── projection.py  #   UTM automatique
│   │   │   │   └── schemas.py     #   AreaOfInterest
│   │   │   ├── modules/           # Un routeur par domaine (15)
│   │   │   ├── services/          # GEE, résolution Overture
│   │   │   └── tests/             # 227 tests
│   └── web/                       # Interface React + MapLibre
│       └── src/
│           ├── lib/api.js         # Client API unique
│           ├── components/        # Carte, couches, icônes, bannière
│           ├── modules/           # Un panneau par groupe
│           └── styles/app.css     # Jetons de conception, 2 thèmes
├── data/reference/                # countries.geojson
├── docs/                          # Migration, API, architecture, sécurité
├── scripts/                       # dev.sh · dev.ps1 · smoke_test · diagnostics
├── legacy/                        # Applications d'origine, conservées
├── docker-compose.yml
└── render.yaml
```

Décisions techniques détaillées : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Développement

### Tests et qualité

```bash
./scripts/dev.sh check        # tests + lint + build   (Windows : .\scripts\dev.ps1 check)
```

227 tests couvrent le socle géométrique, la validation des entrées, les
opérations spatiales, la conversion de fichiers, les exports, la dégradation des
services, les calculs agronomiques, le scoring foncier, la géométrie des isochrones, la sécurité des
identifiants et la cohérence de l'interface.

### Diagnostics

| Script | Usage |
|---|---|
| `scripts/smoke_test.py` | Vérifie les 20 modules de bout en bout |
| `scripts/diagnose_duckdb.py` | Inspecte les schémas Overture et Open Buildings |
| `scripts/security-check.ps1` | Collecte d'indices de compromission (Windows, lecture seule) |
| `.\scripts\dev.ps1 doctor` | Vérifie Python, Node, variables d'environnement |

### Ajouter un module

1. Créer `apps/api/pratisig_api/modules/mon_module.py` avec un `APIRouter`
2. Utiliser `AreaOfInterest` pour toute entrée spatiale
3. Utiliser `core.cache` et `core.http` plutôt que `requests`
4. L'enregistrer dans `main.py` et le déclarer dans `modules/catalog.py`
5. Ajouter des tests

Le front le découvre via `/api/catalog` : aucune modification nécessaire pour
qu'il apparaisse dans le Guide.

### Validation en conditions réelles

Campagne du 30/07/2026, poste Windows, connexion sénégalaise :
**20 modules fonctionnels, 0 erreur**. Tous les services externes ont répondu.

Quatre défauts n'étaient visibles que dans ces conditions :

| Défaut | Cause | Correction |
|---|---|---|
| Overpass `504` | Point unique de défaillance | 4 miroirs en cascade |
| Open Buildings `Binder Error` | La clé primaire est `boundary_id`, pas `id` | Requête corrigée |
| Overture `No files found` | Versions supprimées après 60 jours | Résolution dynamique |
| Overture `timed out` | Filtre bbox sans borne inférieure | Encadrement bilatéral |

Temps de réponse observés : géocodage et climat < 3 s, Overpass 3-12 s,
Open Buildings ~20 s, Overture 60-90 s au premier appel (puis cache).

---

## Origine des projets

**Fusionnés** : `Openbuildings`, `openbuildings_app`, `floodingsn`,
`innondationSN`, `Carto-facileSN`, `AGRISIGHT`, `AgriSight_v2`,
`terracheck-senegal`, `sante-isochrones-app`

**Références intégrées** (forks) : `openmapagents` (architecture),
`city-roads` (requêtes Overpass), `GeoRouteX` (routage),
`GIS-Web-Development` (patrons cartographiques)

**Sans code** : `routine` (vide) · **Inaccessible** : `Zone`

Détail dépôt par dépôt — rôle d'origine, destination, bugs corrigés :
[`docs/MIGRATION.md`](docs/MIGRATION.md). Également disponible en direct sur
`/api/catalog/migration` et dans l'onglet **Guide**.

---

## Documentation

| Document | Contenu |
|---|---|
| [`docs/DEPLOIEMENT.md`](docs/DEPLOIEMENT.md) | Installation, dépannage, Render, Vercel |
| [`docs/API.md`](docs/API.md) | Référence complète des endpoints |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Décisions techniques et justifications |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | Traçabilité des 15 dépôts d'origine |
| [`docs/SECURITE.md`](docs/SECURITE.md) | Garanties, incident documenté, bonnes pratiques |

---

## Licence

MIT — voir [LICENSE](LICENSE).

**Données** : OpenStreetMap (ODbL) · Overture Maps (ODbL/CDLA) ·
Open Buildings (CC BY-4.0) · GADM (usage non commercial) ·
NASA POWER (domaine public) · Copernicus Sentinel (ESA)
