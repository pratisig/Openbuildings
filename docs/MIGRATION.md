# Migration — ce qu'est devenu chaque dépôt

Ce document répond directement au besoin exprimé : *« même si j'ai oublié le
versionning voire même l'objectif de certains »*. Chaque dépôt d'origine est
documenté ici : ce qu'il faisait, ce qu'il est devenu, ce qui a été corrigé.

La même information est disponible en direct sur l'API :
`GET /api/catalog/migration`.

---

## Vue d'ensemble

| Dépôt | Type | Statut | Destination |
|---|---|---|---|
| `Openbuildings` | personnel | **fusionné** | `modules/buildings.py`, `modules/exports.py` |
| `openbuildings_app` | personnel | **fusionné** (doublon) | `modules/buildings.py` |
| `floodingsn` | personnel | **fusionné** | `modules/flood.py`, `modules/climate.py` |
| `innondationSN` | personnel | **fusionné** (doublon) | `modules/flood.py` |
| `Carto-facileSN` | personnel | **fusionné** | `modules/admin.py`, front unifié |
| `routine` | personnel | vide | — |
| `openmapagents` | fork | **référence d'architecture** | `modules/overture.py`, `agent.py`, `raster.py`, `core/` |
| `city-roads` | fork | **logique reprise** | `modules/osm.py` |
| `GeoRouteX` | fork | **logique reprise** | `modules/routing.py` |
| `GIS-Web-Development` | fork | **référence UI** | `docs/` |
| `AGRISIGHT` | personnel | **fusionné** | `modules/agriculture.py` |
| `AgriSight_v2` | personnel | **fusionné** (doublon) | `modules/agriculture.py` |
| `terracheck-senegal` | personnel | **fusionné** | `modules/land.py` |
| `sante-isochrones-app` | personnel | **fusionné** | `modules/routing.py`, `core/projection.py` |
| `Zone` | — | inaccessible | — |

---

## Dépôts personnels

### `Openbuildings` → `modules/buildings.py` + `modules/exports.py`

**Ce qu'il faisait** : application Streamlit téléchargeant les empreintes de
bâtiments Google + Microsoft (dataset VIDA) pour un pays entier au format
GeoParquet, avec export GeoJSON / Shapefile / GeoPackage / CSV.

**Problème principal** : `gpd.read_parquet(url)` téléchargeait **le fichier
complet du pays** (plusieurs gigaoctets pour le Nigeria) avant de filtrer sur
la bbox en mémoire. Sur un quartier de Dakar, cela signifiait rapatrier tout
le Sénégal.

**Ce qui change** : DuckDB interroge le GeoParquet distant avec un *predicate
pushdown* sur la colonne `bbox` — seuls les groupes de lignes pertinents sont
téléchargés. La découpe au polygone exact vient en plus du filtre rectangulaire.

```python
# Avant : tout le pays en mémoire, puis filtre
gdf = gpd.read_parquet(parquet_url)
gdf = gdf[gdf.intersects(bbox)]

# Après : filtre poussé jusqu'au stockage
SELECT id, confidence, area_in_meters, ST_AsGeoJSON(geometry) AS geom_json
FROM read_parquet('...SEN.parquet')
WHERE bbox.xmin <= ... AND bbox.xmax >= ...
```

La fonction `create_shapefile_zip()` (troncature des noms d'attributs à 10
caractères) est devenue le service d'export commun, utilisable par **toutes**
les couches de la plateforme, pas seulement les bâtiments.

Le fichier `countries.geojson` est conservé dans `data/reference/`.

---

### `openbuildings_app` → fusionné dans `modules/buildings.py`

**Ce qu'il faisait** : première version de l'app Open Buildings, avec
sélection par polygone WKT et carte pydeck.

**Pourquoi c'était un doublon** : même objectif que `Openbuildings`, mais sur
l'ancien schéma de tuiles S2 v3 (`gs://open-buildings-data/v3/...`).

