import zipfile
import os
import requests
import geopandas as gpd
import shapely
import streamlit as st
from typing import Tuple

# Constants
BUILDING_DOWNLOAD_PATH = ('gs://open-buildings-data/v3/'
                          'building_data_s2_level_6_gzip_no_header')
data_type = 'building'  # Change this to match your data type

def get_filename_and_region_dataframe(region_border_source: str, region: str,
                                      your_own_wkt_polygon: str = None) -> Tuple[str, gpd.GeoDataFrame]:
    """Returns output filename and a geopandas dataframe with one region row."""
    
    if your_own_wkt_polygon:
        filename = f'open_buildings_{data_type}_your_own_wkt_polygon.geojson'
        region_df = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt([your_own_wkt_polygon]),
            crs='EPSG:4326')
        
        if not isinstance(region_df.iloc[0].geometry, (shapely.geometry.Polygon, shapely.geometry.MultiPolygon)):
            raise ValueError("`your_own_wkt_polygon` must be a POLYGON or MULTIPOLYGON.")
        
        return filename, region_df
    
    if not region:
        raise ValueError('Please select a region or set your_own_wkt_polygon.')
    
    if region_border_source == 'Natural Earth (Low Res 110m)':
        url = 'https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip'
        response = requests.get(url)
        with open('ne_110m.zip', 'wb') as f:  # <-- Make sure there is a colon at the end
            f.write(response.content)
        region_shapefile_path = 'ne_110m.zip'
        source_name = 'ne_110m'
    
    elif region_border_source == 'Natural Earth (High Res 10m)':
        url = 'https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip'
        response = requests.get(url)
        with open('ne_10m.zip', 'wb') as f:  # <-- Ensure the colon is present
            f.write(response.content)
        region_shapefile_path = 'ne_10m.zip'
        source_name = 'ne_10m'
    
    elif region_border_source == 'World Bank (High Res 10m)':
        url = 'https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip'
        response = requests.get(url)
        with open('wb_countries_admin0_10m.zip', 'wb') as f:  # <-- Ensure colon is here
            f.write(response.content)
        
        # Unzip the file and check for the .shp file
        with zipfile.ZipFile('wb_countries_admin0_10m.zip', 'r') as zip_ref:
            zip_ref.extractall()
        
        # List all extracted files and check for the shapefile
        extracted_files = os.listdir()
        shapefile_path = None
        for file in extracted_files:
            if file.endswith('.shp'):
                shapefile_path = file
                break
        
        if shapefile_path is None:
            raise FileNotFoundError("Shapefile (.shp) not found in the extracted files.")
        
        region_shapefile_path = shapefile_path
        source_name = 'wb_10m'

    region_iso_a3 = region.split(' ')[0]
    filename = f'open_buildings_{data_type}_{source_name}_{region_iso_a3}.geojson'

    # Read the shapefile and filter for the region
    region_df = gpd.read_file(region_shapefile_path).query(
        f'ISO_A3 == "{region_iso_a3}"').dissolve(by='ISO_A3')[['geometry']]
    
    return filename, region_df


# Streamlit interface
st.title("Open Buildings Data Downloader")

# Load the countries.geojson file into a GeoDataFrame
countries_gdf = gpd.read_file("countries.geojson")

# List of country names (or ISO codes, depending on the data structure)
country_list = countries_gdf['name'].tolist()  # Assuming the column is 'name', change if needed

# Region selection dropdown
region = st.selectbox('Select a Country:', country_list)

# Region border source selection
region_border_source = st.selectbox('Select Border Source:', 
                                    ['Natural Earth (Low Res 110m)', 'Natural Earth (High Res 10m)', 'World Bank (High Res 10m)'])

# Custom WKT polygon input
wkt_polygon = st.text_area('Or enter your custom WKT polygon:', '')

# Select data format
output_format = st.selectbox("Select Output Format:", ["GeoJSON", "Shapefile"])

# Button to download data
if st.button('Download Data'):
    try:
        # Fetch the data based on region or WKT polygon
        filename, region_df = get_filename_and_region_dataframe(region_border_source, region, wkt_polygon)
        
        # Save the file to GeoJSON or Shapefile
        if output_format == "GeoJSON":
            region_df.to_file(filename, driver='GeoJSON')
            st.download_button('Download GeoJSON', data=open(filename, 'rb'), file_name=filename, mime="application/geo+json")
        
        elif output_format == "Shapefile":
            shapefile_dir = os.path.splitext(filename)[0]
            os.makedirs(shapefile_dir, exist_ok=True)
            region_df.to_file(f"{shapefile_dir}/{filename}", driver='ESRI Shapefile')
            # Package shapefile into a zip
            with zipfile.ZipFile(f"{shapefile_dir}.zip", 'w') as zipf:
                for file in os.listdir(shapefile_dir):
                    zipf.write(os.path.join(shapefile_dir, file), file)
            st.download_button('Download Shapefile', data=open(f"{shapefile_dir}.zip", 'rb'), file_name=f"{shapefile_dir}.zip", mime="application/zip")
        
        st.success(f"Data for {region} downloaded successfully!")

    except Exception as e:
        st.error(f"Error: {e}")
