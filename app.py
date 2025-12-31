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
import tensorflow as tf
import tqdm

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'polygons_s2_level_6_gzip_no_header')

# 1. Load countries.geojson (Cached)
@st.cache_data
def load_countries():
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson"
    return gpd.read_file(url)

# 2. Cache the download of heavy shapefiles
@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    """Télécharge, extrait et charge le shapefile en cache."""
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        response = requests.get(url)
        with open(zip_path, 'wb') as f:
            f.write(response.content)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # Chercher le fichier .shp
        shapefile_path = None
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    shapefile_path = os.path.join(root, file)
                    break
            if shapefile_path: break
            
        if not shapefile_path:
            raise FileNotFoundError("Aucun fichier .shp trouvé dans l'archive.")
            
        return gpd.read_file(shapefile_path)

# Prepare the list of regions (Fixed for Case Sensitivity)
def prepare_regions(countries_gdf):
    # Trouver les colonnes sans se soucier de la casse
    cols = {c.upper(): c for c in countries_gdf.columns}
    name_col = cols.get('NAME')
    iso_col = cols.get('ISO_A3')

    if not name_col or not iso_col:
        return [""] + [f"Index {i}" for i in range(len(countries_gdf))]
    
    regions = [""] + [f"{row[iso_col]} ({row[name_col]})" for _, row in countries_gdf.iterrows()]
    return regions

# Get filename and region dataframe
def get_filename_and_region_dataframe(
    region_border_source: str, region: str, your_own_wkt_polygon: str
) -> Tuple[str, gpd.GeoDataFrame]:
    
    if your_own_wkt_polygon:
        filename = 'open_buildings_v3_polygons_custom'
        region_df = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt([your_own_wkt_polygon]),
            crs='EPSG:4326'
        )
        if not isinstance(region_df.iloc[0].geometry, (shapely.geometry.Polygon, shapely.geometry.MultiPolygon)):
            raise ValueError("`your_own_wkt_polygon` must be a POLYGON or MULTIPOLYGON.")
        return filename, region_df

    if not region:
        raise ValueError('Please select a region or set your_own_wkt_polygon.')

    # Mapping sources
    sources = {
        'Natural Earth (Low Res 110m)': ('https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip', 'ne_110m'),
        'Natural Earth (High Res 10m)': ('https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip', 'ne_10m'),
        'World Bank (High Res 10m)': ('https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip', 'wb_10m')
    }
    
    url, source_name = sources[region_border_source]
    
    # Utilisation de la fonction cachée
    full_gdf = fetch_and_extract_shapefile(url)
    
    region_iso_a3 = region.split(' ')[0]
    filename = f'open_buildings_v3_polygons_{source_name}_{region_iso_a3}'
    
    # Filtrage (Case insensitive pour ISO_A3)
    iso_col = next(c for c in full_gdf.columns if c.upper() == 'ISO_A3')
    region_df = full_gdf[full_gdf[iso_col] == region_iso_a3].dissolve(by=iso_col)[['geometry']]
    
    return filename, region_df

# S2 Geometry helper functions
def get_bounding_box_s2_covering_tokens(region_geometry) -> List[str]:
    region_bounds = region_geometry.bounds
    s2_lat_lng_rect = s2.S2LatLngRect_FromPointPair(
        s2.S2LatLng_FromDegrees(region_bounds[1], region_bounds[0]),
        s2.S2LatLng_FromDegrees(region_bounds[3], region_bounds[2])
    )
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(1000000)
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
            if prepared_region_geometry.covers(s2_cell_geometry):
                with tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.csv.gz') as tmp_f:
                    tmp_f.write(gf.read())
                    return tmp_f.name

            # Partial cover: filter rows
            csv_chunks = pd.read_csv(gf, chunksize=2000000, dtype=object, compression='gzip', header=None)
            tmp_f = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.csv.gz')
            
            for csv_chunk in csv_chunks:
                # Assuming index 0 is lat, index 1 is lon
                points = gpd.GeoDataFrame(
                    geometry=gpd.points_from_xy(csv_chunk[1], csv_chunk[0]),
                    crs='EPSG:4326'
                )
                points = gpd.sjoin(points, region_df, predicate='within')
                csv_chunk = csv_chunk.iloc[points.index]
                csv_chunk.to_csv(tmp_f.name, mode='ab', index=False, header=False, compression='gzip')
            return tmp_f.name
    except Exception:
        return None

# Main App
def main():
    st.set_page_config(page_title="Open Buildings Downloader", layout="wide")
    st.title("🏢 Open Buildings Data Downloader")

    countries_gdf = load_countries()
    regions = prepare_regions(countries_gdf)

    col1, col2 = st.columns(2)
    with col1:
        region_border_source = st.selectbox(
            "Select Border Source:",
            ["Natural Earth (Low Res 110m)", "Natural Earth (High Res 10m)", "World Bank (High Res 10m)"]
        )
        region = st.selectbox("Region", regions)
    
    with col2:
        output_format = st.selectbox("Output Format:", ["GeoJSON", "Shapefile"])
        your_own_wkt_polygon = st.text_area("Or specify WKT Polygon (EPSG:4326):", "")

    if st.button("🚀 Process & Download Data"):
        try:
            with st.status("Processing...", expanded=True) as status:
                filename, region_df = get_filename_and_region_dataframe(
                    region_border_source, region, your_own_wkt_polygon
                )

                st.write(f"Calculating coverage for {filename}...")
                s2_tokens = get_bounding_box_s2_covering_tokens(region_df.iloc[0].geometry)
                
                temp_dir = tempfile.mkdtemp()
                all_dfs = []

                progress_bar = st.progress(0)
                for i, s2_token in enumerate(s2_tokens):
                    fname = download_s2_token(s2_token, region_df)
                    if fname:
                        # On lit le CSV filtré et on le transforme en GDF
                        chunk_df = pd.read_csv(fname, header=None, dtype=object)
                        # On suppose 0: lat, 1: lon, 2: geometry_wkt
                        gdf_chunk = gpd.GeoDataFrame(
                            chunk_df, 
                            geometry=gpd.GeoSeries.from_wkt(chunk_df[2]),
                            crs='EPSG:4326'
                        )
                        all_dfs.append(gdf_chunk)
                    progress_bar.progress((i + 1) / len(s2_tokens))

                if not all_dfs:
                    st.error("No data found for this area.")
                    return

                final_gdf = pd.concat(all_dfs, ignore_index=True)
                output_path = os.path.join(temp_dir, f"{filename}.{output_format.lower()}")

                if output_format == "GeoJSON":
                    final_gdf.to_file(output_path, driver="GeoJSON")
                else:
                    # Shapefile needs zipping
                    shp_dir = os.path.join(temp_dir, "shp_out")
                    os.makedirs(shp_dir)
                    final_gdf.to_file(os.path.join(shp_dir, f"{filename}.shp"))
                    zip_path = os.path.join(temp_dir, f"{filename}.zip")
                    with zipfile.ZipFile(zip_path, "w") as zipf:
                        for f in os.listdir(shp_dir):
                            zipf.write(os.path.join(shp_dir, f), f)
                    output_path = zip_path

                status.update(label="✅ Ready to download!", state="complete")

            with open(output_path, "rb") as f:
                st.download_button(
                    label="💾 Download File",
                    data=f,
                    file_name=os.path.basename(output_path),
                    mime="application/octet-stream"
                )

        except Exception as e:
            st.error(f"Error: {e}")

if __name__ == "__main__":
    main()
