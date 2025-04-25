import os
import tempfile
import zipfile
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

# Load countries.geojson
@st.cache_data
def load_countries():
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson"
    return gpd.read_file(url)

# Prepare the list of regions
def prepare_regions(countries_gdf):
    regions = [""] + [f"{row.ISO_A3} ({row.NAME})" for _, row in countries_gdf.iterrows()]
    return regions

# Get filename and region dataframe
def get_filename_and_region_dataframe(
    region_border_source: str, region: str, your_own_wkt_polygon: str
) -> Tuple[str, gpd.GeoDataFrame]:
    """Returns output filename and a GeoDataFrame with one region row."""
    if your_own_wkt_polygon:
        filename = f'open_buildings_v3_polygons_your_own_wkt_polygon'
        region_df = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt([your_own_wkt_polygon]),
            crs='EPSG:4326'
        )
        if not isinstance(region_df.iloc[0].geometry, (shapely.geometry.Polygon, shapely.geometry.MultiPolygon)):
            raise ValueError("`your_own_wkt_polygon` must be a POLYGON or MULTIPOLYGON.")
        st.write(f'Preparing your_own_wkt_polygon.')
        return filename, region_df

    if not region:
        raise ValueError('Please select a region or set your_own_wkt_polygon.')

    # Download the shapefile based on the selected border source
    if region_border_source == 'Natural Earth (Low Res 110m)':
        url = 'https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip'
        source_name = 'ne_110m'
    elif region_border_source == 'Natural Earth (High Res 10m)':
        url = 'https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip'
        source_name = 'ne_10m'
    elif region_border_source == 'World Bank (High Res 10m)':
        url = 'https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip'
        source_name = 'wb_10m'

    # Download and extract the shapefile
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        response = requests.get(url)
        with open(zip_path, 'wb') as f:
            f.write(response.content)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # Find the shapefile path
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    shapefile_path = os.path.join(root, file)
                    break

        region_iso_a3 = region.split(' ')[0]
        filename = f'open_buildings_v3_polygons_{source_name}_{region_iso_a3}'
        region_df = gpd.read_file(shapefile_path).query(
            f'ISO_A3 == "{region_iso_a3}"').dissolve(by='ISO_A3')[['geometry']]
        st.write(f'Preparing {region} from {region_border_source}.')
        return filename, region_df

# Get bounding box S2 covering tokens
def get_bounding_box_s2_covering_tokens(
    region_geometry: shapely.geometry.base.BaseGeometry
) -> List[str]:
    region_bounds = region_geometry.bounds
    s2_lat_lng_rect = s2.S2LatLngRect_FromPointPair(
        s2.S2LatLng_FromDegrees(region_bounds[1], region_bounds[0]),
        s2.S2LatLng_FromDegrees(region_bounds[3], region_bounds[2])
    )
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(1000000)
    return [cell.ToToken() for cell in coverer.GetCovering(s2_lat_lng_rect)]

# Convert S2 token to Shapely polygon
def s2_token_to_shapely_polygon(s2_token: str) -> shapely.geometry.polygon.Polygon:
    s2_cell = s2.S2Cell(s2.S2CellId_FromToken(s2_token, len(s2_token)))
    coords = []
    for i in range(4):
        s2_lat_lng = s2.S2LatLng(s2_cell.GetVertex(i))
        coords.append((s2_lat_lng.lng().degrees(), s2_lat_lng.lat().degrees()))
    return shapely.geometry.Polygon(coords)

# Download S2 token data
def download_s2_token(
    s2_token: str, region_df: gpd.GeoDataFrame
) -> Optional[str]:
    """Downloads the matching CSV file with polygons for the `s2_token`."""
    s2_cell_geometry = s2_token_to_shapely_polygon(s2_token)
    region_geometry = region_df.iloc[0].geometry
    prepared_region_geometry = shapely.prepared.prep(region_geometry)

    if not prepared_region_geometry.intersects(s2_cell_geometry):
        return None

    try:
        with tf.io.gfile.GFile(
            os.path.join(BUILDING_DOWNLOAD_PATH, f'{s2_token}_buildings.csv.gz'),
            'rb'
        ) as gf:
            if prepared_region_geometry.covers(s2_cell_geometry):
                with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as tmp_f:
                    tmp_f.write(gf.read())
                    return tmp_f.name

            csv_chunks = pd.read_csv(
                gf, chunksize=2000000, dtype=object, compression='gzip', header=None
            )
            tmp_f = tempfile.NamedTemporaryFile(mode='w+b', delete=False)
            tmp_f.close()

            for csv_chunk in csv_chunks:
                points = gpd.GeoDataFrame(
                    geometry=gpd.points_from_xy(csv_chunk[1], csv_chunk[0]),
                    crs='EPSG:4326'
                )
                points = gpd.sjoin(points, region_df, predicate='within')
                csv_chunk = csv_chunk.iloc[points.index]
                csv_chunk.to_csv(
                    tmp_f.name,
                    mode='ab',
                    index=False,
                    header=False,
                    compression={'method': 'gzip', 'compresslevel': 1}
                )
            return tmp_f.name
    except tf.errors.NotFoundError:
        return None

# Main function
def main():
    st.title("Open Buildings Data Downloader")

    # Load countries and prepare regions
    countries_gdf = load_countries()
    regions = prepare_regions(countries_gdf)

    # Widgets for user input
    region_border_source = st.selectbox(
        "Select Border Source:",
        ["Natural Earth (Low Res 110m)", "Natural Earth (High Res 10m)", "World Bank (High Res 10m)"]
    )
    region = st.selectbox("Region", regions)
    your_own_wkt_polygon = st.text_area(
        "Or specify an area of interest in WKT format (assumes crs='EPSG:4326'):", ""
    )
    output_format = st.selectbox("Output Format:", ["GeoJSON", "Shapefile"])

    # Button to trigger download
    if st.button("Download Data"):
        try:
            # Get region dataframe
            filename, region_df = get_filename_and_region_dataframe(
                region_border_source, region, your_own_wkt_polygon
            )

            # Download and filter building data
            s2_tokens = get_bounding_box_s2_covering_tokens(region_df.iloc[0].geometry)
            download_s2_token_fn = functools.partial(download_s2_token, region_df=region_df)

            # Create a temporary directory for output
            temp_dir = tempfile.mkdtemp()
            output_path = os.path.join(temp_dir, f"{filename}.{output_format.lower()}")

            # Process and save data
            gdf = gpd.GeoDataFrame(columns=['latitude', 'longitude', 'geometry'])
            for s2_token in tqdm.tqdm(s2_tokens):
                fname = download_s2_token_fn(s2_token)
                if fname:
                    chunk_gdf = gpd.read_file(fname)
                    gdf = pd.concat([gdf, chunk_gdf], ignore_index=True)

            if output_format == "GeoJSON":
                gdf.to_file(output_path, driver="GeoJSON")
            elif output_format == "Shapefile":
                gdf.to_file(output_path, driver="ESRI Shapefile")
                # Zip the Shapefile
                zip_path = os.path.join(temp_dir, f"{filename}.zip")
                with zipfile.ZipFile(zip_path, "w") as zipf:
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            zipf.write(os.path.join(root, file), file)
                output_path = zip_path

            # Provide download link
            with open(output_path, "rb") as file:
                st.download_button(
                    label="Download File",
                    data=file,
                    file_name=os.path.basename(output_path),
                    mime="application/octet-stream"
                )

        except Exception as e:
            st.error(f"Error: {e}")

# Run the app
if __name__ == "__main__":
    main()
