# Open Buildings Downloader

Application Streamlit pour extraire des bâtiments Open Buildings et les utiliser dans **ArcGIS Pro**. Elle évite l'export asynchrone de Google Earth Engine / Google Tasks quand la source **VIDA Google–Microsoft** est sélectionnée.

## Démarrage rapide

Utilisez Python 3.10 ou plus récent :

```bash
git clone https://github.com/pratisig/Openbuildings.git
cd Openbuildings
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell : .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Ouvrez ensuite l'adresse affichée par Streamlit, généralement `http://localhost:8501`.

## Utilisation recommandée (rapide et sans Earth Engine)

1. Dans **Source des bâtiments**, choisissez **VIDA Google–Microsoft**.
2. Sélectionnez un pays.
3. Dessinez une petite zone, importez un GeoJSON/GPKG/Shapefile ZIP, ou saisissez une BBOX.
4. Cochez **Exporter les centroïdes (points)** si vous voulez un point par bâtiment plutôt que les polygones.
5. Choisissez **Géodatabase fichier ArcGIS Pro (ZIP)** puis téléchargez.
6. Décompressez l'archive et ajoutez le dossier `.gdb` dans le catalogue ArcGIS Pro. La couche s'appelle `buildings`.

Le filtre spatial est transmis au lecteur GeoParquet avant le téléchargement. L'application ne doit donc pas charger l'intégralité du pays lorsque la source publie un index spatial. Pour de bons temps de réponse, limitez l'extraction à une ville, un quartier ou une emprise de projet.

## Autres sources et qualité

- **OpenStreetMap (Overpass)** est disponible dans l'application. Il extrait les objets portant le tag `building=*` pour l'emprise sélectionnée. Choisissez une zone modeste : le service public Overpass peut refuser les requêtes trop vastes ou être temporairement chargé.
- **VIDA Google–Microsoft** et **Google Open Buildings v3** sont des empreintes produites par IA. Elles sont très utiles pour l'analyse à grande échelle, mais leur position, leur forme et leur complétude varient selon la qualité de l'imagerie. Le champ `confidence` de Google permet un filtrage, sans garantir l'exactitude.
- **OSM** peut être plus exact là où des contributeurs ont numérisé les bâtiments, mais peut aussi être incomplet dans les zones peu cartographiées.
- Les données **Meta/Facebook HRSL** ouvertes sont des grilles de population/implantation, et non une couche mondiale d'empreintes de bâtiments comparable aux trois sources ci-dessus. Elles ne sont donc pas proposées comme « bâtiments » afin d'éviter une interprétation erronée.

Aucune de ces sources ne remplace le cadastre ou une donnée topographique validée.

## Source Google Earth Engine

L'option **Google Open Buildings v3 (Earth Engine)** est disponible avec les seuils `confidence` 0.65, 0.70 et 0.75. Elle dépend néanmoins des quotas, de l'authentification et de la disponibilité des serveurs Earth Engine : elle ne résout pas une saturation côté Google.

Avant de l'utiliser, authentifiez Earth Engine sur la machine ou configurez des identifiants de service pour le déploiement, puis indiquez au besoin le projet Google Cloud autorisé. Réduisez fortement l'emprise si l'extraction échoue.

## Formats acceptés pour la zone

- GeoJSON / JSON
- GeoPackage (`.gpkg`)
- Shapefile contenu dans une archive ZIP
- polygone ou rectangle dessiné sur la carte
- BBOX WGS 84

Les géométries importées sont converties en WGS 84 automatiquement.
