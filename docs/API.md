# Référence de l'API

Base : `http://localhost:8000` · Documentation interactive : `/docs` · Schéma : `/openapi.json`

---

## La zone d'étude (`AreaOfInterest`)

Tous les endpoints spatiaux acceptent le même objet `area`. Quatre formes
équivalentes :

```jsonc
{ "bbox": [-17.55, 14.63, -17.33, 14.82] }              // emprise rectangulaire
{ "center": [-17.44, 14.69], "radius_m": 2000 }         // centre + rayon
{ "geojson": { "type": "Polygon", "coordinates": [] } } // polygone exact
{ "admin_code": "SEN.1.2_1" }                           // entité administrative
```

Quand un polygone est fourni, la découpe exacte s'ajoute au filtre
rectangulaire (`clip_to_geometry`, actif par défaut).

---

## Système

| Méthode | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Présentation et liste des modules |
| `GET` | `/health` | État détaillé de chaque service |
| `GET` | `/api/catalog` | Catalogue des modules |
| `GET` | `/api/catalog/modules/{id}` | Détail d'un module |
| `GET` | `/api/catalog/migration` | Traçabilité des dépôts d'origine |
| `POST` | `/api/cache/clear?namespace=` | Vider le cache |

---

## Bâtiments — Open Buildings

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/buildings/countries?q=` |
| `GET` | `/api/buildings/countries/{iso3}` |
| `POST` | `/api/buildings/query` |
| `POST` | `/api/buildings/stats` |

```jsonc
// POST /api/buildings/query
{
  "country_iso3": "SEN",
  "area": { "center": [-17.44, 14.69], "radius_m": 1500 },
  "min_confidence": 0.75,      // 0 – 1
  "min_area_m2": 20,
  "limit": 5000,               // max 200 000
  "clip_to_geometry": true
}
```

Réponse : `FeatureCollection` avec `metadata.count`, `total_area_m2`,
`limit_reached`, `cached`.

`/stats` renvoie les agrégats (total, surfaces moyenne/médiane, confiance,
densité au km²) **sans transférer les géométries** — beaucoup plus rapide pour
un simple dénombrement.

---

## Overture Maps

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/overture/themes` |
| `POST` | `/api/overture/query` |
| `POST` | `/api/overture/stats` |

```jsonc
{
  "theme": "places",   // places | buildings | transportation | divisions | base | addresses
  "area": { "bbox": [-17.55, 14.63, -17.33, 14.82] },
  "category": "pharmacy",
  "min_confidence": 0.6,
  "limit": 1000
}
```

`/stats` accepte `group_by` (ex. `category`, `class`) pour une répartition.

---

## OpenStreetMap

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/osm/presets` |
| `POST` | `/api/osm/query` |
| `POST` | `/api/osm/roads` |

Gabarits : `roads_all`, `roads_main`, `roads_strict`, `buildings`, `waterways`,
`water_bodies`, `health`, `education`, `markets`, `landuse`.

```jsonc
{
  "preset": "health",
  "area": { "center": [-17.44, 14.69], "radius_m": 3000 },
  "limit": 5000
}
```

`/roads` ajoute `length_m` par entité et une répartition `by_class` avec les
longueurs cumulées.

> Overpass refuse les zones supérieures à ~10 000 km² : l'API renvoie un `400`
> explicite avant d'envoyer la requête.

---

## Administratif

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/admin/countries?focus=true` |
| `GET` | `/api/admin/gadm/{iso3}/{level}?with_geometry=&parent_code=` |
| `GET` | `/api/admin/senegal` |
| `GET` | `/api/admin/senegal/{niveau}` |
| `GET` | `/api/admin/resolve?code=SEN.1.2_1` |

Niveaux du Sénégal : `regions` (14), `departements` (46),
`arrondissements` (133), `communes` (557).

`with_geometry=false` allège fortement la réponse quand seule la liste
importe. `/resolve` renvoie bbox, centroïde, superficie et géométrie — à
réinjecter tel quel dans un autre module.

---

## Géocodage

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/geocoding/search?q=&limit=&country=&with_geometry=` |
| `GET` | `/api/geocoding/reverse?lat=&lon=&zoom=` |

---

## Itinéraires et accessibilité

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/routing/profiles` |
| `POST` | `/api/routing/route` |
| `POST` | `/api/routing/isochrone` |
| `POST` | `/api/routing/accessibility` |

```jsonc
// Itinéraire
{ "waypoints": [[-17.44, 14.69], [-16.92, 14.79]], "profile": "car", "steps": true }

// Isochrones
{ "center": [-17.44, 14.69], "minutes": [5, 10, 15], "profile": "foot" }

// Accessibilité — équipement le plus proche pour chaque origine
{
  "origins": [[-17.44, 14.69], [-17.46, 14.71]],
  "facilities": { "type": "FeatureCollection", "features": [] },
  "max_minutes": 30,
  "profile": "car"
}
```

