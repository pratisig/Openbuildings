# Import necessary libraries
import os
import tempfile
import zipfile
import geopandas as gpd
from IPython import display
import pandas as pd
import s2geometry as s2
import shapely
import tensorflow as tf
import tqdm.notebook


# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'polygons_s2_level_6_gzip_no_header')

# Load countries.geojson
def load_countries():
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson"
    return gpd.read_file(url)

# Prepare the list of regions
def prepare_regions(countries_gdf):
    regions = [""] + [f"{row.ISO_A3} ({row.NAME})" for _, row in countries_gdf.iterrows()]
    return regions

# Get filename and region dataframe
def get_filename_and_region_dataframe(
    region_border_source: str, region: str,
    your_own_wkt_polygon: str) -> Tuple[str, gpd.geodataframe.GeoDataFrame]:
    """Returns output filename and a geopandas dataframe with one region row."""
    if your_own_wkt_polygon:
        filename = f'open_buildings_v3_polygons_your_own_wkt_polygon'
        region_df = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt([your_own_wkt_polygon]),
            crs='EPSG:4326')
        if not isinstance(region_df.iloc[0].geometry, shapely.geometry.Polygon) and not isinstance(
                region_df.iloc[0].geometry, shapely.geometry.MultiPolygon):
            raise ValueError("`your_own_wkt_polygon` must be a POLYGON or MULTIPOLYGON.")
        print(f'Preparing your_own_wkt_polygon.')
        return filename, region_df

    if not region:
        raise ValueError('Please select a region or set your_own_wkt_polygon.')

    # Download the shapefile based on the selected border source
    if region_border_source == 'Natural Earth (Low Res 110m)':
        url = ('https://naciscdn.org/naturalearth/'
               '110m/cultural/ne_110m_admin_0_countries.zip')
        !wget -N {url}
        display.clear_output()
        region_shapefile_path = os.path.basename(url)
        source_name = 'ne_110m'
    elif region_border_source == 'Natural Earth (High Res 10m)':
        url = ('https://naciscdn.org/naturalearth/'
               '10m/cultural/ne_10m_admin_0_countries.zip')
        !wget -N {url}
        display.clear_output()
        region_shapefile_path = os.path.basename(url)
        source_name = 'ne_10m'
    elif region_border_source == 'World Bank (High Res 10m)':
        url = ('https://datacatalogfiles.worldbank.org/ddh-published/'
               '0038272/DR0046659/wb_countries_admin0_10m.zip')
        !wget -N {url}
        !unzip -o {os.path.basename(url)}
        display.clear_output()
        region_shapefile_path = 'WB_countries_Admin0_10m'
        source_name = 'wb_10m'

    region_iso_a3 = region.split(' ')[0]
    filename = f'open_buildings_v3_polygons_{source_name}_{region_iso_a3}'
    region_df = gpd.read_file(region_shapefile_path).query(
        f'ISO_A3 == "{region_iso_a3}"').dissolve(by='ISO_A3')[['geometry']]
    print(f'Preparing {region} from {region_border_source}.')
    return filename, region_df

