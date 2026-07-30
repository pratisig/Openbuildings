import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import folium
import geopandas as gpd
from folium.plugins import Draw
import requests
import streamlit as st
from shapely.geometry import box, shape
from streamlit_folium import st_folium
from io import BytesIO
import time

# Configuration
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

# URLs correctes VIDA Google-Microsoft Open Buildings
GEOPARQUET_BASE = "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country"

@st.cache_data
def load_countries():
    """Charge le GeoJSON des pays depuis le fichier local"""
    geojson_path = "countries.geojson"
    
    if not os.path.exists(geojson_path):
        st.error(f"❌ Fichier {geojson_path} non trouvé")
        return None
    
    try:
        gdf = gpd.read_file(geojson_path)
        return gdf
    except Exception as e:
        st.error(f"Erreur chargement GeoJSON : {e}")
        return None

def prepare_regions(countries_gdf):
    """Prépare la liste des pays pour le selectbox"""
    if countries_gdf is None:
        return [""]
    
    name_col = 'name' if 'name' in countries_gdf.columns else None
    iso_col = None
    
    if 'ISO3166-1-Alpha-3' in countries_gdf.columns:
        iso_col = 'ISO3166-1-Alpha-3'
    elif 'ISO3166-1-Alpha-2' in countries_gdf.columns:
        iso_col = 'ISO3166-1-Alpha-2'
    
    if not name_col or not iso_col:
        return [""] + [f"Zone {i}" for i in range(len(countries_gdf))]
    
    regions = []
    for _, row in countries_gdf.iterrows():
        iso_val = str(row[iso_col]).strip()
        name_val = str(row[name_col]).strip()
        if iso_val and iso_val != 'nan' and name_val and name_val != 'nan':
            regions.append(f"{name_val} ({iso_val})")
    
    return [""] + sorted(regions)

def read_aoi_upload(uploaded_file):
    """Lit une zone téléversée et renvoie une géométrie WGS 84 unique."""
    suffix = Path(uploaded_file.name).suffix.lower()
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, uploaded_file.name)
        with open(input_path, "wb") as output:
            output.write(uploaded_file.getbuffer())

        if suffix == ".zip":
            with zipfile.ZipFile(input_path) as archive:
                archive.extractall(temp_dir)
            shapefiles = list(Path(temp_dir).rglob("*.shp"))
            if not shapefiles:
                raise ValueError("Le ZIP doit contenir un Shapefile (.shp).")
            gdf = gpd.read_file(shapefiles[0])
        else:
            gdf = gpd.read_file(input_path)

    if gdf.empty:
        raise ValueError("Le fichier ne contient aucune géométrie.")
    if gdf.crs is None:
        raise ValueError("Le système de coordonnées du fichier est inconnu.")
    return gdf.to_crs("EPSG:4326").geometry.union_all()


def download_google_earth_engine_buildings(aoi, min_confidence, project_id=""):
    """Extrait Open Buildings v3 via Earth Engine pour une petite zone d'intérêt."""
    try:
        import ee
    except ImportError as exc:
        raise RuntimeError("Le paquet earthengine-api n'est pas installé.") from exc

    try:
        ee.Initialize(project=project_id or None)
    except Exception as exc:
        raise RuntimeError(
            "Earth Engine n'est pas authentifié. Configurez les identifiants Earth Engine "
            "et, si nécessaire, indiquez votre projet Google Cloud dans la barre latérale."
        ) from exc

    collection = ee.FeatureCollection("GOOGLE/Research/open-buildings/v3/polygons")
    collection = collection.filterBounds(ee.Geometry(aoi.__geo_interface__))
    if min_confidence is not None:
        collection = collection.filter(ee.Filter.gte("confidence", min_confidence))

    try:
        download_url = collection.getDownloadURL({"format": "GEOJSON", "filename": "open_buildings"})
        response = requests.get(download_url, timeout=300)
        response.raise_for_status()
        # Earth Engine peut retourner directement du GeoJSON ou une archive ZIP
        # suivant le format négocié par son service de téléchargement.
        if response.content[:2] == b"PK":
            with tempfile.TemporaryDirectory() as temp_dir:
                archive_path = os.path.join(temp_dir, "open_buildings.zip")
                with open(archive_path, "wb") as archive:
                    archive.write(response.content)
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(temp_dir)
                geojson_files = list(Path(temp_dir).rglob("*.geojson")) + list(Path(temp_dir).rglob("*.json"))
                if not geojson_files:
                    raise ValueError("Archive Earth Engine sans fichier GeoJSON.")
                return gpd.read_file(geojson_files[0]).to_crs("EPSG:4326")
        payload = response.json()
        return gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:4326")
    except Exception as exc:
        raise RuntimeError(
            "L'extraction Earth Engine a échoué. Réduisez la zone d'intérêt : "
            "le téléchargement direct est limité par Earth Engine."
        ) from exc


