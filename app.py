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
        with open('ne_110m.zip', 'wb') as f:
            f.write(response.content)
        region_shapefile_path = 'ne_110m.zip'
        source_name = 'ne_110m'
    
    elif region_border_source == 'Natural Earth (High Res 10m)':
        url = 'https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip'
        response = requests.get(url)
        with open
