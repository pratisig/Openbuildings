# Architecture

Décisions techniques et raisons qui les motivent.

---

## Principe directeur

> Une donnée, un service, un point d'entrée.

Chaque fonctionnalité n'existe qu'à un seul endroit. Un module qui a besoin
d'une capacité l'appelle plutôt que de la réimplémenter — c'est précisément ce
qui manquait entre les quinze dépôts d'origine.

```
┌──────────────────────────────────────────────────────────┐
│  Interface React + MapLibre   ·   un seul client API     │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP (même domaine en prod.)
┌───────────────────────────▼──────────────────────────────┐
│                  API FastAPI unifiée                     │
│                                                          │
│   Données        Analyse         Thématiques   Services  │
│   buildings      spatial         flood         geocoding │
│   overture       routing         climate       exports   │
│   osm            raster                        agent     │
│   admin                                                  │
├──────────────────────────────────────────────────────────┤
│  Socle partagé (core/)                                   │
│  config · cache · duckdb_engine · http · geo · schemas   │
└───────────────────────────┬──────────────────────────────┘
                            │
   DuckDB/S3 · Overpass · Nominatim · OSRM · GADM
   NASA POWER · Earth Engine · fournisseur LLM
```

---

## Décisions et justifications

### 1. Une API unique, pas des microservices

**Décision** : un seul processus FastAPI avec un routeur par domaine.

**Pourquoi** : les microservices auraient signifié dix conteneurs à déployer,
surveiller et faire dialoguer — l'inverse de l'objectif. Un module reste un
fichier autonome (`modules/flood.py`) : la séparation logique est là, sans le
coût opérationnel. Si un module devient un goulot d'étranglement, son
extraction est mécanique puisqu'il ne dépend que de `core/`.

### 2. FastAPI plutôt que Flask ou Streamlit

**Pourquoi pas Streamlit** : quatre des dépôts en étaient. Streamlit réexécute
tout le script à chaque interaction, mélange interface et traitement, et
n'expose aucune API réutilisable. Impossible d'appeler `floodingsn` depuis un
script ou QGIS.

**Pourquoi pas Flask** (`Carto-facileSN`) : pas d'asynchrone (bloquant sur des
appels réseau lents comme Overpass), pas de validation intégrée, pas de
documentation générée.