# Get bounding box S2 covering tokens
def get_bounding_box_s2_covering_tokens(
    region_geometry: shapely.geometry.base.BaseGeometry) -> List[str]:
    region_bounds = region_geometry.bounds
    s2_lat_lng_rect = s2.S2LatLngRect_FromPointPair(
        s2.S2LatLng_FromDegrees(region_bounds[1], region_bounds[0]),
        s2.S2LatLng_FromDegrees(region_bounds[3], region_bounds[2]))
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
    s2_token: str, region_df: gpd.geodataframe.GeoDataFrame) -> Optional[str]:
    """Downloads the matching CSV file with polygons for the `s2_token`."""
    s2_cell_geometry = s2_token_to_shapely_polygon(s2_token)
    region_geometry = region_df.iloc[0].geometry
    prepared_region_geometry = shapely.prepared.prep(region_geometry)

    if not prepared_region_geometry.intersects(s2_cell_geometry):
        return None

    try:
        with tf.io.gfile.GFile(
            os.path.join(BUILDING_DOWNLOAD_PATH, f'{s2_token}_buildings.csv.gz'),
            'rb') as gf:
            if prepared_region_geometry.covers(s2_cell_geometry):
                with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as tmp_f:
                    shutil.copyfileobj(gf, tmp_f)
                    return tmp_f.name

            csv_chunks = pd.read_csv(
                gf, chunksize=2000000, dtype=object, compression='gzip', header=None)
            tmp_f = tempfile.NamedTemporaryFile(mode='w+b', delete=False)
            tmp_f.close()

            for csv_chunk in csv_chunks:
                points = gpd.GeoDataFrame(
                    geometry=gpd.points_from_xy(csv_chunk[1], csv_chunk[0]),
                    crs='EPSG:4326')
                points = gpd.sjoin(points, region_df, predicate='within')
                csv_chunk = csv_chunk.iloc[points.index]
                csv_chunk.to_csv(
                    tmp_f.name,
                    mode='ab',
                    index=False,
                    header=False,
                    compression={
                        'method': 'gzip',
                        'compresslevel': 1
                    })
            return tmp_f.name
    except tf.errors.NotFoundError:
        return None

# Main function
def main():
    # Load countries and prepare regions
    countries_gdf = load_countries()
    regions = prepare_regions(countries_gdf)

    # Widgets for user input
    region_border_source = widgets.Dropdown(
        options=["Natural Earth (Low Res 110m)", "Natural Earth (High Res 10m)", "World Bank (High Res 10m)"],
        description="Border Source:")
    region = widgets.Dropdown(options=regions, description="Region:")
    your_own_wkt_polygon = widgets.Textarea(description="WKT Polygon:", placeholder="Paste WKT here...")
    output_format = widgets.Dropdown(options=["GeoJSON", "Shapefile"], description="Output Format:")

    # Display widgets
    display.display(region_border_source, region, your_own_wkt_polygon, output_format)

    # Button to trigger download
    download_button = widgets.Button(description="Download Data")
    display.display(download_button)

    def on_download_button_clicked(b):
        try:
            # Get region dataframe
            filename, region_df = get_filename_and_region_dataframe(
                region_border_source.value, region.value, your_own_wkt_polygon.value)

            # Download and filter building data
            s2_tokens = get_bounding_box_s2_covering_tokens(region_df.iloc[0].geometry)
            download_s2_token_fn = functools.partial(download_s2_token, region_df=region_df)

            # Create a temporary directory for output
            temp_dir = tempfile.mkdtemp()
            output_path = os.path.join(temp_dir, f"{filename}.{output_format.value.lower()}")

            # Process and save data
            if output_format.value == "GeoJSON":
                gdf = gpd.GeoDataFrame(columns=['latitude', 'longitude', 'geometry'])
                for s2_token in tqdm.notebook.tqdm(s2_tokens):
                    fname = download_s2_token_fn(s2_token)
                    if fname:
                        chunk_gdf = gpd.read_file(fname)
                        gdf = pd.concat([gdf, chunk_gdf], ignore_index=True)
                gdf.to_file(output_path, driver="GeoJSON")
            elif output_format.value == "Shapefile":
                gdf = gpd.GeoDataFrame(columns=['latitude', 'longitude', 'geometry'])
                for s2_token in tqdm.notebook.tqdm(s2_tokens):
                    fname = download_s2_token_fn(s2_token)
                    if fname:
                        chunk_gdf = gpd.read_file(fname)
                        gdf = pd.concat([gdf, chunk_gdf], ignore_index=True)
                gdf.to_file(output_path, driver="ESRI Shapefile")
                # Zip the Shapefile
                zip_path = os.path.join(temp_dir, f"{filename}.zip")
                with zipfile.ZipFile(zip_path, "w") as zipf:
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            zipf.write(os.path.join(root, file), file)
                output_path = zip_path

            # Provide download link
            from google.colab import files
            files.download(output_path)

        except Exception as e:
            print(f"Error: {e}")

    download_button.on_click(on_download_button_clicked)

# Run the app
main()
