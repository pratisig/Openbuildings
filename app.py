import streamlit as st
import geopandas as gpd
from shapely.geometry import Polygon
import tempfile
from shapely import wkt
import os

st.set_page_config(page_title="Open Buildings Downloader")

st.title("Télécharger des données Open Buildings")
st.markdown("Choisissez une région ou spécifiez un polygone WKT pour générer un fichier spatial.")

regions = ["", "SEN (Senegal)", "CMR (Cameroon)", "COD (DR Congo)", "CAF (CAR)"]
region = st.selectbox("Région", regions)
your_own_wkt_polygon = st.text_area("Ou spécifiez un polygone WKT (EPSG:4326)", "")
data_type = st.selectbox("Type de données", ["polygons", "points"])
output_format = st.selectbox("Format de sortie", ["geojson", "shp"])

def get_filename_and_geometry(region, wkt_text):
    if wkt_text:
        try:
            geom = wkt.loads(wkt_text)
        except Exception:
            raise ValueError("Le WKT spécifié est invalide.")
        filename = f'open_buildings_{data_type}_custom.{output_format}'
        region_df = gpd.GeoDataFrame(geometry=[geom], crs='EPSG:4326')
        return filename, region_df
    elif region:
        st.warning("Les régions prédéfinies ne sont pas encore connectées à un shapefile.")
        return None, None
    else:
        raise ValueError("Veuillez spécifier une région ou un polygone WKT.")

def save_file(gdf, filename, output_format):
    if output_format == "geojson":
        gdf.to_file(filename, driver="GeoJSON")
    elif output_format == "shp":
        temp_dir = tempfile.mkdtemp()
        shp_path = os.path.join(temp_dir, "output.shp")
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        shutil.make_archive(filename.replace(".shp", ""), 'zip', temp_dir)
        return filename.replace(".shp", ".zip")
    return filename

if st.button("Télécharger"):
    try:
        filename, gdf = get_filename_and_geometry(region, your_own_wkt_polygon)
        if gdf is not None:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{output_format}")
            final_path = save_file(gdf, temp_file.name, output_format)
            with open(final_path, "rb") as file:
                st.download_button(
                    label="Télécharger le fichier",
                    data=file,
                    file_name=os.path.basename(final_path),
                    mime="application/zip" if output_format == "shp" else "application/json"
                )
    except Exception as e:
        st.error(f"Erreur : {e}")
