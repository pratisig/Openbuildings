import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from shapely.geometry import box
from io import BytesIO
import duckdb

# Configuration
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

# Source Cooperative GeoParquet (beaucoup plus rapide!)
GEOPARQUET_BASE_URL = "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet-by-country/country_iso={country}"

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

@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    """Télécharge et extrait un shapefile depuis une URL (avec cache)"""
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        
        with open(zip_path, 'wb') as f:
            f.write(r.content)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    gdf = gpd.read_file(os.path.join(root, file))
                    return gdf
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

def find_iso_column(gdf):
    """Trouve la colonne ISO dans un GeoDataFrame"""
    iso_columns = ['ISO_A3', 'ISO3', 'ADM0_A3', 'WB_A3', 'ISO_A2', 'ISO3166-1-Alpha-3', 'ISO3166-1-Alpha-2']
    
    for col in gdf.columns:
        if col in iso_columns:
            return col
    return None

def download_buildings_duckdb(bbox_or_country, mode="bbox", iso_code=None):
    """Télécharge les bâtiments via DuckDB et GeoParquet de Source Cooperative"""
    
    status = st.status("🔄 Téléchargement en cours...", expanded=True)
    
    try:
        # Connexion DuckDB
        status.write("📊 Connexion à DuckDB...")
        conn = duckdb.connect()
        conn.execute("INSTALL spatial; LOAD spatial;")
        
        if mode == "bbox":
            # Mode BBox - requête spatiale
            minx, miny, maxx, maxy = bbox_or_country.bounds
            
            status.write(f"🌍 Chargement des bâtiments pour BBox: ({minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f})")
            
            # Utilise l'URL globale GeoParquet
            parquet_url = "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet-by-country/country_iso=*/*.parquet"
            
            query = f"""
                SELECT * FROM read_parquet('{parquet_url}', hive_partitioning=1)
                WHERE bbox.xmin <= {maxx}
                AND bbox.xmax >= {minx}
                AND bbox.ymin <= {maxy}
                AND bbox.ymax >= {miny}
            """
            
            status.write("⏳ Exécution de la requête spatiale...")
            df = conn.execute(query).df()
            
        else:
            # Mode Pays - filtrage par ISO
            status.write(f"🗺️ Chargement des bâtiments pour le pays: {iso_code}")
            
            parquet_url = f"https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet-by-country/country_iso={iso_code}/*.parquet"
            
            query = f"SELECT * FROM read_parquet('{parquet_url}', hive_partitioning=1)"
            
            status.write("⏳ Téléchargement des données...")
            df = conn.execute(query).df()
        
        conn.close()
        
        if df.empty:
            status.update(label="⚠️ Aucune donnée trouvée", state="error")
            return None
        
        status.write(f"✅ {len(df):,} bâtiments téléchargés")
        status.write("🔄 Conversion en GeoDataFrame...")
        
        # Conversion en GeoDataFrame
        from shapely import wkb
        df['geometry'] = df['geometry'].apply(lambda x: wkb.loads(x))
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
        
        status.update(label=f"✅ {len(gdf):,} bâtiments chargés!", state="complete")
        
        return gdf
        
    except Exception as e:
        status.update(label=f"❌ Erreur: {str(e)}", state="error")
        st.error(f"Détails: {e}")
        return None

