import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon
import tempfile
import os
import gzip
import s2geometry as s2
import pandas as pd
import tensorflow as tf
import multiprocessing
import glob
import shutil
import tqdm

# Configuration de l'application
st.title("Télécharger des données Open Buildings")
st.markdown("Choisissez une région ou spécifiez un polygone WKT pour télécharger les données au format GeoJSON ou Shapefile.")

# Widgets pour les paramètres
region_border_source = st.selectbox(
    "Source des frontières régionales",
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

region = st.selectbox("Région", regions)
your_own_wkt_polygon = st.text_area("Ou spécifiez un polygone WKT (EPSG:4326)", "")
data_type = st.selectbox("Type de données", ["polygons", "points"])
output_format = st.selectbox("Format de sortie", ["geojson", "shp"])

# Fonction pour préparer les données
def get_filename_and_region_dataframe(region_border_source, region, your_own_wkt_polygon):
    if your_own_wkt_polygon:
        filename = f'open_buildings_v3_{data_type}_your_own_wkt_polygon.{output_format}'
        region_df = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries.from_wkt([your_own_wkt_polygon]),
            crs='EPSG:4326')
        return filename, region_df
    if not region:
        raise ValueError('Veuillez sélectionner une région ou spécifier un polygone WKT.')
    # Ajoutez ici la logique pour charger les régions depuis les fichiers shapefile
    # ...
    return filename, region_df

# Bouton pour démarrer le téléchargement
if st.button("Télécharger"):
    try:
        filename, region_df = get_filename_and_region_dataframe(region_border_source, region, your_own_wkt_polygon)

        # Logique pour générer les fichiers GeoJSON ou Shapefile
        def save_to_geojson_or_shp(gdf, filename):
            if output_format == 'geojson':
                gdf.to_file(filename, driver='GeoJSON')
            elif output_format == 'shp':
                gdf.to_file(filename.replace('.shp', '.zip'), driver='ESRI Shapefile')

        # Simulez la génération des données
        gdf = gpd.GeoDataFrame(geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])], crs='EPSG:4326')
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{output_format}') as tmp_file:
            save_to_geojson_or_shp(gdf, tmp_file.name)
            st.success("Fichier prêt !")

            # Téléchargement du fichier
            with open(tmp_file.name, "rb") as file:
                st.download_button(
                    label="Télécharger le fichier",
                    data=file,
                    file_name=os.path.basename(tmp_file.name),
                    mime="application/zip" if output_format == "shp" else "application/json"
                )
    except Exception as e:
        st.error(f"Une erreur est survenue : {e}")