def download_buildings_by_country(iso_code, bbox=None):
    """Télécharge les bâtiments pour un pays via GeoParquet"""
    
    status = st.status("🔄 Téléchargement en cours...", expanded=True)
    
    try:
        # URL du GeoParquet pour le pays
        parquet_url = f"{GEOPARQUET_BASE}/country_iso={iso_code}/{iso_code}.parquet"
        
        status.write(f"🌍 Téléchargement des bâtiments pour : {iso_code}")
        status.write(f"📂 URL : {parquet_url}")
        
        start_time = time.time()
        
        # Le filtre bbox est transmis au lecteur GeoParquet : lorsqu'un index
        # spatial est disponible, seules les parties du fichier utiles sont
        # téléchargées. C'est essentiel : charger tout un pays peut représenter
        # plusieurs millions de bâtiments.
        if bbox is not None:
            status.write("⏳ Lecture optimisée de la zone dans le GeoParquet...")
            try:
                gdf = gpd.read_parquet(parquet_url, bbox=bbox.bounds)
            except (TypeError, ValueError):
                # Compatibilité avec les anciennes versions de GeoPandas/PyArrow.
                status.write("⚠️ Index spatial indisponible : lecture complète puis filtrage.")
                gdf = gpd.read_parquet(parquet_url)
            initial_count = len(gdf)
            gdf = gdf[gdf.intersects(bbox)]
            status.write(f"📊 {len(gdf):,} bâtiments dans la zone (sur {initial_count:,} lus)")
        else:
            status.write("⏳ Lecture du fichier GeoParquet complet...")
            gdf = gpd.read_parquet(parquet_url)

        download_time = time.time() - start_time
        status.write(f"✅ {len(gdf):,} bâtiments chargés en {download_time:.1f}s")
        
        if gdf.empty:
            status.update(label="⚠️ Aucun bâtiment dans la zone", state="warning")
            return None
        
        status.update(label=f"✅ {len(gdf):,} bâtiments chargés!", state="complete")
        
        return gdf
        
    except Exception as e:
        status.update(label=f"❌ Erreur: {str(e)}", state="error")
        st.error(f"💡 Détails: Le pays '{iso_code}' n'est peut-être pas disponible dans le dataset.")
        st.info("🗺️ **Couverture** : Afrique, Asie du Sud/Sud-Est, Amérique Latine, Caraïbes (185 pays)")
        return None

