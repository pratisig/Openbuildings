import os
import tempfile
import zipfile
import geopandas as gpd
import requests
import streamlit as st
from typing import Tuple
from google.cloud import storage
import s2sphere
import pandas as pd

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'building_data_s2_level_6_gzip_no_header')
data_type = 'polygons'  # Default data type

# Load countries.geojson
@st.cache_data
def load_countries():
    return gpd.read_file("https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson")

# Function to get filename and region dataframe
def get_filename_and_region_dataframe(
    region_border_source: str, region: str, your_own_wkt_polygon: str = None
) -> Tuple[str, gpd.GeoDataFrame]:
    """Returns output filename and a GeoDataFrame with one region row."""
    if your_own_wkt_polygon:
        filename = f'open_buildings_v3_{data_type}_your_own_wkt_polygon'
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

    filename = f'open_buildings_v3_{data_type}_{region_iso_a3}'
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
        blob_name = f'{data_type}_s2_level_6_gzip_no_header/{token}_buildings.csv.gz'
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

# Streamlit Interface
st.title("Open Buildings Data Downloader")

# Load countries
countries_gdf = load_countries()

# Region selection
region_border_source = st.selectbox(
    "Select Border Source:",
    ["Natural Earth (Low Res 110m)", "Natural Earth (High Res 10m)", "World Bank (High Res 10m)"]
)
regions = [
    "", "ABW (Aruba)", "AGO (Angola)", "AIA (Anguilla)", "ARG (Argentina)",
    "ATG (Antigua and Barbuda)", "BDI (Burundi)", "BEN (Benin)", "BFA (Burkina Faso)",
    "BGD (Bangladesh)", "BHS (The Bahamas)", "BLM (Saint Barthelemy)", "BLZ (Belize)",
    "BOL (Bolivia)", "BRA (Brazil)", "BRB (Barbados)", "BRN (Brunei)", "BTN (Bhutan)",
    "BWA (Botswana)", "CAF (Central African Republic)", "CHL (Chile)", "CIV (Ivory Coast)",
    "CMR (Cameroon)", "COD (Democratic Republic of the Congo)", "COG (Republic of Congo)",
    "COL (Colombia)", "COM (Comoros)", "CPV (Cape Verde)", "CRI (Costa Rica)", "CUB (Cuba)",
    "CUW (Curaçao)", "CYM (Cayman Islands)", "DJI (Djibouti)", "DMA (Dominica)",
    "DOM (Dominican Republic)", "DZA (Algeria)", "ECU (Ecuador)", "EGY (Egypt)",
    "ERI (Eritrea)", "ETH (Ethiopia)", "FLK (Falkland Islands)", "GAB (Gabon)",
    "GHA (Ghana)", "GIN (Guinea)", "GMB (Gambia)", "GNB (Guinea Bissau)",
    "GNQ (Equatorial Guinea)", "GRD (Grenada)", "GTM (Guatemala)", "GUY (Guyana)",
    "HND (Honduras)", "HTI (Haiti)", "IDN (Indonesia)", "IND (India)",
    "IOT (British Indian Ocean Territory)", "JAM (Jamaica)", "KEN (Kenya)",
    "KHM (Cambodia)", "KNA (Saint Kitts and Nevis)", "LAO (Laos)", "LBR (Liberia)",
    "LCA (Saint Lucia)", "LKA (Sri Lanka)", "LSO (Lesotho)", "MAF (Saint Martin)",
    "MDG (Madagascar)", "MDV (Maldives)", "MEX (Mexico)", "MOZ (Mozambique)",
    "MRT (Mauritania)", "MSR (Montserrat)", "MUS (Mauritius)", "MWI (Malawi)",
    "MYS (Malaysia)", "MYT (Mayotte)", "NAM (Namibia)", "NER (Niger)", "NGA (Nigeria)",
    "NIC (Nicaragua)", "NPL (Nepal)", "PAN (Panama)", "PER (Peru)", "PHL (Philippines)",
    "PRI (Puerto Rico)", "PRY (Paraguay)", "RWA (Rwanda)", "SDN (Sudan)", "SEN (Senegal)",
    "SGP (Singapore)", "SHN (Saint Helena)", "SLE (Sierra Leone)", "SLV (El Salvador)",
    "SOM (Somalia)", "STP (Sao Tome and Principe)", "SUR (Suriname)", "SWZ (Eswatini)",
    "SXM (Sint Maarten)", "SYC (Seychelles)", "TCA (Turks and Caicos Islands)",
    "TGO (Togo)", "THA (Thailand)", "TLS (East Timor)", "TTO (Trinidad and Tobago)",
    "TUN (Tunisia)", "TZA (United Republic of Tanzania)", "UGA (Uganda)", "URY (Uruguay)",
    "VCT (Saint Vincent and the Grenadines)", "VEN (Venezuela)", "VGB (British Virgin Islands)",
    "VIR (United States Virgin Islands)", "VNM (Vietnam)", "ZAF (South Africa)",
    "ZMB (Zambia)", "ZWE (Zimbabwe)"
]
region = st.selectbox("Region", regions)

# Custom WKT polygon input
your_own_wkt_polygon = st.text_area("Or specify an area of interest in WKT format (assumes crs='EPSG:4326'):", "")

# Output format selection
output_format = st.selectbox("Select Output Format:", ["GeoJSON", "Shapefile"])

# Download button
if st.button("Download Data"):
    try:
        # Get region dataframe
        filename, region_df = get_filename_and_region_dataframe(region_border_source, region, your_own_wkt_polygon)

        # Download and filter building data
        buildings_gdf = download_building_data(region_df)

        # Save to GeoJSON or Shapefile
        if output_format == "GeoJSON":
            geojson_path = f"{filename}.geojson"
            buildings_gdf.to_file(geojson_path, driver="GeoJSON")
            with open(geojson_path, "rb") as file:
                st.download_button(
                    label="Download GeoJSON",
                    data=file,
                    file_name=os.path.basename(geojson_path),
                    mime="application/geo+json"
                )

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

            with open(zip_path, "rb") as file:
                st.download_button(
                    label="Download Shapefile",
                    data=file,
                    file_name=os.path.basename(zip_path),
                    mime="application/zip"
                )

        st.success(f"Data for {region} downloaded successfully!")

    except Exception as e:
        st.error(f"Error: {e}")
