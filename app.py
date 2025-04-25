import os
import tempfile
import zipfile
import geopandas as gpd
import requests
from google.colab import files
import folium
from IPython.display import display
from ipywidgets import interact, widgets

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'polygons_s2_level_6_gzip_no_header')

# Load countries.geojson
def load_countries():
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson"
    return gpd.read_file(url)

# Function to get filename and region dataframe
def get_filename_and_region_dataframe(
    region: str, your_own_wkt_polygon: str = None
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
        return filename, region_df

    if not region:
        raise ValueError('Please select a region or set your_own_wkt_polygon.')

    # Load the selected region from the countries.geojson file
    countries_gdf = load_countries()
    region_iso_a3 = region.split(' ')[0]
    region_df = countries_gdf[countries_gdf['ISO_A3'] == region_iso_a3]

    if region_df.empty:
        raise ValueError(f"Region '{region}' not found in the dataset.")

    filename = f'open_buildings_v3_polygons_{region_iso_a3}'
    return filename, region_df.dissolve(by='ISO_A3')[['geometry']]

# Download building data
def download_building_data(region_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Downloads and filters building data for the given region."""
    storage_client = storage.Client.create_anonymous_client()
    bucket_name = 'open-buildings-data'
    bucket = storage_client.bucket(bucket_name)

    # Get S2 covering tokens for the region
    region_bounds = region_df.total_bounds
    s2_lat_lng_rect = s2sphere.LatLngRect.from_point_pair(
        s2sphere.LatLng.from_degrees(region_bounds[1], region_bounds[0]),
        s2sphere.LatLng.from_degrees(region_bounds[3], region_bounds[2])
    )
    coverer = s2sphere.RegionCoverer()
    coverer.min_level = 6
    coverer.max_level = 6
    coverer.max_cells = 1000
    s2_tokens = [cell.to_token() for cell in coverer.get_covering(s2_lat_lng_rect)]

    building_data_list = []
    for token in s2_tokens:
        blob_name = f'polygons_s2_level_6_gzip_no_header/{token}_buildings.csv.gz'
        blob = bucket.blob(blob_name)
        if not blob.exists():
            continue

        with tempfile.NamedTemporaryFile(suffix='.csv.gz', delete=False) as tmp_file:
            blob.download_to_filename(tmp_file.name)
            df = pd.read_csv(tmp_file.name, compression='gzip', header=None, names=['latitude', 'longitude', 'area_in_meters', 'confidence'])
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['longitude'], df['latitude']), crs='EPSG:4326')
            filtered_gdf = gpd.sjoin(gdf, region_df, predicate='within')
            building_data_list.append(filtered_gdf)

    if not building_data_list:
        raise ValueError("No buildings found in the specified region.")
    return pd.concat(building_data_list, ignore_index=True)

# Interactive map setup
def draw_map(countries_gdf):
    m = folium.Map(location=[0, 0], zoom_start=2)
    folium.GeoJson(countries_gdf).add_to(m)
    draw = folium.plugins.Draw(export=True)
    draw.add_to(m)
    return m

# Main function
def main():
    # Load countries
    countries_gdf = load_countries()

    # Region selection
    regions = [""] + [f"{row.ISO_A3} ({row.NAME})" for _, row in countries_gdf.iterrows()]
    region_widget = widgets.Dropdown(options=regions, description="Select Region:")
    wkt_widget = widgets.Textarea(description="WKT Polygon:", placeholder="Paste WKT here...")
    output_format_widget = widgets.Dropdown(options=["GeoJSON", "Shapefile"], description="Output Format:")
    download_button = widgets.Button(description="Download Data")

    # Display widgets
    display(region_widget, wkt_widget, output_format_widget, download_button)

    # Map for drawing
    print("Draw a polygon on the map below or paste a WKT polygon above:")
    m = draw_map(countries_gdf)
    display(m)

    def on_download_button_clicked(b):
        try:
            # Get region dataframe
            region = region_widget.value
            your_own_wkt_polygon = wkt_widget.value
            output_format = output_format_widget.value

            filename, region_df = get_filename_and_region_dataframe(region, your_own_wkt_polygon)

            # Download and filter building data
            buildings_gdf = download_building_data(region_df)

            # Save to GeoJSON or Shapefile
            if output_format == "GeoJSON":
                geojson_path = f"{filename}.geojson"
                buildings_gdf.to_file(geojson_path, driver="GeoJSON")
                files.download(geojson_path)

            elif output_format == "Shapefile":
                shapefile_dir = f"{filename}_shapefile"
                os.makedirs(shapefile_dir, exist_ok=True)
                buildings_gdf.to_file(os.path.join(shapefile_dir, f"{filename}.shp"), driver="ESRI Shapefile")

                # Zip the Shapefile
                zip_path = f"{filename}.zip"
                with zipfile.ZipFile(zip_path, "w") as zipf:
                    for root, dirs, files in os.walk(shapefile_dir):
                        for file in files:
                            zipf.write(os.path.join(root, file), file)

                files.download(zip_path)

            print(f"Data for {region} downloaded successfully!")

        except Exception as e:
            print(f"Error: {e}")

    download_button.on_click(on_download_button_clicked)

# Run the app
main()