L'accessibilité renvoie par origine : `nearest_facility`, `duration_min`,
`distance_km`, `reachable`, plus un `coverage_rate` global.

> Si OSRM est injoignable, la réponse porte `approximate: true` et le calcul
> se fait à vol d'oiseau selon la vitesse moyenne du mode.

---

## Analyse spatiale

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/spatial/operations` |
| `POST` | `/api/spatial/run` |

| Opération | Entrées | Paramètres |
|---|---|---|
| `buffer` | 1 | `radius_m` (obligatoire) |
| `centroid` | 1 | — |
| `convex_hull` | 1 | — |
| `dissolve` | 1 | `attribute` (Shapely requis) |
| `clip` | 2 | — |
| `intersection` | 2 | Shapely requis |
| `difference` | 2 | Shapely requis |
| `points_in_polygon` | 2 | — |
| `nearest` | 2 | — |
| `stats` | 1 | `attribute` |

```jsonc
{
  "operation": "buffer",
  "layer_a": { "type": "FeatureCollection", "features": [] },
  "layer_b": null,
  "params": { "radius_m": 500 }
}
```

---

## Imagerie satellite *(nécessite Earth Engine)*

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/raster/status` |
| `GET` | `/api/raster/datasets` |
| `POST` | `/api/raster/tiles` |
| `POST` | `/api/raster/timeseries` |

Jeux de données : `sentinel2`, `sentinel1`, `landsat8`, `landsat9`,
`modis_ndvi`, `modis_lst`, `worldcover`, `srtm`, `era5`, `worldpop`.

```jsonc
{
  "dataset": "sentinel2",
  "index": "NDVI",           // RGB | NDVI | NDWI | NDBI | EVI | NIR
  "area": { "bbox": [-17.55, 14.63, -17.33, 14.82] },
  "date_start": "2024-06-01",
  "date_end": "2024-09-30",
  "cloud_max": 20,
  "composite": "median"      // median | mosaic | least_cloudy
}
```

`/tiles` renvoie une URL de tuiles XYZ à ajouter à la carte.
`/timeseries` renvoie l'évolution de l'indice sur la zone (moyenne, médiane,
maximum ou minimum par date).

---

## Inondations *(nécessite Earth Engine)*

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/flood/status` |
| `POST` | `/api/flood/analyze` |
| `POST` | `/api/flood/exposure` |

```jsonc
{
  "area": { "bbox": [-16.5, 15.9, -16.2, 16.1] },
  "flood_start": "2024-09-01",
  "flood_end": "2024-10-15",
  "reference_start": null,   // défaut : même période l'année précédente
  "threshold_db": 1.3,       // baisse de rétrodiffusion VV
  "max_slope_deg": 5,        // masque de pente
  "include_population": true,
  "include_geometry": false  // vectorisation du contour (plus lent)
}
```

Réponse : `flooded_area_km2`, `flooded_ratio_pct`, `population.exposed`,
`tile_url` pour l'affichage.

`/exposure` croise le masque d'inondation avec une couche d'infrastructures et
marque chaque entité d'un booléen `flood_impacted`.

---

## Climat

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/climate/parameters` |
| `POST` | `/api/climate/timeseries` |

Paramètres : `PRECTOTCORR`, `T2M`, `T2M_MAX`, `T2M_MIN`, `RH2M`, `WS2M`,
`ALLSKY_SFC_SW_DWN`.

Pour les précipitations, le résumé inclut `total_mm`, `rainy_days` (≥ 1 mm) et
`heavy_rain_days` (≥ 20 mm).

---

## Agriculture

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/agriculture/crops` |
| `GET` | `/api/agriculture/crops/{crop_id}` |
| `GET` | `/api/agriculture/zones` |
| `POST` | `/api/agriculture/season` |
| `POST` | `/api/agriculture/suitability` |

Dix cultures : `mil`, `sorgho`, `mais`, `riz`, `arachide`, `niebe`, `manioc`,
`tomate`, `oignon`, `coton`.

```jsonc
// Bilan d'une campagne
{
  "crop": "mil",
  "latitude": 14.69, "longitude": -17.44,
  "sowing_date": "2024-07-01",
  "end_date": null,           // défaut : semis + durée du cycle
  "soil": "sableux"           // optionnel
}
```

Réponse : degrés-jours cumulés, stade phénologique, bilan hydrique FAO-56
(ETc, déficit, besoin d'irrigation), indices de stress thermique/hydrique/froid,
rendement potentiel et alertes.

```jsonc
// Aptitude culturale
{ "latitude": 14.69, "longitude": -17.44, "year": 2024, "soil": "sableux" }
```

Réponse : zone agro-écologique et classement des cultures par score
(pluviométrie 50 %, température 30 %, sol 20 % — redistribué si le sol
n'est pas précisé).

> Les indices de végétation ne sont **pas** fournis par ce module : ils
> viennent de `/api/raster/timeseries` (Sentinel-2 réel). `POST
> /api/agriculture/vegetation` renvoie un `400` qui le rappelle.

---

## Analyse foncière

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/land/criteria` |
| `GET` | `/api/land/references` |
| `POST` | `/api/land/analyze` |
| `POST` | `/api/land/compare` |

