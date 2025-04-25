import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon
import tempfile
import os
import pandas as pd

# Configuration de l'application
st.title("Télécharger des données Open Buildings")
st.markdown("Choisissez une région ou spécifiez un polygone WKT pour télécharger les données au format GeoJSON ou Shapefile.")

# Widgets
region_border_source = st.selectbox("Source des frontières régionales", [
    "Natural Earth (Low Res 110m)", "Natural Earth (High Res 10m)", "World Bank (High Res 10m)"
])

regions = ["", "SEN (Senegal)", "MLI (Mali)", "GIN (Guinea)", "CIV (Ivory Coast)"]
region = st.selectbox("Région", regions)
your_own_wkt_polygon = st.text_area("Ou spécifiez un polygone WKT (EPSG:4326)", "")
data_type = st.selectbox("Type de données", ["polygons", "points"])
output_format = st.selectbox("Format de sortie", ["geojson", "shp"])

# Fonction pour sauvegarder
def save_to_geojson_or_shp(gdf, filename, output_format):
    if output_format == "geojson":
        gdf.to_file(filename, driver="GeoJSON")
    elif output_format == "shp":
        gdf.to_file(filename, driver="ESRI Shapefile")

# Fonction pour préparer les données
def get_region_geometry(region_border_source, region, your_own_wkt_polygon):
    if your_own_wkt_polygon:
        region_df = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt([your_own_wkt_polygon]),
            crs='EPSG:4326'
        )
        return f"open_buildings_custom.{output_format}", region_df

    if not region:
        raise ValueError("Veuillez choisir une région ou spécifier un polygone.")

    # Simulation simple pour test (à remplacer par lecture réelle shapefile)
    gdf = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
        crs="EPSG:4326"
    )
    return f"open_buildings_{region}.{output_format}", gdf

# Téléchargement
if st.button("Télécharger"):
    try:
        filename, gdf = get_region_geometry(region_border_source, region, your_own_wkt_polygon)

        # Sauvegarde dans un fichier temporaire
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{output_format}") as tmp_file:
            tmp_path = tmp_file.name

        save_to_geojson_or_shp(gdf, tmp_path, output_format)

        # Téléchargement
        with open(tmp_path, "rb") as file:
            st.download_button(
                label="Télécharger le fichier",
                data=file,
                file_name=filename,
                mime="application/json" if output_format == "geojson" else "application/zip"
            )

        st.success("Fichier généré avec succès !")

    except Exception as e:
        st.error(f"Erreur : {e}")