**FastAPI** apporte : validation Pydantic (les entrées invalides sont rejetées
avant d'atteindre la logique métier), OpenAPI généré automatiquement,
asynchrone natif pour les appels réseau.

### 3. Un moteur DuckDB partagé

`openmapagents` instanciait la même connexion DuckDB dans `backend.py` et
`agent.py` — mêmes extensions, mêmes réglages, deux fois en mémoire.

`core/duckdb_engine.py` fournit une connexion unique, paresseuse (créée au
premier usage), protégée par verrou. Si l'extension `spatial` est absente, la
plateforme démarre quand même et `/health` le signale.

**Pourquoi DuckDB** : il lit le Parquet distant en poussant les filtres
jusqu'au stockage. Pour Open Buildings, cela transforme un téléchargement de
plusieurs gigaoctets en une requête de quelques mégaoctets.

### 4. `AreaOfInterest` : la zone d'étude unifiée

Le concept le plus structurant. Chaque projet avait sa manière de dire « où » :

| Projet | Représentation de la zone |
|---|---|
| `Openbuildings` | pays ISO3 + bbox optionnelle |
| `openbuildings_app` | polygone WKT |
| `floodingsn` | pays GADM, dessin Folium ou fichier |
| `innondationSN` | subdivision GADM |
| `openmapagents` | bbox ou centre + rayon |
| `Carto-facileSN` | identifiant de commune |

Un seul schéma les accepte toutes, et **tous** les modules le comprennent :

```python
class AreaOfInterest(BaseModel):
    bbox: list[float] | None        # [xmin, ymin, xmax, ymax]
    center: list[float] | None      # [lon, lat]
    radius_m: float | None
    geojson: dict | None            # Polygon, MultiPolygon…
    admin_code: str | None          # SEN.1.2_1
```

Conséquence directe : la zone renvoyée par `/api/admin/resolve` alimente sans
transformation `/api/buildings/query`, `/api/flood/analyze` ou
`/api/raster/tiles`. La composabilité vient de là.

### 5. Dégradation explicite plutôt que données factices

**Règle** : un service indisponible renvoie un `503` indiquant quoi
configurer. Jamais de valeur de repli silencieuse.

C'est la correction du défaut le plus grave trouvé dans `floodingsn`, qui
affichait `'population': 1500000` en dur quand Earth Engine manquait — un
utilisateur pouvait prendre une décision sur un chiffre inventé.

Les seuls replis autorisés sont **signalés dans la réponse** :

```json
{ "metadata": { "engine": "approximation géodésique", "approximate": true } }
```

### 6. Dépendances lourdes optionnelles

Le socle (`requirements.txt`) n'installe que FastAPI, httpx, DuckDB et Shapely.
GeoPandas, Earth Engine et LiteLLM sont des extras.

**Pourquoi** : GeoPandas tire GDAL, Fiona, pyproj — plusieurs centaines de
mégaoctets et une compilation fréquemment cassée. Les anciens `requirements.txt`
mélangeaient tout : celui de `Openbuildings` demandait `tensorflow`,
`s2geometry`, `cmake` et `g++` pour une application qui ne fait que lire un
Parquet.

La plateforme fonctionne sans eux ; les fonctions concernées se signalent
indisponibles.

### 7. Géométrie sans dépendance dans le socle

`core/geo.py` implémente en Python pur : bbox, conversions mètres/degrés,
haversine, point-dans-polygone, aire sphérique, centroïde surfacique, cercle
géodésique.

**Pourquoi** : ces primitives sont utilisées partout (validation, découpe,
statistiques). Les faire dépendre de Shapely rendrait l'API inutilisable sans
GEOS. Shapely est utilisé **quand il est là**, pour les opérations où la
précision compte (intersection, différence, dissolve).

### 8. OSRM plutôt que Mapbox

`openmapagents` utilisait l'API Mapbox pour les routes et isochrones : clé
payante obligatoire, donc fonction morte pour quiconque clone le dépôt.

OSRM public ne demande pas de clé. En cas d'indisponibilité, l'isochrone est
approximée par un cercle basé sur la vitesse moyenne du mode — avec
`approximate: true` dans la réponse.

### 9. Cache disque partagé

Un seul cache pour tous les modules, organisé par espace de noms
(`geocoding/`, `overture/`, `osm/`…), avec durée de vie configurable.

**Pourquoi c'est nécessaire** : Nominatim limite à 1 requête/seconde et
Overpass restreint le débit. Sans cache, la plateforme se ferait bloquer.
`Carto-facileSN` avait bien un cache, mais spécifique à ses shapefiles.

### 10. Sécurité

- **Aucun secret dans le code** — tout par variables d'environnement.
  `openmapagents` versionnait une adresse de compte de service et un chemin de
  clé privée ; `.gitignore` couvre désormais `.env`, `secrets/` et
  `*-service-account*.json`.
- **Entrées validées** — Pydantic contraint les bornes (latitude ∈ [-90, 90],
  limites de features, surface maximale des requêtes Overpass).
- **Littéraux SQL échappés** — les valeurs interpolées dans les requêtes
  DuckDB passent par `_escape()`, en plus de la validation d'énumération.
- **Noms de fichiers assainis** à l'export (protection contre la traversée de
  répertoires).

---

## Ajouter un module

1. Créer `apps/api/pratisig_api/modules/mon_module.py` avec un
   `router = APIRouter(prefix="/api/mon-module", tags=["mon-module"])`
2. Utiliser `AreaOfInterest` pour toute entrée spatiale
3. Utiliser `core.cache` et `core.http` plutôt que d'appeler `requests`
4. L'enregistrer dans `main.py` (boucle d'inclusion des routeurs)
5. Le déclarer dans `modules/catalog.py` — il apparaît automatiquement dans
   l'interface et la documentation
6. Ajouter des tests dans `apps/api/tests/`

Le front le découvre par `/api/catalog` : aucune modification n'est nécessaire
pour qu'il figure dans le panneau « À propos ».

---

## Choix de l'interface

**MapLibre GL** plutôt que Leaflet ou Mapbox GL : rendu WebGL (indispensable
pour afficher des dizaines de milliers d'empreintes de bâtiments), libre, sans
clé d'API. Mapbox GL est passé sous licence propriétaire à partir de la v2.

**React sans framework d'état** : l'état tient dans quelques `useState` dans
`App.jsx`. Redux ou Zustand seraient disproportionnés.

**Un client API unique** (`lib/api.js`) : avant, chaque front avait ses URLs en
dur (`carto-facilesn.onrender.com`, `openmapagents.geoafrica.fr`,
`localhost:8000`). Changer d'environnement se fait maintenant en une variable.

**En production, l'API est servie sous le même domaine** via le proxy nginx :
plus de CORS à configurer, plus d'URL externe à maintenir.
