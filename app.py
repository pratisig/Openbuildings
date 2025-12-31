import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
import s2geometry as s2
from shapely.geometry import box
import tensorflow as tf

# Configuration
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

# Constants
BUILDING_DOWNLOAD_PATH = 'gs://open-buildings-data/v3/polygons_s2_level_6_gzip_no_header'

@st.cache_data
def load_countries():
    """Charge le GeoJSON des pays depuis GitHub"""
    url = "https://raw.githubusercontent.com/pratisig/Openbuildings/main/countries.geojson"
    try:
        gdf = gpd.read_file(url)
        # Garder les noms de colonnes originaux (en minuscules)
        return gdf
    except Exception as e:
        st.error(f"Erreur chargement GeoJSON : {e}")
        return None

@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    """Télécharge et extrait un shapefile depuis une URL"""
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        
        with open(zip_path, 'wb') as f:
            f.write(r.content)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    gdf = gpd.read_file(os.path.join(root, file))
                    return gdf
    return None

def prepare_regions(countries_gdf):
    """Prépare la liste des pays pour le selectbox"""
    if countries_gdf is None:
        return [""]
    
    # Chercher les colonnes ISO et nom (sensible à la casse)
    iso_col = None
    name_col = None
    
    for col in countries_gdf.columns:
        col_upper = col.upper()
        if col_upper in ['ISO_A3', 'ISO3', 'ADM0_A3']:
            iso_col = col
        if col_upper in ['NAME', 'ADMIN', 'NAME_EN', 'SOVEREIGNT']:
            name_col = col
    
    if not iso_col or not name_col:
        st.warning(f"Colonnes trouvées : {list(countries_gdf.columns)}")
        return [""] + [f"Zone {i}" for i in range(len(countries_gdf))]
    
    # Créer la liste "NOM (ISO)"
    regions = []
    for _, row in countries_gdf.iterrows():
        iso_val = str(row[iso_col]).strip()
        name_val = str(row[name_col]).strip()
        if iso_val and iso_val != 'nan' and name_val and name_val != 'nan':
            regions.append(f"{name_val} ({iso_val})")
    
    return [""] + sorted(regions)

def get_s2_tokens(geometry) -> list:
    """Génère les tokens S2 pour une géométrie donnée"""
    bounds = geometry.bounds  # (minx, miny, maxx, maxy)
    
    # Création du rectangle S2
    rect = s2.S2LatLngRect(
        s2.S2LatLng.FromDegrees(bounds[1], bounds[0]),  # Low (Sud, Ouest)
        s2.S2LatLng.FromDegrees(bounds[3], bounds[2])   # High (Nord, Est)
    )
    
    coverer = s2.S2RegionCoverer()
    coverer.set_fixed_level(6)
    coverer.set_max_cells(1000)
    
    covering = coverer.GetCovering(rect)
    return [cell.ToToken() for cell in covering]

def find_iso_column(gdf):
    """Trouve la colonne ISO dans un GeoDataFrame"""
    for col in gdf.columns:
        col_upper = col.upper()
        if col_upper in ['ISO_A3', 'ISO3', 'ADM0_A3', 'ISO_A2', 'WB_A3']:
            return col
    return None

