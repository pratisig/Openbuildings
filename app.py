import os
import tempfile
import zipfile
import functools
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from typing import List, Optional, Tuple
import s2geometry as s2
import shapely
from shapely.geometry import box
import tensorflow as tf
import tqdm

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'polygons_s2_level_6_gzip_no_header')

@st.cache_data
def load_countries():
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson"
    gdf = gpd.read_file(url)
    return gdf

@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        response = requests.get(url)
        with open(zip_path, 'wb') as f:
            f.write(response.content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        shapefile_path = None
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    shapefile_path = os.path.join(root, file)
                    break
            if shapefile_path: break
        return gpd.read_file(shapefile_path)

def prepare_regions(countries_gdf):
    # Liste des noms de colonnes possibles pour l'ISO et le Nom
    iso_possibilities = ['ISO_A3', 'iso_a3', 'ISO3', 'ADM0_A3', 'iso3']
    name_possibilities = ['NAME', 'name', 'ADMIN', 'admin', 'NAME_EN']
    
    # Détection dynamique
    iso_col = next((c for c in countries_gdf.columns if c in iso_possibilities), None)
    name_col = next((c for c in countries_gdf.columns if c in name_possibilities), None)

    if not iso_col or not name_col:
        # Si on ne trouve pas, on essaye de deviner ou on utilise des index
        return [""] + [f"ID_{i}" for i in range(len(countries_gdf))]
    
    # Tri par nom pour faciliter la recherche
    sorted_gdf = countries_gdf.sort_values(by=name_col)
    regions = [""] + [f"{row[iso_col]} ({row[name_col]})" for _, row in sorted_gdf.iterrows()]
    return regions

def get_filename_and_region_dataframe(
    region_border_source: str, region: str, bbox_coords: Optional[dict]
) -> Tuple[str, gpd.GeoDataFrame]:
    
    # Cas 1 : Utilisation du Bounding Box
    if bbox_coords:
        filename = 'open_buildings_custom_bbox'
        # box(minx, miny, maxx, maxy) -> (West, South, East, North)
        polygon = box(bbox_coords['west'], bbox_coords['south'], bbox_coords['east'], bbox_coords['north'])
        region_df = gpd.GeoDataFrame(geometry=[polygon], crs='EPSG:4326')
        return filename, region_df

    # Cas 2 : Sélection par pays
    if not region:
        raise ValueError('Veuillez sélectionner un pays ou entrer des coordonnées BBox.')

    sources = {
        'Natural Earth (Low Res 110m)': ('https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip', 'ne_110m'),
        'Natural Earth (High Res 10m)': ('https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip', 'ne_10m'),
        'World Bank (High Res 10m)': ('https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip', 'wb_10m')
    }
    
    url, source_name = sources[region_border_source]
    full_gdf = fetch_and_extract_shapefile(url)
    
    region_iso_a3 = region.split(' ')[0]
    filename = f'open_buildings_v3_{source_name}_{region_iso_a3}'
    
    # Recherche de la colonne ISO dans le shapefile téléchargé
    iso_col = next((c for c in full_gdf.columns if c.upper() in ['ISO_A3', 'ISO3', 'ADM0_A3']), None)
    if not iso_col:
        raise ValueError("Impossible de trouver la colonne ISO dans le fichier source.")
        
    region_df = full_gdf[full_gdf[iso_col] == region_iso_a3].dissolve(by=iso_col)[['geometry']]
    
    if region_df.empty:
        raise ValueError(f"Aucune géométrie trouvée pour l'ISO {region_iso_a3}")
        
    return filename, region_df

# --- S2 & Download Logic (Inchangé mais propre) ---

def get_bounding_box_s2_covering_tokens(region_geometry) -> List[str]:
    region_bounds = region_geometry.bounds
    s2_lat_lng_rect = s2.S2LatLngRect_FromPointPair(
        s2.S2LatLng_FromDegrees(region_bounds[1], region_bounds[0]),
        s2.S2LatLng_FromDegrees(region_bounds[3], region_bounds[2])
    )
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(1000)
    return [cell.ToToken() for cell in coverer.GetCovering(s2_lat_lng_rect)]

def s2_token_to_shapely_polygon(s2_token: str) -> shapely.geometry.polygon.Polygon:
    s2_cell = s2.S2Cell(s2.S2CellId_FromToken(s2_token, len(s2_token)))
    coords = []
    for i in range(4):
        s2_lat_lng = s2.S2LatLng(s2_cell.GetVertex(i))
        coords.append((s2_lat_lng.lng().degrees(), s2_lat_lng.lat().degrees()))
    return shapely.geometry.Polygon(coords)

def download_s2_token(s2_token: str, region_df: gpd.GeoDataFrame) -> Optional[str]:
    s2_cell_geometry = s2_token_to_shapely_polygon(s2_token)
    region_geometry = region_df.iloc[0].geometry
    prepared_region_geometry = shapely.prepared.prep(region_geometry)

    if not prepared_region_geometry.intersects(s2_cell_geometry):
        return None

    try:
        path = os.path.join(BUILDING_DOWNLOAD_PATH, f'{s2_token}_buildings.csv.gz')
        with tf.io.gfile.GFile(path, 'rb') as gf:
            # On stocke temporairement
            tmp_f = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.csv.gz')
            tmp_f.write(gf.read())
            tmp_f.close()
            return tmp_f.name
    except:
        return None

# --- UI Interface ---

def main():
    st.set_page_config(page_title="Open Buildings Downloader", layout="wide")
    st.title("🏢 Open Buildings Data Downloader")

    countries_gdf = load_countries()
    regions = prepare_regions(countries_gdf)

    tab1, tab2 = st.tabs(["🌍 Sélection par Pays", "📐 Sélection par Bounding Box"])

    with tab1:
        col_a, col_b = st.columns(2)
        with col_a:
            region_border_source = st.selectbox(
                "Source des frontières :",
                ["Natural Earth (Low Res 110m)", "Natural Earth (High Res 10m)", "World Bank (High Res 10m)"]
            )
        with col_b:
            selected_region = st.selectbox("Choisir un pays :", regions)

    with tab2:
        st.info("Utilisez [bboxfinder.com](http://bboxfinder.com) pour obtenir les coordonnées. Copiez les valeurs en bas de l'écran (format Decimal).")
        col_n, col_s, col_e, col_w = st.columns(4)
        with col_n: n = st.number_input("Nord (Max Lat)", value=0.0, format="%.6f")
        with col_s: s = st.number_input("Sud (Min Lat)", value=0.0, format="%.6f")
        with col_e: e = st.number_input("Est (Max Lon)", value=0.0, format="%.6f")
        with col_w: w = st.number_input("Ouest (Min Lon)", value=0.0, format="%.6f")
        
        bbox_data = None
        if n != 0 or s != 0: # Simple vérification que l'utilisateur a rempli les champs
            bbox_data = {'north': n, 'south': s, 'east': e, 'west': w}

    output_format = st.radio("Format de sortie :", ["GeoJSON", "Shapefile"], horizontal=True)

    if st.button("🚀 Lancer l'extraction"):
        try:
            with st.status("Traitement en cours...", expanded=True) as status:
                # Si on est dans l'onglet pays, on ignore le bbox_data
                current_bbox = bbox_data if (n != 0 and tab2) else None
                
                filename, region_df = get_filename_and_region_dataframe(
                    region_border_source, selected_region, current_bbox
                )

                st.write(f"Analyse de la zone : {filename}")
                s2_tokens = get_bounding_box_s2_covering_tokens(region_df.iloc[0].geometry)
                
                all_dfs = []
                progress_bar = st.progress(0)
                
                for idx, token in enumerate(s2_tokens):
                    fname = download_s2_token(token, region_df)
                    if fname:
                        chunk_df = pd.read_csv(fname, header=None, dtype=object)
                        # Création du GeoDataFrame (0:lat, 1:lon, 2:wkt)
                        gdf_chunk = gpd.GeoDataFrame(
                            chunk_df, 
                            geometry=gpd.GeoSeries.from_wkt(chunk_df[2]),
                            crs='EPSG:4326'
                        )
                        # Filtrage spatial pour ne garder que ce qui est DANS la zone
                        gdf_chunk = gdf_chunk[gdf_chunk.geometry.intersects(region_df.iloc[0].geometry)]
                        all_dfs.append(gdf_chunk)
                    progress_bar.progress((idx + 1) / len(s2_tokens))

                if not all_dfs:
                    st.error("Aucune donnée trouvée pour cette zone.")
                    return

                final_gdf = pd.concat(all_dfs, ignore_index=True)
                temp_dir = tempfile.mkdtemp()
                output_path = os.path.join(temp_dir, f"{filename}.{output_format.lower()}")

                if output_format == "GeoJSON":
                    final_gdf.to_file(output_path, driver="GeoJSON")
                else:
                    shp_dir = os.path.join(temp_dir, "shp_out")
                    os.makedirs(shp_dir)
                    final_gdf.to_file(os.path.join(shp_dir, f"{filename}.shp"))
                    zip_path = os.path.join(temp_dir, f"{filename}.zip")
                    with zipfile.ZipFile(zip_path, "w") as zipf:
                        for f in os.listdir(shp_dir):
                            zipf.write(os.path.join(shp_dir, f), f)
                    output_path = zip_path

                status.update(label="✅ Traitement terminé !", state="complete")

            with open(output_path, "rb") as f:
                st.download_button(
                    label="💾 Télécharger les données",
                    data=f,
                    file_name=os.path.basename(output_path),
                    mime="application/octet-stream"
                )

        except Exception as e:
            st.error(f"Erreur : {e}")

if __name__ == "__main__":
    main()
