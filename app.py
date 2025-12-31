import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
import s2geometry as s2
from shapely.geometry import box
import tensorflow as tf
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

# Configuration
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

# Constants
BUILDING_DOWNLOAD_PATH = 'gs://open-buildings-data/v3/polygons_s2_level_6_gzip_no_header'

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

def get_s2_tokens(geometry) -> list:
    """Génère les tokens S2 pour une géométrie donnée"""
    bounds = geometry.bounds
    
    rect = s2.S2LatLngRect(
        s2.S2LatLng.FromDegrees(bounds[1], bounds[0]),
        s2.S2LatLng.FromDegrees(bounds[3], bounds[2])
    )
    
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(1000)
    
    covering = coverer.GetCovering(rect)
    return [cell.ToToken() for cell in covering]

def find_iso_column(gdf):
    """Trouve la colonne ISO dans un GeoDataFrame"""
    iso_columns = ['ISO_A3', 'ISO3', 'ADM0_A3', 'WB_A3', 'ISO_A2', 'ISO3166-1-Alpha-3', 'ISO3166-1-Alpha-2']
    
    for col in gdf.columns:
        if col in iso_columns:
            return col
    return None

@st.cache_data(ttl=3600)
def download_single_tile(token: str, geom_wkt: str):
    """Télécharge une tuile S2 (avec cache de 1h)"""
    csv_url = os.path.join(BUILDING_DOWNLOAD_PATH, f'{token}_buildings.csv.gz')
    
    try:
        with tf.io.gfile.GFile(csv_url, 'rb') as gf:
            df = pd.read_csv(gf, header=None, compression='gzip')
            
            if len(df.columns) >= 3:
                from shapely import wkt
                geom_filter = wkt.loads(geom_wkt)
                
                gdf_chunk = gpd.GeoDataFrame(
                    df,
                    geometry=gpd.GeoSeries.from_wkt(df[2]),
                    crs='EPSG:4326'
                )
                
                gdf_chunk = gdf_chunk[gdf_chunk.intersects(geom_filter)]
                
                if not gdf_chunk.empty:
                    return gdf_chunk
    except:
        pass
    
    return None

def download_tiles_parallel(tokens: list, geom, max_workers: int = 10):
    """Télécharge les tuiles en parallèle"""
    geom_wkt = geom.wkt
    all_data = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    buildings_found = 0
    completed = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_token = {executor.submit(download_single_tile, token, geom_wkt): token 
                          for token in tokens}
        
        for future in as_completed(future_to_token):
            token = future_to_token[future]
            completed += 1
            
            try:
                result = future.result()
                if result is not None:
                    all_data.append(result)
                    buildings_found += len(result)
                    status_text.text(f"✅ {completed}/{len(tokens)} tuiles - {buildings_found:,} bâtiments trouvés")
            except Exception as e:
                pass
            
            progress_bar.progress(completed / len(tokens))
    
    status_text.empty()
    progress_bar.empty()
    
    return all_data