```jsonc
{
  "latitude": 14.75, "longitude": -17.30,
  "reference_city": "dakar",   // voir /api/land/references
  "include_services": true,
  "years": 1                   // historique pluviométrique
}
```

Six critères pondérés : inondation (30 %), topographie (15 %), occupation du
sol (15 %), accessibilité routière (15 %), services de proximité (15 %),
distance à la ville (10 %).

**Redistribution des poids** : une composante indisponible est `null` et son
poids est réparti sur les autres. `coverage_pct` indique la part de données
réellement obtenue, `missing` liste les composantes absentes.

`/compare` accepte 2 à 8 parcelles et les classe.

---

## Conversion de fichiers et BBox

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/converter/formats` |
| `POST` | `/api/converter/import` |

`/import` reçoit un formulaire `multipart/form-data` avec le champ `file` et,
optionnellement, `input_format`. Sans ce dernier, l’extension du fichier est
utilisée. La réponse est une `FeatureCollection` en WGS 84 (`EPSG:4326`) avec
un résumé dans `metadata`.

| Format d’entrée | Extensions | Dépendance |
|---|---|---|
| `geojson` | `.geojson`, `.json` | aucune |
| `geojsonl` | `.geojsonl`, `.ndjson` | aucune |
| `csv` | `.csv`, `.tsv` | aucune — longitude/latitude ou WKT |
| `kml` | `.kml` | aucune |
| `gpx` | `.gpx` | aucune |
| `wkt` | `.wkt`, `.txt` | Shapely |
| `gpkg` | `.gpkg` | GeoPandas |
| `shapefile` | `.zip` | GeoPandas |
| `geoparquet` | `.parquet`, `.geoparquet` | GeoPandas |

```bash
curl -X POST http://localhost:8000/api/converter/import \
  -F 'file=@mes_donnees.kml'
```

Dans l’interface, l’onglet **Convertir → Créer une BBox** permet aussi de
dessiner ou saisir une emprise, de copier ses coordonnées (BBox, JSON,
Overpass ou WKT) et de la télécharger dans l’un des formats d’export.

---

## Exports

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/exports/formats` |
| `POST` | `/api/exports/create` |

| Format | Extension | Dépendance |
|---|---|---|
| `geojson` | `.geojson` | aucune |
| `geojsonl` | `.geojsonl` | aucune |
| `csv` | `.csv` | aucune (géométrie en WKT) |
| `wkt` | `.wkt` | aucune |
| `kml` | `.kml` | aucune |
| `gpkg` | `.gpkg` | GeoPandas |
| `shapefile` | `.zip` | GeoPandas |
| `geoparquet` | `.parquet` | GeoPandas |

```jsonc
{ "format": "gpkg", "data": { "type": "FeatureCollection", "features": [] },
  "filename": "batiments_dakar", "layer_name": "buildings" }
```

Réponse : le fichier en pièce jointe, avec l'en-tête `X-Feature-Count`.

---

## Agent *(nécessite une clé LLM)*

| Méthode | Endpoint |
|---|---|
| `GET` | `/api/agent/tools` |
| `POST` | `/api/agent/chat` |

```jsonc
{
  "messages": [{ "role": "user", "content": "Pharmacies autour du centre de Dakar" }],
  "map_context": { "layers": [], "bbox": [], "zoom": 12 }
}
```

Réponse : `reply` (texte), `layers` (couches à afficher), `actions`
(déplacements de caméra), `tool_calls` (outils appelés).

`/tools` reste consultable même sans clé — utile pour savoir ce que l'agent
saurait faire.

---

## Codes d'erreur

| Code | Signification |
|---|---|
| `400` | Requête invalide (zone trop vaste, paramètre manquant) |
| `404` | Ressource inconnue (thème, gabarit, pays, format) |
| `422` | Validation échouée, ou aucune donnée pour la période demandée |
| `501` | Fonction nécessitant une dépendance non installée |
| `502` / `504` | Service externe en erreur ou trop lent |
| `503` | Service non configuré (Earth Engine, LLM, DuckDB) |

Les erreurs `503` indiquent toujours **quelle variable d'environnement**
renseigner.
