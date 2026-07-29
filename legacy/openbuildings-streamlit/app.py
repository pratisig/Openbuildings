import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
import streamlit as st
from shapely.geometry import box
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

def download_buildings_by_country(iso_code, bbox=None):
    """Télécharge les bâtiments pour un pays via GeoParquet"""
    
    status = st.status("🔄 Téléchargement en cours...", expanded=True)
    
    try:
        # URL du GeoParquet pour le pays
        parquet_url = f"{GEOPARQUET_BASE}/country_iso={iso_code}/{iso_code}.parquet"
        
        status.write(f"🌍 Téléchargement des bâtiments pour : {iso_code}")
        status.write(f"📂 URL : {parquet_url}")
        
        start_time = time.time()
        
        # Lecture du GeoParquet
        status.write("⏳ Lecture du fichier GeoParquet...")
        gdf = gpd.read_parquet(parquet_url)
        
        download_time = time.time() - start_time
        status.write(f"✅ {len(gdf):,} bâtiments téléchargés en {download_time:.1f}s")
        
        # Filtrage par bbox si fourni
        if bbox is not None:
            status.write("🔍 Filtrage par zone géographique...")
            initial_count = len(gdf)
            gdf = gdf[gdf.intersects(bbox)]
            status.write(f"📊 {len(gdf):,} bâtiments dans la zone (sur {initial_count:,})")
        
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
    """Crée un fichier GeoPackage (SQLite spatial)"""
    with tempfile.TemporaryDirectory() as temp_dir:
        gpkg_path = os.path.join(temp_dir, f"{base_name}.gpkg")
        gdf.to_file(gpkg_path, driver="GPKG", layer="buildings")
        
        with open(gpkg_path, 'rb') as f:
            return f.read()

def main():
    st.title("🏢 Open Buildings Downloader")
    st.markdown("Téléchargez les données **Google-Microsoft Open Buildings** (2.5+ milliards de bâtiments)")
    
    # Info source
    st.info("📊 **Source** : VIDA Google-Microsoft Open Buildings via Source Cooperative | Format : GeoParquet")
    
    # Sidebar - Paramètres
    with st.sidebar:
        st.header("⚙️ Paramètres")
        
        export_format = st.selectbox(
            "📦 Format d'export",
            ["GeoJSON", "Shapefile (ZIP)", "GeoPackage (GPKG)", "GeoParquet", "CSV"],
            help="GeoJSON : universel\nShapefile : compatible SIG\nGeoPackage : recommandé\nGeoParquet : format cloud-native"
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
    
    # Chargement des pays
    countries_gdf = load_countries()
    
    if countries_gdf is not None:
        st.sidebar.success(f"✅ {len(countries_gdf)} pays disponibles")
    
    regions_list = prepare_regions(countries_gdf)
    
    # Interface simplifiée (un seul onglet : pays uniquement)
    st.markdown("### 🌍 Sélectionner un pays")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        choice = st.selectbox("Pays :", regions_list, key="country_select")
    
    with col2:
        use_bbox = st.checkbox("Filtrer par zone", help="Extraire uniquement une partie du pays")
    
    # BBox optionnel
    bbox_geom = None
    if use_bbox and choice and choice != "":
        st.markdown("#### 📐 Zone à extraire (optionnel)")
        st.caption("Obtenez les coordonnées sur [bboxfinder.com](http://bboxfinder.com)")
        
        col1, col2, col3, col4 = st.columns(4)
        w = col1.number_input("⬅️ Ouest (Lon)", value=0.0, format="%.6f", key="west")
        s = col2.number_input("🔽 Sud (Lat)", value=0.0, format="%.6f", key="south")
        e = col3.number_input("➡️ Est (Lon)", value=0.0, format="%.6f", key="east")
        n = col4.number_input("🔼 Nord (Lat)", value=0.0, format="%.6f", key="north")
        
        if all([w != 0.0, s != 0.0, e != 0.0, n != 0.0]):
            if n > s and e > w:
                bbox_geom = box(w, s, e, n)
                st.success(f"✅ Zone définie : ({w:.4f}, {s:.4f}, {e:.4f}, {n:.4f})")
            else:
                st.error("❌ Coordonnées invalides : Nord > Sud et Est > Ouest")

    # Bouton d'extraction
    if st.button("🚀 Télécharger les bâtiments", type="primary", use_container_width=True):
        if not choice or choice == "":
            st.warning("⚠️ Veuillez sélectionner un pays")
            return
        
        try:
            # Extraire le code ISO
            iso_code = choice.split('(')[-1].strip(')')
            name = iso_code
            
            st.markdown("---")
            st.subheader(f"📥 Téléchargement pour {choice}")
            
            # Téléchargement
            buildings_gdf = download_buildings_by_country(iso_code, bbox_geom)
            
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
                    if export_format == "GeoJSON":
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