def create_shapefile_zip(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée un ZIP contenant le shapefile"""
    with tempfile.TemporaryDirectory() as temp_dir:
        shp_path = os.path.join(temp_dir, f"{base_name}.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        
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
    st.title("🏢 Open Buildings Extractor")
    st.markdown("Téléchargez les données de bâtiments depuis Google Open Buildings")
    
    # Sidebar - Paramètres
    with st.sidebar:
        st.header("⚙️ Paramètres")
        
        max_workers = st.slider(
            "Téléchargements parallèles",
            min_value=1,
            max_value=20,
            value=10,
            help="Plus de workers = plus rapide, mais plus de mémoire"
        )
        
        st.markdown("---")
        
        export_format = st.selectbox(
            "📦 Format d'export",
            ["GeoJSON", "Shapefile (ZIP)", "GeoPackage (GPKG)"],
            help="GeoJSON : universel\nShapefile : compatible SIG\nGeoPackage : SQLite spatial"
        )
        
        st.markdown("---")
        st.markdown("### 💡 Astuces")
        st.markdown("""
        - **Cache activé** : Les tuiles sont mises en cache 1h
        - **Téléchargement parallèle** : Jusqu'à 20x plus rapide
        - **Formats optimisés** : GPKG recommandé pour grandes zones
        """)
    
    # Chargement des pays
    countries_gdf = load_countries()
    
    if countries_gdf is not None:
        st.sidebar.success(f"✅ {len(countries_gdf)} pays chargés")
    
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
            
            # Mode Pays
            if mode == "country":
                st.info(f"🌍 Mode : Sélection par pays - {choice}")
                
                iso_code = choice.split('(')[-1].strip(')')
                
                url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
                if "World Bank" in source_name:
                    url = "https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip"
                
                with st.spinner("📥 Téléchargement du shapefile..."):
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
                name = f"custom_{abs(hash(f'{n}{s}{e}{w}'))}"
                st.success("✅ Zone définie")
            
            # Extraction des données
            st.markdown("---")
            st.subheader("📥 Téléchargement des données")
            
            tokens = get_s2_tokens(geom)
            st.info(f"🔢 **{len(tokens)}** tuiles S2 à traiter (téléchargement parallèle : {max_workers} workers)")
            
            # Téléchargement parallèle
            all_data = download_tiles_parallel(tokens, geom, max_workers)
            
            # Résultats
            if not all_data:
                st.warning("⚠️ Aucun bâtiment trouvé dans cette zone")
                st.info("Cela peut signifier :\n- Zone vide\n- Données non disponibles\n- Coordonnées incorrectes")
            else:
                final_gdf = pd.concat(all_data, ignore_index=True)
                
                # Simplification de la géométrie pour alléger
                if len(final_gdf) > 10000:
                    with st.spinner("🔧 Simplification des géométries..."):
                        final_gdf['geometry'] = final_gdf['geometry'].simplify(tolerance=0.00001)
                
                st.success(f"🎉 **{len(final_gdf):,} bâtiments** extraits !")
                
                # Statistiques
                col1, col2, col3 = st.columns(3)
                col1.metric("🏗️ Bâtiments", f"{len(final_gdf):,}")
                col2.metric("🗂️ Tuiles", len(tokens))
                col3.metric("✅ Avec données", len(all_data))
                
                # Export selon le format choisi
                st.markdown("### 💾 Téléchargement")
                
                if export_format == "GeoJSON":
                    geojson_buffer = BytesIO()
                    final_gdf.to_file(geojson_buffer, driver="GeoJSON")
                    
                    st.download_button(
                        label="📥 Télécharger GeoJSON",
                        data=geojson_buffer.getvalue(),
                        file_name=f"{name}_buildings.geojson",
                        mime="application/geo+json",
                        use_container_width=True
                    )
                
                elif export_format == "Shapefile (ZIP)":
                    with st.spinner("📦 Création du shapefile..."):
                        shp_zip = create_shapefile_zip(final_gdf, f"{name}_buildings")
                    
                    st.download_button(
                        label="📥 Télécharger Shapefile (ZIP)",
                        data=shp_zip,
                        file_name=f"{name}_buildings.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                
                elif export_format == "GeoPackage (GPKG)":
                    with st.spinner("📦 Création du GeoPackage..."):
                        gpkg_data = create_geopackage(final_gdf, f"{name}_buildings")
                    
                    st.download_button(
                        label="📥 Télécharger GeoPackage",
                        data=gpkg_data,
                        file_name=f"{name}_buildings.gpkg",
                        mime="application/geopackage+sqlite3",
                        use_container_width=True
                    )
                
                # Aperçu
                with st.expander("👁️ Aperçu des données"):
                    st.dataframe(final_gdf.head(10))
                    
                    # Info sur la taille
                    size_mb = len(final_gdf) * 0.001  # Estimation
                    st.caption(f"📊 Taille estimée : ~{size_mb:.1f} MB")
        
        except Exception as e:
            st.error(f"❌ Erreur système : {e}")
            import traceback
            with st.expander("🔍 Détails"):
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