**Problèmes du code d'origine** : variables `data_type` et `output_format`
utilisées sans jamais être définies (`NameError` garanti) ; module `shapely`
référencé sans import ; URL de téléchargement construite par interpolation de
coordonnées vers un point de terminaison qui n'existe pas sous cette forme ;
appels `wget`/`unzip` via `subprocess` (dépendances système implicites).

**Ce qui est conservé** : l'idée de sélectionner la zone par polygone
plutôt que par pays entier — devenue le champ `geojson` d'`AreaOfInterest`.

---

### `floodingsn` → `modules/flood.py` + `modules/climate.py` + `modules/admin.py`

**Ce qu'il faisait** : « FloodWatch WA », surveillance des inondations en
Afrique de l'Ouest. Interface Streamlit soignée (choix de zone GADM / dessin /
import, périodes de référence et de crue, graphiques).

**Problème majeur** : l'analyse était **factice**. Quand Earth Engine était
indisponible, l'application affichait des chiffres codés en dur sans
avertissement clair :

```python
st.session_state.results = {
    'population': 1500000, 'flooded_area': 1250.5,
    'buildings': 4500, 'roads': 120
}
```

Et lorsque GEE **était** disponible, le code retournait… d'autres chiffres en
dur, avec le commentaire `# Ici, ajouter le vrai code GEE`.

**Ce qui change** : la vraie logique SAR vient de `innondationSN` (ci-dessous).
Sans Earth Engine, l'API renvoie un `503` explicite plutôt que des données
inventées. La fonction `get_climate_data()` (NASA POWER) devient le module
`climate`, enrichi de statistiques dérivées (cumul, jours de pluie, jours de
pluie forte). Le chargement GADM devient le module `admin`.

---

### `innondationSN` → `modules/flood.py`

**Ce qu'il faisait** : seconde version de FloodWatch, avec cette fois une
véritable détection radar.

**Ce qui est retenu** — la méthode `get_flood_mask()`, techniquement solide :

1. Sentinel-1 GRD, mode IW, polarisation VV
2. Comparaison entre la période de crue et la même période l'année précédente
3. Filtrage du speckle par médiane focale de 30 m
4. Seuil sur la baisse de rétrodiffusion (l'eau libre réfléchit loin du capteur)
5. **Masque de pente** (SRTM < 5°) : l'eau ne stagne pas en relief
6. Ouverture morphologique : suppression des pixels isolés

**Ce qui est ajouté** : exclusion des eaux permanentes (JRC Global Surface
Water) — sans quoi les lacs et le fleuve Sénégal étaient comptés comme
inondations à chaque analyse.

**Autres corrections** : `osmnx` (dépendance lourde et lente) remplacé par des
appels Overpass directs ; `unary_union` déprécié remplacé ; le compte de
service GEE n'est plus lu depuis les secrets Streamlit mais depuis
l'environnement.

---

### `Carto-facileSN` → `modules/admin.py` + front unifié

**Ce qu'il faisait** : le projet le plus abouti de l'ensemble — plateforme
Flask + React de cartographie du Sénégal (557 communes), avec shapefiles IGN,
exports PNG/PDF, connecteur KoboCollect et paiement Wave.

**Ce qui est repris** :

- La hiérarchie administrative à 4 niveaux (régions → départements →
  arrondissements → communes) devient `/api/admin/senegal/{niveau}` ;
- Le principe de préchauffage du cache (`geo_cache.py`) est généralisé au
  cache disque partagé ;
- La détection tolérante des colonnes de noms (`NOM_CANDIDATS`, très utile
  face à des shapefiles hétérogènes) inspire la normalisation des propriétés
  GADM ;
- L'ergonomie du front React (panneaux latéraux, gestionnaire de couches,
  catalogue thématique) structure l'interface unifiée.

**Ce qui change** : les shapefiles IGN (21 Mo dans le dépôt) sont remplacés
par GADM 4.1 chargé à la demande et mis en cache — le dépôt reste léger et la
couverture s'étend à tous les pays. Les modèles SQLAlchemy et le paiement Wave
ne sont pas repris : ils relèvent d'un produit commercial distinct, à
rebrancher si besoin sur cette API.

