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
4. Choisissez **Géodatabase fichier ArcGIS Pro (ZIP)** puis téléchargez.
5. Décompressez l'archive et ajoutez le dossier `.gdb` dans le catalogue ArcGIS Pro. La couche s'appelle `buildings`.

Le filtre spatial est transmis au lecteur GeoParquet avant le téléchargement. L'application ne doit donc pas charger l'intégralité du pays lorsque la source publie un index spatial. Pour de bons temps de réponse, limitez l'extraction à une ville, un quartier ou une emprise de projet.

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
