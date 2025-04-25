import streamlit as st
import geopandas as gpd
import pandas as pd
import shapely.wkt
from shapely.geometry import shape
import io
import tempfile
import os
import zipfile
import requests
import json
from streamlit_folium import st_folium
import folium
from folium.plugins import Draw
from s2sphere import RegionCoverer, LatLng, Cap

st.set_page_config(page_title="Téléchargement Open Buildings", layout="wide")
st.title("📦 Télécharger des données de bâtiments (Google Open Buildings)")

# --- ZONE DE SELECTION ---
st.sidebar.header("Méthode de sélection")
mode = st.sidebar.radio("Choisir la zone", ["📍 Choisir un pays", "✏️ Dessiner un polygone"])

geometry = None

if mode == "📍 Choisir un pays":
    world = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres"))
    countries = world["name"].sort_values().tolist()
    selected_country = st.sidebar.selectbox("Pays", countries)
    geometry = world[world["name"] == selected_country].geometry.values[0]

else:
    st.sidebar.info("Tracez un polygone sur la carte ci-dessous")
    m = folium.Map(location=[0, 0], zoom_start=2)
    draw = Draw(export=True, filename='drawn.geojson')
    draw.add_to(m)
    result = st_folium(m, width=700, height=500)
    geojson = result.get("last_active_drawing")
    if geojson:
        geometry = shape(geojson["geometry"])

# --- OPTIONS ---
st.sidebar.header("Options de données")
data_type = st.sidebar.selectbox("Type de données", ["polygons", "points"])
export_format = st.sidebar.selectbox("Format de sortie", ["GeoJSON", "Shapefile"])

# --- S2 COVERING ---
def get_s2_covering(geom, level=13):
    coverer = RegionCoverer()
    coverer.min_level = level
    coverer.max_level = level
    rect = geom.bounds
    latlng1 = LatLng.from_degrees(rect[1], rect[0])
    latlng2 = LatLng.from_degrees(rect[3], rect[2])
    region = Cap.from_axis_angle(latlng1.to_point(), 0.1)
    cell_ids = coverer.get_covering(region)
    return [cell.id() for cell in cell_ids]

# --- TELECHARGEMENT DONNEES GOOGLE OPEN BUILDINGS ---
def download_and_filter(geom, data_type="polygons"):
    ids = get_s2_covering(geom)
    gdf_all = []
    for s2_id in ids:
        url = f"https://storage.googleapis.com/open-buildings-data/v2/{data_type}_s2_level_13/{s2_id}.csv.gz"
        r = requests.get(url)
        if r.status_code != 200:
            continue
        df = pd.read_csv(io.BytesIO(r.content), compression="gzip")
        if data_type == "polygons":
            df["geometry"] = df["geometry"].apply(shapely.wkt.loads)
        else:
            df["geometry"] = df.apply(lambda row: shapely.geometry.Point(row["longitude"], row["latitude"]), axis=1)
        gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
        gdf_all.append(gdf[gdf.intersects(geom)])
    if not gdf_all:
        return None
    return pd.concat(gdf_all)

# --- BOUTON TELECHARGER ---
if st.button("Télécharger"):
    if not geometry:
        st.error("Veuillez choisir ou dessiner une zone.")
    else:
        gdf = download_and_filter(geometry, data_type)
        if gdf is None or gdf.empty:
            st.warning("Aucune donnée disponible pour cette zone.")
        else:
            if export_format == "GeoJSON":
                geojson = gdf.to_json()
                st.download_button("Télécharger GeoJSON", geojson.encode(), "buildings.geojson", "application/json")
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    shp_path = os.path.join(tmpdir, "buildings.shp")
                    gdf.to_file(shp_path)
                    zip_path = os.path.join(tmpdir, "buildings.zip")
                    with zipfile.ZipFile(zip_path, "w") as zf:
                        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                            file = shp_path.replace(".shp", ext)
                            if os.path.exists(file):
                                zf.write(file, arcname=os.path.basename(file))
                    with open(zip_path, "rb") as f:
                        st.download_button("Télécharger Shapefile (ZIP)", f.read(), "buildings.zip", "application/zip")

# --- INFO ---
st.markdown("""
---
**📌 Source des données :** [Google Open Buildings Dataset](https://sites.research.google/open-buildings/#download)
""")