> Note : le code Flask d'origine contenait un import circulaire
> (`routes/exports.py` faisait `from app import db` alors que `app.py`
> importe les routes). L'architecture par routeurs FastAPI évite ce piège.

---

### `routine`

Dépôt vide, aucun commit. Rien à migrer.

---

## Forks — références et logiques reprises

### `openmapagents` (fork de `diouck/openmapagents`)

**Le fork le plus important** : c'est son architecture qui structure la
plateforme. Explorateur Overture Maps avec agent LiteLLM multi-fournisseurs,
DuckDB, routes GEE, connecteur base de données externe, serveur MCP.

**Ce qui est repris** :

| Origine | Destination |
|---|---|
| `backend.py` + `agent.py` (DuckDB dupliqué) | `core/duckdb_engine.py` — une seule instance |
| Thèmes Overture et colonnes SQL | `modules/overture.py` |
| `gee_routes.py` (catalogue, indices, palettes) | `services/gee.py` + `modules/raster.py` |
| Définitions d'outils de l'agent | `modules/agent.py` |
| Opérations turf.js côté navigateur | `modules/spatial.py` — désormais côté serveur |

**Corrections apportées** :

- **Secrets exposés** : `gee_routes.py` contenait en clair l'adresse du compte
  de service et le chemin absolu de la clé privée
  (`/var/www/google/laravelauth-477918-....json`). Tout passe par
  l'environnement.
- **Injection SQL** : les filtres étaient interpolés sans échappement
  (`categories.primary = '{args['category']}'`). Les entrées sont désormais
  validées par Pydantic et les littéraux échappés.
- **Conversion géométrique incomplète** : `query_geojson()` dans `backend.py`
  ne savait convertir que les points (`if "POINT" in str(geom_wkt)`) — les
  polygones et lignes étaient silencieusement perdus. On utilise
  `ST_AsGeoJSON()` côté SQL.
- **Analyse spatiale inaccessible hors navigateur** : turf.js étant côté
  client, ni l'API ni les scripts ne pouvaient en bénéficier.
- **Dépendance Mapbox** : routes et isochrones exigeaient une clé payante.
  Remplacé par OSRM public, avec repli géométrique documenté.

---

### `city-roads` (fork de `anvaka/city-roads`)

**Ce qu'il fait** : rendu WebGL de toutes les routes d'une ville, données
Overpass, cache de 3 000 villes en protobuf. Projet remarquable, mais orienté
production d'images.

**Ce qui est repris** : les gabarits de requêtes Overpass de `src/lib/Query.js`
— notamment `RoadStrict`, expression affinée par la communauté OSM pour ne
retenir que les voies réellement carrossables :

```javascript
way["highway"~"^(((motorway|trunk|primary|secondary|tertiary)(_link)?)
   |unclassified|residential|living_street|pedestrian|service|track)$"]["area"!=yes]
```

Ces gabarits deviennent les *presets* de `/api/osm/presets`, exécutés côté
serveur avec cache — Overpass étant fréquemment limité en débit.

Le fork reste utile tel quel pour la production d'images artistiques.

---

### `GeoRouteX` (fork de `Suman-hulk/GeoRouteX`)

**Ce qu'il fait** : plugin QGIS de routage Dijkstra sur des couches réseau,
avec animation du parcours et estimation de durée.

**Limite** : enfermé dans QGIS — inutilisable depuis une application web ou un
script.

**Ce qui est repris** : le service `modules/routing.py` expose le calcul
d'itinéraire en HTTP. Le plugin QGIS peut d'ailleurs devenir un **client** de
cette API plutôt que de recalculer le graphe localement.

L'isochrone est calculée par échantillonnage de la matrice de temps OSRM puis
enveloppe convexe des points atteignables — plus fidèle qu'un simple cercle,
sans nécessiter de clé Mapbox.

---

### `GIS-Web-Development` (fork de `Omariu/GIS-Web-Development`)

28 pages HTML de démonstration de l'API ArcGIS JavaScript : rendus par classes,
valeurs uniques, carte de chaleur, widgets de recherche et de mesure, scènes 3D.