def create_shapefile_zip(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée un ZIP contenant le shapefile"""
    with tempfile.TemporaryDirectory() as temp_dir:
        shp_path = os.path.join(temp_dir, f"{base_name}.shp")
        
        # Limitation des noms de colonnes à 10 caractères pour shapefile
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
    """Crée un fichier GeoPackage (SQLite spatial)"""
    with tempfile.TemporaryDirectory() as temp_dir:
        gpkg_path = os.path.join(temp_dir, f"{base_name}.gpkg")
        gdf.to_file(gpkg_path, driver="GPKG", layer="buildings")
        
        with open(gpkg_path, 'rb') as f:
            return f.read()

def upload_to_google_drive(file_data, filename, mime_type):
    """Upload vers Google Drive (nécessite authentification OAuth)"""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        
        # Scopes pour Google Drive
        SCOPES = ['https://www.googleapis.com/auth/drive.file']
        
        # Authentification (nécessite credentials.json)
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        
        # Service Google Drive
        service = build('drive', 'v3', credentials=creds)
        
        # Upload du fichier
        file_metadata = {'name': filename}
        media = MediaIoBaseUpload(BytesIO(file_data), mimetype=mime_type, resumable=True)
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        return f"https://drive.google.com/file/d/{file.get('id')}/view"
        
    except Exception as e:
        return None

def main():
    st.title("🏢 Open Buildings Extractor Pro")
    st.markdown("Téléchargez les données de **Google-Microsoft Open Buildings** (2.5+ milliards de bâtiments)")
    
    # Info source
    st.info("📊 **Nouvelle source optimisée** : GeoParquet de Source Cooperative (VIDA) - Téléchargement 10-50x plus rapide!")
    
    # Sidebar - Paramètres
    with st.sidebar:
        st.header("⚙️ Paramètres")
        
        export_format = st.selectbox(
            "📦 Format d'export",
            ["GeoJSON", "Shapefile (ZIP)", "GeoPackage (GPKG)", "GeoParquet"],
            help="GeoJSON : universel\nShapefile : compatible SIG\nGeoPackage : SQLite spatial\nGeoParquet : format cloud-native"
        )
        
        upload_to_cloud = st.checkbox(
            "☁️ Upload vers Google Drive",
            value=False,
            help="Nécessite credentials.json et authentification OAuth"
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
        st.markdown("### 💡 Info")
        st.markdown("""
        - **Source** : VIDA (Google + Microsoft)
        - **Format source** : GeoParquet partitionné
        - **Couverture** : 92% des pays (185 partitions)
        - **Total** : 2.5+ milliards de bâtiments
        """)
    
    # Chargement des pays
    countries_gdf = load_countries()
    
    if countries_gdf is not None:
        st.sidebar.success(f"✅ {len(countries_gdf)} pays disponibles")
    
    regions_list = prepare_regions(countries_gdf)
    
    # Interface à onglets
    tab1, tab2 = st.tabs(["🌍 Sélection par Pays", "📐 Coordonnées (BBox)"])
    
    mode = None
    choice = ""
    n = s = e = w = 0.0
    
    with tab1:
        st.markdown("### Sélectionner un pays")
        source_name = st.selectbox(
            "Source des frontières :",
            ["Natural Earth (High Res 10m)", "World Bank (High Res)"],
            help="Natural Earth est recommandé"
        )
        choice = st.selectbox("Pays :", regions_list, key="country_select")
        if choice and choice != "":
            mode = "country"
            st.info(f"📍 Sélection : {choice}")
    
    with tab2:
        st.markdown("### Entrer des coordonnées manuelles")
        st.info("📍 Obtenez les coordonnées sur [bboxfinder.com](http://bboxfinder.com)")
        
        col1, col2 = st.columns(2)
        with col1:
            n = st.number_input("🔼 Nord (Lat Max)", value=0.0, format="%.6f", step=0.1, key="north")
            s = st.number_input("🔽 Sud (Lat Min)", value=0.0, format="%.6f", step=0.1, key="south")
        with col2:
            e = st.number_input("➡️ Est (Lon Max)", value=0.0, format="%.6f", step=0.1, key="east")
            w = st.number_input("⬅️ Ouest (Lon Min)", value=0.0, format="%.6f", step=0.1, key="west")
        
        if any([n != 0.0, s != 0.0, e != 0.0, w != 0.0]):
            if mode != "country":
                mode = "bbox"
                st.info(f"📍 BBox : N={n}, S={s}, E={e}, O={w}")

    # Bouton d'extraction
    if st.button("🚀 Extraire les données", type="primary", use_container_width=True):
        if not mode:
            st.warning("⚠️ Veuillez sélectionner un pays OU entrer des coordonnées")
            return
        
        try:
            geom = None
            name = ""
            iso_code = None
            
            # Mode Pays
            if mode == "country":
                st.info(f"🌍 Mode : Sélection par pays - {choice}")
                
                iso_code = choice.split('(')[-1].strip(')')
                
                url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
                if "World Bank" in source_name:
                    url = "https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip"
                
                with st.spinner("📥 Chargement des frontières..."):
                    full_gdf = fetch_and_extract_shapefile(url)
                
                if full_gdf is None:
                    st.error("❌ Impossible de charger le shapefile")
                    return
                
                iso_col = find_iso_column(full_gdf)
                
                if not iso_col:
                    st.error(f"❌ Aucune colonne ISO trouvée")
                    return
                
                target_gdf = full_gdf[full_gdf[iso_col] == iso_code]
                
                if target_gdf.empty:
                    st.error(f"❌ Code ISO '{iso_code}' non trouvé")
                    return
                
                geom = target_gdf.dissolve().iloc[0].geometry
                name = iso_code
                st.success(f"✅ Pays trouvé : {choice}")
            
            # Mode BBox
            elif mode == "bbox":
                if n <= s or e <= w:
                    st.error("❌ Coordonnées invalides")
                    return
                
                st.info(f"📐 Mode : BBox personnalisée")
                geom = box(w, s, e, n)
                name = f"bbox_{abs(hash(f'{n}{s}{e}{w}'))}"
                st.success("✅ Zone définie")
            
            # Extraction des données
            st.markdown("---")
            st.subheader("📥 Téléchargement des bâtiments")
            
            # Téléchargement avec DuckDB
            buildings_gdf = download_buildings_duckdb(geom, mode, iso_code)
            
            # Résultats
            if buildings_gdf is None or buildings_gdf.empty:
                st.warning("⚠️ Aucun bâtiment trouvé dans cette zone")
                st.info("💡 Cela peut signifier :\n- Zone sans données\n- Pays non couvert dans le dataset\n- Coordonnées incorrectes")
                st.info("🗺️ **Couverture** : Afrique, Asie du Sud/Sud-Est, Amérique Latine, Caraïbes")
            else:
                # Simplification optionnelle
                if simplify_geom and len(buildings_gdf) > 1000:
                    with st.spinner("🔧 Simplification des géométries..."):
                        buildings_gdf['geometry'] = buildings_gdf['geometry'].simplify(tolerance=tolerance)
                
                st.success(f"🎉 **{len(buildings_gdf):,} bâtiments** extraits !")
                
                # Statistiques
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("🏗️ Bâtiments", f"{len(buildings_gdf):,}")
                
                if 'area_in_meters' in buildings_gdf.columns:
                    total_area = buildings_gdf['area_in_meters'].sum() / 1e6
                    col2.metric("📐 Surface totale", f"{total_area:.2f} km²")
                    col3.metric("📏 Surface moyenne", f"{buildings_gdf['area_in_meters'].mean():.1f} m²")
                
                if 'bf_source' in buildings_gdf.columns:
                    sources = buildings_gdf['bf_source'].value_counts()
                    col4.metric("🔍 Sources", f"G:{sources.get('google', 0)} M:{sources.get('microsoft', 0)}")
                
                # Export selon le format choisi
                st.markdown("### 💾 Téléchargement")
                
                file_data = None
                filename = None
                mime_type = None
                
                if export_format == "GeoJSON":
                    geojson_buffer = BytesIO()
                    buildings_gdf.to_file(geojson_buffer, driver="GeoJSON")
                    file_data = geojson_buffer.getvalue()
                    filename = f"{name}_buildings.geojson"
                    mime_type = "application/geo+json"
                    
                elif export_format == "Shapefile (ZIP)":
                    with st.spinner("📦 Création du shapefile..."):
                        file_data = create_shapefile_zip(buildings_gdf, f"{name}_buildings")
                    filename = f"{name}_buildings.zip"
                    mime_type = "application/zip"
                    
                elif export_format == "GeoPackage (GPKG)":
                    with st.spinner("📦 Création du GeoPackage..."):
                        file_data = create_geopackage(buildings_gdf, f"{name}_buildings")
                    filename = f"{name}_buildings.gpkg"
                    mime_type = "application/geopackage+sqlite3"
                
                elif export_format == "GeoParquet":
                    parquet_buffer = BytesIO()
                    buildings_gdf.to_parquet(parquet_buffer)
                    file_data = parquet_buffer.getvalue()
                    filename = f"{name}_buildings.parquet"
                    mime_type = "application/octet-stream"
                
                # Upload vers Google Drive si activé
                if upload_to_cloud and file_data:
                    st.markdown("#### ☁️ Upload vers Google Drive")
                    if st.button("📤 Uploader vers Google Drive"):
                        with st.spinner("📤 Upload en cours..."):
                            drive_url = upload_to_google_drive(file_data, filename, mime_type)
                            if drive_url:
                                st.success(f"✅ Fichier uploadé avec succès!")
                                st.markdown(f"[📁 Voir sur Google Drive]({drive_url})")
                            else:
                                st.error("❌ Erreur d'upload. Vérifiez credentials.json et réessayez.")
                
                # Bouton de téléchargement local
                st.download_button(
                    label=f"📥 Télécharger {export_format}",
                    data=file_data,
                    file_name=filename,
                    mime=mime_type,
                    use_container_width=True
                )
                
                # Aperçu
                with st.expander("👁️ Aperçu des 10 premiers bâtiments"):
                    st.dataframe(buildings_gdf.head(10))
                
                # Statistiques détaillées
                with st.expander("📊 Statistiques détaillées"):
                    st.write(f"**Colonnes disponibles:** {', '.join(buildings_gdf.columns.tolist())}")
                    
                    if 'area_in_meters' in buildings_gdf.columns:
                        st.write(f"**Surface min:** {buildings_gdf['area_in_meters'].min():.2f} m²")
                        st.write(f"**Surface max:** {buildings_gdf['area_in_meters'].max():.2f} m²")
                        st.write(f"**Surface médiane:** {buildings_gdf['area_in_meters'].median():.2f} m²")
                    
                    if 'confidence' in buildings_gdf.columns:
                        valid_conf = buildings_gdf['confidence'].dropna()
                        if len(valid_conf) > 0:
                            st.write(f"**Confiance moyenne:** {valid_conf.mean():.2%}")
        
        except Exception as e:
            st.error(f"❌ Erreur système : {e}")
            import traceback
            with st.expander("🔍 Détails de l'erreur"):
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
