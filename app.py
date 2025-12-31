import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
import s2geometry as s2
import shapely
from shapely.geometry import box
import tensorflow as tf

# Configuration
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'polygons_s2_level_6_gzip_no_header')

@st.cache_data
def load_countries():
    # Lien RAW du GeoJSON
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/main/countries.geojson"
    try:
        gdf = gpd.read_file(url)
        # Nettoyage : On s'assure que les colonnes sont en majuscules pour la détection
        gdf.columns = [c.upper() for c in gdf.columns]
        return gdf
    except Exception as e:
        st.error(f"Erreur chargement GeoJSON : {e}")
        return None

@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        r = requests.get(url)
        with open(zip_path, 'wb') as f:
            f.write(r.content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    gdf = gpd.read_file(os.path.join(root, file))
                    gdf.columns = [c.upper() for c in gdf.columns] # Normalisation
                    return gdf
    return None

def prepare_regions(countries_gdf):
    if countries_gdf is None: return [""]
    
    # Chercher la colonne ISO (Priorité ISO_A3 puis ISO_A2)
    iso_col = next((c for c in ['ISO_A3', 'ISO3', 'ISO_A2', 'ISO'] if c in countries_gdf.columns), None)
    name_col = next((c for c in ['NAME', 'ADMIN', 'NAME_EN'] if c in countries_gdf.columns), None)
    
    if not iso_col or not name_col:
        return [""] + [f"Zone {i}" for i in range(len(countries_gdf))]
    
    # Créer la liste "ISO - NOM"
    regions = []
    for _, row in countries_gdf.iterrows():
        regions.append(f"{row[iso_col]} - {row[name_col]}")
    return [""] + sorted(regions)

# --- Correction S2 (Syntaxe universelle) ---
def get_s2_tokens(geometry) -> list:
    bounds = geometry.bounds # (minx, miny, maxx, maxy)
    # Création du rectangle S2 sans utiliser la fonction FromPointPair qui bugge
    rect = s2.S2LatLngRect(
        s2.S2LatLng.FromDegrees(bounds[1], bounds[0]), # Low (Sud, Ouest)
        s2.S2LatLng.FromDegrees(bounds[3], bounds[2])  # High (Nord, Est)
    )
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(1000)
    return [cell.ToToken() for cell in coverer.GetCovering(rect)]

# --- Interface ---
def main():
    st.title("🏢 Open Buildings Extractor")
    
    countries_gdf = load_countries()
    regions_list = prepare_regions(countries_gdf)
    
    tab1, tab2 = st.tabs(["🌍 Sélection par Pays", "📐 Coordonnées (BBox)"])
    
    with tab1:
        source_name = st.selectbox("Source :", ["Natural Earth (High Res 10m)", "World Bank (High Res)"])
        choice = st.selectbox("Pays :", regions_list)
        
    with tab2:
        st.info("Obtenez les coordonnées sur [bboxfinder.com](http://bboxfinder.com)")
        c1, c2, c3, c4 = st.columns(4)
        n = c1.number_input("Nord (Lat Max)", value=0.0, format="%.6f")
        s = c2.number_input("Sud (Lat Min)", value=0.0, format="%.6f")
        e = c3.number_input("Est (Lon Max)", value=0.0, format="%.6f")
        w = c4.number_input("Ouest (Lon Min)", value=0.0, format="%.6f")

    if st.button("🚀 Extraire les données"):
        try:
            # 1. Définir la zone cible
            if choice and not (n != 0 and s != 0):
                # Mode Pays
                iso_code = choice.split(' - ')[0]
                url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
                if "World Bank" in source_name:
                    url = "https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip"
                
                full_gdf = fetch_and_extract_shapefile(url)
                # On cherche dans toutes les colonnes ISO possibles du shapefile
                iso_col = next((c for c in ['ISO_A3', 'ISO_A2', 'ISO3', 'ADM0_A3'] if c in full_gdf.columns), None)
                target_gdf = full_gdf[full_gdf[iso_col] == iso_code]
                
                if target_gdf.empty:
                    st.error(f"Code {iso_code} non trouvé dans la source {source_name}. Essayez une autre source.")
                    return
                geom = target_gdf.dissolve().iloc[0].geometry
                name = iso_code
            else:
                # Mode BBox
                if n == s or e == w:
                    st.error("Veuillez entrer des coordonnées valides.")
                    return
                geom = box(w, s, e, n)
                name = "custom_area"

            # 2. Extraction S2
            tokens = get_s2_tokens(geom)
            st.write(f"Extraction de {len(tokens)} tuiles S2...")
            
            all_data = []
            progress = st.progress(0)
            
            for i, token in enumerate(tokens):
                csv_url = os.path.join(BUILDING_DOWNLOAD_PATH, f'{token}_buildings.csv.gz')
                try:
                    # Lecture directe via TensorFlow GFile
                    with tf.io.gfile.GFile(csv_url, 'rb') as gf:
                        df = pd.read_csv(gf, header=None, dtype=object)
                        # 0:lat, 1:lon, 2:WKT
                        gdf_chunk = gpd.GeoDataFrame(df, geometry=gpd.GeoSeries.from_wkt(df[2]), crs='EPSG:4326')
                        # Filtrage par la géométrie exacte
                        gdf_chunk = gdf_chunk[gdf_chunk.intersects(geom)]
                        if not gdf_chunk.empty:
                            all_data.append(gdf_chunk)
                except:
                    pass
                progress.progress((i + 1) / len(tokens))

            if not all_data:
                st.warning("Aucun bâtiment trouvé.")
            else:
                final_gdf = pd.concat(all_data)
                out_path = f"{name}_buildings.geojson"
                final_gdf.to_file(out_path, driver="GeoJSON")
                with open(out_path, "rb") as f:
                    st.download_button("💾 Télécharger GeoJSON", f, file_name=out_path)

        except Exception as e:
            st.error(f"Erreur système : {e}")

if __name__ == "__main__":
    main()