**Aucun code n'est intégré** : la plateforme utilise MapLibre GL (libre, sans
clé) et non ArcGIS. Ce fork reste un catalogue de patrons cartographiques
(classification, légendes, outils de mesure) pour les évolutions de l'interface.

---

## Dépôts récupérés en seconde passe

Ces quatre dépôts, inaccessibles lors de la première migration, ont été
rendus publics et intégrés depuis.

### `AGRISIGHT` → `modules/agriculture.py` + `modules/climate.py`

**Ce qu'il faisait** : « AgriSight Pro v6.5 », application Streamlit
monolithique de 1496 lignes — suivi agronomique avec degrés-jours, bilan
FAO-56, indices de stress, graphiques Plotly, rapports PDF ReportLab et
recommandations par IA Gemini.

**Ce qui est repris** : la classe `AgronomicCalculator` — GDD, stades
phénologiques, bilan hydrique, indices de stress, rendement potentiel. Ces
calculs sont solides et deviennent des fonctions pures, testables et
appelables en API.

**Problème corrigé** : `calculate_vegetation_indices()` ne mesurait rien. Elle
**fabriquait** le NDVI à partir d'une sinusoïde et de bruit gaussien :

```python
growth_factor = (1 + np.sin(x - np.pi / 2)) / 2
ndvi = 0.2 + (ndvi_base - 0.2) * growth_factor + np.random.normal(0, 0.02, days)
```

Les courbes avaient l'allure convaincante d'un cycle végétatif, mais aucun
lien avec la parcelle observée — EVI, SAVI et LAI en étaient dérivés, donc
tout aussi fictifs. `POST /api/agriculture/vegetation` renvoie désormais une
erreur explicite qui renvoie vers `/api/raster/timeseries` (Sentinel-2 réel).

### `AgriSight_v2` → fusionné dans `modules/agriculture.py`

**Ce qu'il faisait** : refonte modulaire d'AgriSight en six fichiers
(`config`, `api`, `database`, `analytics`, `ui`, `app`), avec une base de
cultures typée par `dataclass`, des zones agro-écologiques et des préférences
pédologiques.

**Pourquoi c'était un doublon** : même objectif qu'AGRISIGHT, données
complémentaires. AGRISIGHT détenait les paramètres thermiques
(`base_temp`, `opt_temp`, `max_temp`, `stages`, `kc`), la v2 les seuils
pluviométriques, les rendements maximaux et les sols. La base de cultures de
la plateforme est la **réunion des deux**, sur 10 cultures.

Le meilleur de la v2 est son typage : c'est ce modèle qui structure le
dictionnaire `CROPS`.

### `terracheck-senegal` → `modules/land.py`

**Ce qu'il faisait** : application Next.js 14 + TypeScript d'analyse foncière
avant achat au Sénégal — score sur six critères pondérés, carte Leaflet,
export PDF, recommandations OpenAI.

**Deux idées reprises telles quelles, parce qu'elles sont justes** :

1. **Redistribution des poids.** Quand une source est indisponible, son poids
   est réparti sur les autres au lieu d'être compté comme zéro. Un terrain
   n'est pas dévalué parce qu'Overpass est en panne. Le champ `coverage_pct`
   indique la part de données réellement obtenue.

2. **Refus des données simulées.** Le dépôt avait vidé son `mockGee.ts` avec
   ce commentaire : « Si une source est indisponible, la donnée est absente
   (null) plutôt que simulée. » C'est exactement la règle de cette plateforme
   — et l'inverse de ce que faisait `floodingsn`.

**Ce qui change** : TerraCheck exécutait Overpass et Esri **dans le
navigateur** pour contourner le blocage des IP Vercel, ce qui rendait
l'analyse d'accessibilité inaccessible en API. Ici tout est côté serveur.
Le score reste borné au Sénégal côté front d'origine ; l'API accepte
n'importe quel point et propose sept villes de référence ouest-africaines.

### `sante-isochrones-app` → `modules/routing.py` + `core/projection.py`

**Ce qu'il faisait** : générateur d'isochrones de desserte sanitaire avec
**six moteurs** de routage (OSM Pur via `Tps_min`, OSMnx, ORS, OSRM,
Valhalla, GraphHopper), trois algorithmes de contour et un mode comparaison.

