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

# Configuration de la page
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'polygons_s2_level_6_gzip_no_header')

@st.cache_data
def load_countries():
    # Utilisation du lien raw pour éviter les erreurs de lecture HTML
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/main/countries.geojson"
    try:
        gdf = gpd.read_file(url)
        return gdf
    except Exception as e:
        st.error(f"Erreur lors du chargement du GeoJSON : {e}")
        return None

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
    if countries_gdf is None:
        return [""]

    # Détection intelligente des colonnes ISO et NAME
    iso_col = None
    name_col = None

    for col in countries_gdf.columns:
        c_up = col.upper()
        if "ISO" in c_up and ("A3" in c_up or "3" in c_up):
            iso_col = col
        if "NAME" in c_up or "ADMIN" in c_up:
            name_col = col

    # Si on ne trouve pas les colonnes spécifiques, on prend les premières colonnes textuelles
    if not iso_col:
        iso_col = countries_gdf.select_dtypes(include=['object']).columns[0]
    if not name_col:
        name_col = countries_gdf.select_dtypes(include=['object']).columns[1]

    # Construction de la liste "ISO (NOM)"
    regions = []
    for _, row in countries_gdf.iterrows():
        iso = str(row[iso_col]).strip()
        name = str(row[name_col]).strip()
        if iso and name and iso != "None":
            regions.append(f"{iso} ({name})")
    
    return [""] + sorted(regions)

def get_filename_and_region_dataframe(
    region_border_source: str, region: str, bbox_coords: Optional[dict]
) -> Tuple[str, gpd.GeoDataFrame]:
    
    # Cas 1 : Bounding Box (Prioritaire si rempli)
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
    
    # Trouver dynamiquement la colonne ISO dans le shapefile téléchargé
    iso_col = next((c for c in full_gdf.columns if "ISO" in c.upper() or "ADM0_A3" in c.upper()), full_gdf.columns[0])
    
    region_df = full_gdf[full_gdf[iso_col].astype(str) == region_iso_a3].dissolve()[['geometry']]
    
    if region_df.empty:
        raise ValueError(f"Aucune géométrie trouvée pour le code ISO : {region_iso_a3}")
        
    return filename, region_df

# --- Fonctions S2 ---

def get_bounding_box_s2_covering_tokens(region_geometry) -> List[str]:
    region_bounds = region_geometry.bounds
    s2_lat_lng_rect = s2.S2LatLngRect_FromPointPair(
        s2.S2LatLng_FromDegrees(region_bounds[1], region_bounds[0]),
        s2.S2LatLng_FromDegrees(region_bounds[3], region_bounds[2])
    )
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(2000)
    return [cell.ToToken() for cell in coverer.GetCovering(s2_lat_lng_rect)]

def s2_token_to_shapely_polygon(s2_token: str) -> shapely.geometry.polygon.Polygon:
    s2_cell = s2.S2Cell(s2.S2CellId_FromToken(s2_token, len(s2_token)))
    coords = []
    for i in range(4):
        s2_lat_lng = s2.S2LatLng(s2_cell.GetVertex(i))
        coords.append((s2_lat_lng.lng().degrees(), s2_lat_lng.lat().degrees()))
    return shapely.geometry.Polygon(coords)

def download_s2_token(s2_token: str) -> Optional[str]:
    try:
        path = os.path.join(BUILDING_DOWNLOAD_PATH, f'{s2_token}_buildings.csv.gz')
        with tf.io.gfile.GFile(path, 'rb') as gf:
            tmp_f = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.csv.gz')
            tmp_f.write(gf.read())
            tmp_f.close()
            return tmp_f.name
    except:
        return None

# --- UI Principal ---