def main():
    st.title("🏢 Open Buildings Extractor")
    st.markdown("Téléchargez les données de bâtiments depuis Google Open Buildings")
    
    # Chargement des pays pour la sélection
    countries_gdf = load_countries()
    regions_list = prepare_regions(countries_gdf)
    
    # Interface à onglets
    tab1, tab2 = st.tabs(["🌍 Sélection par Pays", "📐 Coordonnées (BBox)"])
    
    mode = "bbox"  # par défaut
    choice = ""
    n = s = e = w = 0.0
    
    with tab1:
        st.markdown("### Sélectionner un pays")
        source_name = st.selectbox(
            "Source des frontières :",
            ["Natural Earth (High Res 10m)", "World Bank (High Res)"],
            help="Natural Earth est recommandé pour la plupart des cas"
        )
        choice = st.selectbox("Pays :", regions_list)
        if choice:
            mode = "country"
    
    with tab2:
        st.markdown("### Entrer des coordonnées manuelles")
        st.info("📍 Obtenez les coordonnées sur [bboxfinder.com](http://bboxfinder.com)")
        
        col1, col2 = st.columns(2)
        with col1:
            n = st.number_input("🔼 Nord (Latitude Max)", value=0.0, format="%.6f", step=0.1)
            s = st.number_input("🔽 Sud (Latitude Min)", value=0.0, format="%.6f", step=0.1)
        with col2:
            e = st.number_input("➡️ Est (Longitude Max)", value=0.0, format="%.6f", step=0.1)
            w = st.number_input("⬅️ Ouest (Longitude Min)", value=0.0, format="%.6f", step=0.1)
        
        if n != 0.0 or s != 0.0 or e != 0.0 or w != 0.0:
            mode = "bbox"

    # Bouton d'extraction
    if st.button("🚀 Extraire les données", type="primary"):
        try:
            geom = None
            name = ""
            
            # Mode Pays
            if mode == "country" and choice:
                st.info(f"Mode : Sélection par pays - {choice}")
                
                # Extraire le code ISO du choix
                iso_code = choice.split('(')[-1].strip(')')
                
                # Charger le shapefile source
                url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
                if "World Bank" in source_name:
                    url = "https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip"
                
                with st.spinner("Téléchargement du shapefile des frontières..."):
                    full_gdf = fetch_and_extract_shapefile(url)
                
                if full_gdf is None:
                    st.error("Impossible de charger le shapefile")
                    return
                
                # Trouver la colonne ISO
                iso_col = find_iso_column(full_gdf)
                
                if not iso_col:
                    st.error(f"Aucune colonne ISO trouvée. Colonnes disponibles : {list(full_gdf.columns)}")
                    return
                
                # Filtrer le pays
                target_gdf = full_gdf[full_gdf[iso_col] == iso_code]
                
                if target_gdf.empty:
                    st.error(f"❌ Code ISO '{iso_code}' non trouvé dans {source_name}")
                    st.info(f"Codes disponibles : {sorted(full_gdf[iso_col].unique()[:20])}")
                    return
                
                geom = target_gdf.dissolve().iloc[0].geometry
                name = iso_code
                st.success(f"✅ Pays trouvé : {choice}")
            
            # Mode BBox
            elif mode == "bbox" and (n != 0.0 or s != 0.0):
                if n <= s or e <= w:
                    st.error("❌ Coordonnées invalides : Nord doit être > Sud et Est doit être > Ouest")
                    return
                
                st.info(f"Mode : BBox personnalisée ({w}, {s}, {e}, {n})")
                geom = box(w, s, e, n)
                name = f"custom_{abs(hash(f'{n}{s}{e}{w}'))}"
                st.success("✅ Zone définie")
            
            else:
                st.warning("⚠️ Veuillez sélectionner un pays OU entrer des coordonnées")
                return
            
            # Extraction des données
            st.markdown("---")
            st.subheader("📥 Téléchargement des données")
            
            tokens = get_s2_tokens(geom)
            st.info(f"🔢 Nombre de tuiles S2 à traiter : {len(tokens)}")
            
            all_data = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, token in enumerate(tokens):
                status_text.text(f"Traitement de la tuile {i+1}/{len(tokens)} ({token})")
                
                csv_url = os.path.join(BUILDING_DOWNLOAD_PATH, f'{token}_buildings.csv.gz')
                
                try:
                    with tf.io.gfile.GFile(csv_url, 'rb') as gf:
                        df = pd.read_csv(gf, header=None, compression='gzip')
                        
                        if len(df.columns) >= 3:
                            # Colonnes : latitude, longitude, geometry_wkt, ...
                            gdf_chunk = gpd.GeoDataFrame(
                                df,
                                geometry=gpd.GeoSeries.from_wkt(df[2]),
                                crs='EPSG:4326'
                            )
                            
                            # Filtrage spatial
                            gdf_chunk = gdf_chunk[gdf_chunk.intersects(geom)]
                            
                            if not gdf_chunk.empty:
                                all_data.append(gdf_chunk)
                                status_text.text(f"✅ Tuile {i+1}/{len(tokens)} : {len(gdf_chunk)} bâtiments trouvés")
                
                except Exception as e:
                    # Tuile vide ou erreur, on continue
                    pass
                
                progress_bar.progress((i + 1) / len(tokens))
            
            status_text.empty()
            progress_bar.empty()
            
            # Résultats
            if not all_data:
                st.warning("⚠️ Aucun bâtiment trouvé dans cette zone")
                st.info("Cela peut signifier :\n- La zone est vide\n- Les données ne sont pas disponibles pour cette région\n- Les coordonnées sont incorrectes")
            else:
                final_gdf = pd.concat(all_data, ignore_index=True)
                st.success(f"🎉 **{len(final_gdf)} bâtiments** extraits avec succès !")
                
                # Statistiques
                col1, col2, col3 = st.columns(3)
                col1.metric("Bâtiments", f"{len(final_gdf):,}")
                col2.metric("Tuiles traitées", len(tokens))
                col3.metric("Tuiles avec données", len(all_data))
                
                # Export
                out_path = f"{name}_buildings.geojson"
                final_gdf.to_file(out_path, driver="GeoJSON")
                
                with open(out_path, "rb") as f:
                    st.download_button(
                        label="💾 Télécharger le GeoJSON",
                        data=f,
                        file_name=out_path,
                        mime="application/geo+json"
                    )
                
                # Nettoyage
                os.remove(out_path)
        
        except Exception as e:
            st.error(f"❌ Erreur système : {e}")
            st.exception(e)

if __name__ == "__main__":
    main()