def create_shapefile_zip(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée un ZIP contenant le shapefile"""
    with tempfile.TemporaryDirectory() as temp_dir:
        shp_path = os.path.join(temp_dir, f"{base_name}.shp")
        
        # Limitation des noms de colonnes à 10 caractères
        gdf_copy = gdf.copy()
        column_map = {col: col[:10] for col in gdf_copy.columns if col != 'geometry'}
        gdf_copy = gdf_copy.rename(columns=column_map)
        gdf_copy.to_file(shp_path, driver="ESRI Shapefile")
        
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                file_path = os.path.join(temp_dir, f"{base_name}{ext}")
                if os.path.exists(file_path):
                    zip_file.write(file_path, f"{base_name}{ext}")
        
        return zip_buffer.getvalue()

def create_geopackage(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée un fichier GeoPackage (SQLite spatial)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        gpkg_path = os.path.join(temp_dir, f"{base_name}.gpkg")
        gdf.to_file(gpkg_path, driver="GPKG", layer="buildings")

        with open(gpkg_path, 'rb') as f:
            return f.read()


def create_file_geodatabase_zip(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée une géodatabase fichier ESRI et la compresse pour le téléchargement.

    Une .gdb est un dossier composé de plusieurs fichiers, elle doit donc être
    distribuée dans une archive ZIP. Après extraction, le dossier .gdb peut être
    ajouté directement dans ArcGIS Pro.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        gdb_name = f"{base_name}.gdb"
        gdb_path = os.path.join(temp_dir, gdb_name)

        try:
            # OpenFileGDB est le pilote GDAL libre qui crée les File Geodatabases.
            # GeoPandas utilise pyogrio lorsqu'il est disponible.
            gdf.to_file(
                gdb_path, driver="OpenFileGDB", layer="buildings", engine="pyogrio"
            )
        except Exception:
            # Certaines installations GDAL proposent uniquement le pilote ESRI
            # propriétaire (FileGDB). On l'essaie avant de signaler une erreur utile.
            if os.path.isdir(gdb_path):
                shutil.rmtree(gdb_path)
            try:
                gdf.to_file(
                    gdb_path, driver="FileGDB", layer="buildings", engine="pyogrio"
                )
            except Exception as fallback_exc:
                raise RuntimeError(
                    "Impossible de créer la géodatabase. Installez une version de "
                    "GDAL/pyogrio avec le pilote OpenFileGDB (GDAL 3.6 ou plus récent)."
                ) from fallback_exc

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, _, files in os.walk(gdb_path):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    zip_file.write(file_path, os.path.relpath(file_path, temp_dir))

        return zip_buffer.getvalue()

def main():
    st.title("🏢 Open Buildings Downloader")
    st.markdown("Téléchargez les données **Google-Microsoft Open Buildings** (2.5+ milliards de bâtiments)")
    
    # Info source
    st.info("📊 **Source** : VIDA Google-Microsoft Open Buildings via Source Cooperative | Format : GeoParquet")
    
    # Sidebar - Paramètres
    with st.sidebar:
        st.header("⚙️ Paramètres")

        data_source = st.radio(
            "Source des bâtiments",
            ["VIDA Google–Microsoft", "Google Open Buildings v3 (Earth Engine)"],
            help="VIDA est la source ouverte actuelle. Earth Engine donne accès à la collection Google v3 et à son champ confidence."
        )
        ee_project_id = ""
        min_confidence = None
        if data_source == "Google Open Buildings v3 (Earth Engine)":
            ee_project_id = st.text_input("Projet Google Cloud Earth Engine (optionnel)")
            min_confidence = st.select_slider(
                "Confiance minimale", options=["Aucun filtre", "0.65", "0.70", "0.75"], value="Aucun filtre"
            )
            min_confidence = None if min_confidence == "Aucun filtre" else float(min_confidence)

        export_format = st.selectbox(
            "📦 Format d'export",
            ["Géodatabase fichier ArcGIS Pro (ZIP)", "GeoJSON", "Shapefile (ZIP)", "GeoPackage (GPKG)", "GeoParquet", "CSV"],
            help=(
                "Géodatabase fichier : format natif ArcGIS Pro, livré dans un ZIP à extraire\n"
                "GeoJSON : universel\nShapefile : compatible SIG\n"
                "GeoPackage : recommandé pour les SIG libres\nGeoParquet : format cloud-native"
            )
        )
        
        simplify_geom = st.checkbox(
            "Simplifier géométries",
            value=False,
            help="Réduit la taille du fichier"
        )
        
        if simplify_geom:
            tolerance = st.slider(
                "Tolérance",
                min_value=0.00001,
                max_value=0.0001,
                value=0.00001,
                format="%.5f"
            )
        
        st.markdown("---")
        st.markdown("### 💡 Info Dataset")
        st.markdown("""
        - **Total** : 2.5+ milliards de bâtiments
        - **Sources** : Google + Microsoft
        - **Couverture** : 185 pays
        - **Régions** : Afrique, Asie du Sud/Sud-Est, Amérique Latine
        """)
        
        st.markdown("---")
        st.markdown("[📖 Documentation VIDA](https://source.coop/vida/google-microsoft-open-buildings)")
    
    # La liste des pays est nécessaire uniquement pour les fichiers VIDA par pays.
    countries_gdf = load_countries() if data_source == "VIDA Google–Microsoft" else None
    if countries_gdf is not None:
        st.sidebar.success(f"✅ {len(countries_gdf)} pays disponibles")
    regions_list = prepare_regions(countries_gdf)
    
    st.markdown("### 🌍 Zone d'intérêt")
    choice = ""
    if data_source == "VIDA Google–Microsoft":
        choice = st.selectbox("Pays (requis pour la source VIDA) :", regions_list, key="country_select")

    aoi_geom = None
    aoi_method = st.radio(
        "Définir la zone", ["Dessiner sur la carte", "Importer un fichier", "Coordonnées BBOX"], horizontal=True
    )
    if aoi_method == "Dessiner sur la carte":
        st.caption("Utilisez les outils polygon ou rectangle situés en haut à gauche de la carte.")
        map_view = folium.Map(location=[14.72, -17.47], zoom_start=11, tiles="OpenStreetMap")
        Draw(export=False, draw={"polyline": False, "marker": False, "circle": False, "circlemarker": False}).add_to(map_view)
        map_state = st_folium(map_view, height=430, use_container_width=True, key="aoi_map")
        drawings = map_state.get("all_drawings") or []
        if drawings:
            aoi_geom = shape(drawings[-1]["geometry"])
            st.success("✅ Zone dessinée prise en compte.")
    elif aoi_method == "Importer un fichier":
        uploaded_aoi = st.file_uploader("Zone d'intérêt", type=["geojson", "json", "gpkg", "zip"])
        if uploaded_aoi:
            try:
                aoi_geom = read_aoi_upload(uploaded_aoi)
                st.success("✅ Zone importée et reprojetée en WGS 84.")
            except Exception as exc:
                st.error(f"❌ Fichier de zone non valide : {exc}")
    else:
        st.caption("Coordonnées en degrés WGS 84 (longitude / latitude).")
        col1, col2, col3, col4 = st.columns(4)
        w = col1.number_input("⬅️ Ouest", value=-17.50, format="%.6f")
        s = col2.number_input("🔽 Sud", value=14.65, format="%.6f")
        e = col3.number_input("➡️ Est", value=-17.35, format="%.6f")
        n = col4.number_input("🔼 Nord", value=14.80, format="%.6f")
        if n > s and e > w:
            aoi_geom = box(w, s, e, n)
        else:
            st.error("❌ Coordonnées invalides : Nord doit être supérieur à Sud et Est à Ouest.")

    # Bouton d'extraction
    if st.button("🚀 Télécharger les bâtiments", type="primary", use_container_width=True):
        if data_source == "VIDA Google–Microsoft" and not choice:
            st.warning("⚠️ Veuillez sélectionner un pays pour la source VIDA.")
            return
        if aoi_geom is None:
            st.warning("⚠️ Dessinez, importez ou renseignez une zone d'intérêt.")
            return

        try:
            iso_code = choice.split('(')[-1].strip(')') if choice else "GEE"
            name = iso_code
            
            st.markdown("---")
            st.subheader(f"📥 Téléchargement : {data_source}")

            # VIDA lit le GeoParquet du pays puis conserve les bâtiments qui
            # intersectent la géométrie ; Earth Engine applique le filtre côté serveur.
            if data_source == "VIDA Google–Microsoft":
                buildings_gdf = download_buildings_by_country(iso_code, aoi_geom)
            else:
                buildings_gdf = download_google_earth_engine_buildings(
                    aoi_geom, min_confidence, ee_project_id
                )
            
            # Résultats
            if buildings_gdf is None or buildings_gdf.empty:
                st.warning("⚠️ Aucun bâtiment trouvé")
                st.info("""
💡 **Raisons possibles** :
- Pays non couvert par le dataset
- Zone filtrée trop petite ou sans données
                
🗺️ **Pays couverts** : Principalement Afrique, Asie du Sud/Sud-Est, Amérique Latine
                """)
            else:
                # Simplification optionnelle
                if simplify_geom and len(buildings_gdf) > 1000:
                    with st.spinner("🔧 Simplification des géométries..."):
                        buildings_gdf['geometry'] = buildings_gdf['geometry'].simplify(tolerance=tolerance)
                
                st.success(f"🎉 **{len(buildings_gdf):,} bâtiments** extraits avec succès !")
                
                # Statistiques
                st.markdown("### 📊 Statistiques")
                col1, col2, col3, col4 = st.columns(4)
                
                col1.metric("🏗️ Bâtiments", f"{len(buildings_gdf):,}")
                
                if 'area_in_meters' in buildings_gdf.columns:
                    total_area = buildings_gdf['area_in_meters'].sum() / 1e6
                    avg_area = buildings_gdf['area_in_meters'].mean()
                    col2.metric("📐 Surface totale", f"{total_area:.2f} km²")
                    col3.metric("📏 Moyenne", f"{avg_area:.1f} m²")
                
                if 'bf_source' in buildings_gdf.columns:
                    sources = buildings_gdf['bf_source'].value_counts().to_dict()
                    google_count = sources.get('google', 0)
                    microsoft_count = sources.get('microsoft', 0)
                    col4.metric("🔍 Sources", f"G: {google_count:,} | M: {microsoft_count:,}")
                
                # Export
                st.markdown("### 💾 Téléchargement")
                
                file_data = None
                filename = None
                mime_type = None
                
                with st.spinner(f"📦 Préparation du fichier {export_format}..."):
                    if export_format == "Géodatabase fichier ArcGIS Pro (ZIP)":
                        file_data = create_file_geodatabase_zip(buildings_gdf, f"{name}_open_buildings")
                        filename = f"{name}_open_buildings.gdb.zip"
                        mime_type = "application/zip"

                    elif export_format == "GeoJSON":
                        geojson_buffer = BytesIO()
                        buildings_gdf.to_file(geojson_buffer, driver="GeoJSON")
                        file_data = geojson_buffer.getvalue()
                        filename = f"{name}_buildings.geojson"
                        mime_type = "application/geo+json"
                        
                    elif export_format == "Shapefile (ZIP)":
                        file_data = create_shapefile_zip(buildings_gdf, f"{name}_buildings")
                        filename = f"{name}_buildings.zip"
                        mime_type = "application/zip"
                        
                    elif export_format == "GeoPackage (GPKG)":
                        file_data = create_geopackage(buildings_gdf, f"{name}_buildings")
                        filename = f"{name}_buildings.gpkg"
                        mime_type = "application/geopackage+sqlite3"
                    
                    elif export_format == "GeoParquet":
                        parquet_buffer = BytesIO()
                        buildings_gdf.to_parquet(parquet_buffer)
                        file_data = parquet_buffer.getvalue()
                        filename = f"{name}_buildings.parquet"
                        mime_type = "application/octet-stream"
                    
                    elif export_format == "CSV":
                        csv_buffer = BytesIO()
                        df_export = buildings_gdf.copy()
                        df_export['geometry_wkt'] = df_export['geometry'].apply(lambda x: x.wkt)
                        df_export = df_export.drop(columns=['geometry'])
                        df_export.to_csv(csv_buffer, index=False, encoding='utf-8')
                        file_data = csv_buffer.getvalue()
                        filename = f"{name}_buildings.csv"
                        mime_type = "text/csv"
                
                # Bouton de téléchargement
                file_size_mb = len(file_data) / (1024 * 1024)
                st.download_button(
                    label=f"📥 Télécharger {export_format} ({file_size_mb:.1f} MB)",
                    data=file_data,
                    file_name=filename,
                    mime=mime_type,
                    use_container_width=True
                )

                if export_format == "Géodatabase fichier ArcGIS Pro (ZIP)":
                    st.info(
                        "**ArcGIS Pro :** décompressez le fichier téléchargé, puis dans le "
                        "Catalogue ajoutez le dossier contenant `*.gdb`. La couche `buildings` "
                        "est prête à être ajoutée à la carte. Ne renommez pas les fichiers à "
                        "l'intérieur de la géodatabase."
                    )
                
                # Aperçu
                with st.expander("👁️ Aperçu des 10 premiers bâtiments"):
                    st.dataframe(buildings_gdf.head(10))
                
                # Colonnes disponibles
                with st.expander("📋 Colonnes disponibles"):
                    st.write(", ".join(buildings_gdf.columns.tolist()))
                    
                    if 'area_in_meters' in buildings_gdf.columns:
                        st.markdown("**Statistiques de surface :**")
                        st.write(f"- Min : {buildings_gdf['area_in_meters'].min():.2f} m²")
                        st.write(f"- Max : {buildings_gdf['area_in_meters'].max():.2f} m²")
                        st.write(f"- Médiane : {buildings_gdf['area_in_meters'].median():.2f} m²")
                    
                    if 'confidence' in buildings_gdf.columns:
                        valid_conf = buildings_gdf['confidence'].dropna()
                        if len(valid_conf) > 0:
                            st.markdown("**Confiance (Google uniquement) :**")
                            st.write(f"- Moyenne : {valid_conf.mean():.2%}")
                            st.write(f"- Min : {valid_conf.min():.2%}")
                            st.write(f"- Max : {valid_conf.max():.2%}")
        
        except Exception as e:
            st.error(f"❌ Erreur système : {e}")
            import traceback
            with st.expander("🔍 Détails de l'erreur"):
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