def main():
    st.title("🏢 Open Buildings Data Downloader")
    st.markdown("---")

    countries_gdf = load_countries()
    regions_list = prepare_regions(countries_gdf)

    tab1, tab2 = st.tabs(["🌍 Par Pays", "📐 Par Bounding Box"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            source = st.selectbox("Source des frontières :", 
                                ["Natural Earth (High Res 10m)", "Natural Earth (Low Res 110m)", "World Bank (High Res 10m)"])
        with c2:
            selection = st.selectbox("Sélectionner le pays :", regions_list)

    with tab2:
        st.write("Indiquez les coordonnées limites (WGS84) :")
        st.caption("Astuce : Allez sur [bboxfinder.com](http://bboxfinder.com), tracez votre zone et copiez les coordonnées.")
        
        col_n, col_s, col_e, col_w = st.columns(4)
        n = col_n.number_input("Nord (Latitude Max)", value=0.0, format="%.6f")
        s = col_s.number_input("Sud (Latitude Min)", value=0.0, format="%.6f")
        e = col_e.number_input("Est (Longitude Max)", value=0.0, format="%.6f")
        w = col_w.number_input("Ouest (Longitude Min)", value=0.0, format="%.6f")
        
        bbox = None
        if n != 0 or s != 0:
            bbox = {'north': n, 'south': s, 'east': e, 'west': w}

    output_fmt = st.radio("Format de sortie :", ["GeoJSON", "Shapefile"], horizontal=True)

    if st.button("🚀 Extraire les données"):
        try:
            # On vérifie quel onglet est actif (si bbox est rempli dans Tab 2)
            active_bbox = bbox if (n != 0 and s != 0) else None
            
            with st.status("Initialisation...", expanded=True) as status:
                filename, region_df = get_filename_and_region_dataframe(source, selection, active_bbox)
                
                st.write(f"Calcul des tuiles S2 pour la zone...")
                target_geom = region_df.iloc[0].geometry
                tokens = get_bounding_box_s2_covering_tokens(target_geom)
                
                all_chunks = []
                pbar = st.progress(0)
                
                for i, t in enumerate(tokens):
                    f_tmp = download_s2_token(t)
                    if f_tmp:
                        # Lecture du CSV Google (0:lat, 1:lon, 2:WKT_polygone)
                        df = pd.read_csv(f_tmp, header=None, dtype=object)
                        gdf_chunk = gpd.GeoDataFrame(
                            df, 
                            geometry=gpd.GeoSeries.from_wkt(df[2]),
                            crs='EPSG:4326'
                        )
                        # Filtrage spatial strict pour ne pas déborder de la BBox/Pays
                        gdf_chunk = gdf_chunk[gdf_chunk.geometry.intersects(target_geom)]
                        if not gdf_chunk.empty:
                            all_chunks.append(gdf_chunk)
                    pbar.progress((i + 1) / len(tokens))

                if not all_chunks:
                    st.warning("Aucun bâtiment trouvé dans cette zone.")
                    return

                final_gdf = pd.concat(all_chunks, ignore_index=True)
                
                # Export
                temp_dir = tempfile.mkdtemp()
                out_file = os.path.join(temp_dir, f"{filename}.{output_fmt.lower()}")
                
                if output_fmt == "GeoJSON":
                    final_gdf.to_file(out_file, driver="GeoJSON")
                else:
                    shp_path = os.path.join(temp_dir, "export_shp")
                    os.makedirs(shp_path)
                    final_gdf.to_file(os.path.join(shp_path, f"{filename}.shp"))
                    zip_out = os.path.join(temp_dir, f"{filename}.zip")
                    with zipfile.ZipFile(zip_out, 'w') as z:
                        for f in os.listdir(shp_path):
                            z.write(os.path.join(shp_path, f), f)
                    out_file = zip_out

                status.update(label="✅ Données prêtes !", state="complete")

            with open(out_file, "rb") as f:
                st.download_button("💾 Télécharger le fichier", f, file_name=os.path.basename(out_file))

        except Exception as e:
            st.error(f"Erreur : {e}")

if __name__ == "__main__":
    main()