**Apport majeur — l'interpolation radiale.** Mon implémentation initiale
seuillait un nuage de points échantillonnés : le contour sautait d'un anneau
à l'autre. Ce dépôt fait mieux — pour chaque azimut, il mesure le temps réseau
réel puis **interpole la position du front** le long du rayon :

```python
ratio = min(1.0, target_sec / duration)
point = (lon + dlon * ratio, lat + dlat * ratio)
```

Le contour épouse ainsi le réseau. C'est désormais la méthode par défaut.

**Second apport — l'alpha-shape.** Une enveloppe convexe surestime toujours la
zone atteignable : elle comble les échancrures entre les axes routiers.
L'alpha-shape produit un contour concave qui les respecte. Implémentée ici via
SciPy et Shapely (déjà dans le socle) plutôt que la bibliothèque `alphashape`.

**Troisième apport — la projection UTM.** Le dépôt reprojetait
systématiquement avant de mesurer une aire. Mesurer en degrés donne un
résultat faux ; `core/projection.py` généralise cette précaution à toute la
plateforme.

**Non repris** : les moteurs à clé payante (ORS, GraphHopper) et OSMnx
(dépendance lourde). OSRM public couvre le besoin sans clé. Le moteur
« OSM Pur » exploitant une colonne `Tps_min` d'une couche locale est une bonne
idée pour des données de terrain — à rebrancher via un import utilisateur.

---

## Dépôt encore inaccessible

| Dépôt | Statut |
|---|---|
| `Zone` | Toujours « Repository not found » — privé ou supprimé |

Le schéma `AreaOfInterest` (bbox, centre+rayon, GeoJSON, code administratif)
couvre vraisemblablement ce que faisait ce dépôt. S'il est rendu accessible,
son intégration suivra la procédure décrite dans
[`ARCHITECTURE.md`](ARCHITECTURE.md#ajouter-un-module).

---

## Corrections notables

Bugs réels identifiés en lisant le code d'origine :

1. **Téléchargement intégral du pays** (`Openbuildings`) — plusieurs Go pour
   extraire un quartier. Corrigé par pushdown DuckDB.
2. **Données factices présentées comme des résultats** (`floodingsn`) —
   population et surfaces inondées codées en dur.
3. **Secrets en clair dans le code** (`openmapagents`) — compte de service et
   chemin de clé GEE.
4. **Injection SQL** (`openmapagents`) — filtres interpolés sans échappement.
5. **Perte silencieuse des géométries non ponctuelles** (`openmapagents`) —
   conversion WKT limitée aux points.
6. **Variables non définies** (`openbuildings_app`) — `data_type`,
   `output_format`, `shapely` non importé.
7. **Import circulaire** (`Carto-facileSN`) — `routes/exports.py` ↔ `app.py`.
8. **Eaux permanentes comptées comme inondations** (`innondationSN`) — corrigé
   par le masque JRC.
9. **Centroïde biaisé** — bug détecté par les tests lors de cette migration :
   la moyenne des sommets est faussée par le sommet de fermeture dupliqué et
   par une densité de vertex inégale. Remplacé par un centroïde surfacique
   pondéré, trous déduits (`core/geo.py`, tests dans `TestCentroidAccuracy`).
10. **NDVI fabriqué** (`AGRISIGHT`) — `calculate_vegetation_indices()`
    générait les courbes NDVI/EVI/SAVI/LAI par sinusoïde et bruit gaussien.
    Remplacé par les séries Sentinel-2 réelles du module `raster`.
11. **Alpha-shape dégénérée** — bug introduit puis corrigé pendant cette
    seconde passe : le chaînage manuel des arêtes de bord ne gérait pas les
    frontières fragmentées et renvoyait une boucle partielle (0,16 km² au lieu
    de ~11 km²). Remplacé par une union Shapely des triangles conservés, avec
    repli sur l'enveloppe convexe si le contour dégénère
    (`TestIsochroneGeometry::test_degenerate_alpha_falls_back`).
