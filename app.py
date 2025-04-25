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
                          'polygons_s2_level_6_gzip_no_header')
data_type = 'polygons'  # Default data type

# Load countries.geojson
@st.cache_data
def load_countries():
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson"
    return gpd.read_file(url)

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

        with tempfile.NamedTemporaryFile(suffix='.csv.gz', delete=False)
