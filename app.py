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
    """Charge le GeoJSON des pays depuis le fichier local"""
    geojson_path = "countries.geojson"
    
    # Vérifier si le fichier existe
    if not os.path.exists(geojson_path):
        st.error(f"❌ Fichier {geojson_path} non trouvé dans le répertoire")
        return None
    
    try:
        gdf = gpd.read_file(geojson_path)
        return gdf
    except Exception as e:
        st.error(f"Erreur chargement GeoJSON : {e}")
        return None

@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    """Télécharge et extrait un shapefile depuis une URL"""
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = os.path.join(temp_dir, 'shapefile.zip')
        r = requests.get(url, timeout=60)
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
    
    # Les colonnes dans le GeoJSON sont : name, ISO3166-1-Alpha-3, ISO3166-1-Alpha-2
    name_col = None
    iso_col = None
    
    # Chercher la colonne name
    if 'name' in countries_gdf.columns:
        name_col = 'name'
    
    # Chercher la colonne ISO (priorité à ISO3)
    if 'ISO3166-1-Alpha-3' in countries_gdf.columns:
        iso_col = 'ISO3166-1-Alpha-3'
    elif 'ISO3166-1-Alpha-2' in countries_gdf.columns:
        iso_col = 'ISO3166-1-Alpha-2'
    
    if not name_col or not iso_col:
        st.error(f"Colonnes manquantes. Colonnes disponibles : {list(countries_gdf.columns)}")
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
    # Liste de colonnes ISO possibles (ordre de priorité)
    iso_columns = ['ISO_A3', 'ISO3', 'ADM0_A3', 'WB_A3', 'ISO_A2', 'ISO3166-1-Alpha-3', 'ISO3166-1-Alpha-2']
    
    for col in gdf.columns:
        if col in iso_columns:
            return col
    
    return None

def main():
    st.title("🏢 Open Buildings Extractor")
    st.markdown("Téléchargez les données de bâtiments depuis Google Open Buildings")
    
    # Chargement des pays pour la sélection
    countries_gdf = load_countries()
    
    if countries_gdf is not None:
        st.sidebar.success(f"✅ {len(countries_gdf)} pays chargés")
    
    regions_list = prepare_regions(countries_gdf)
    
    # Interface à onglets
    tab1, tab2 = st.tabs(["🌍 Sélection par Pays", "📐 Coordonnées (BBox)"])
    
    mode = None
    choice = ""
    n = s = e = w = 0.0
    
    with tab1:
        st.markdown("### Sélectionner un pays")
        source_name = st.selectbox(
            "Source des frontières :",
            ["Natural Earth (High Res 10m)", "World Bank (High Res)"],
            help="Natural Earth est recommandé pour la plupart des cas"
        )
        choice = st.selectbox("Pays :", regions_list, key="country_select")
        if choice and choice != "":
            mode = "country"
            st.info(f"📍 Sélection : {choice}")
    
    with tab2:
        st.markdown("### Entrer des coordonnées manuelles")
        st.info("📍 Obtenez les coordonnées sur [bboxfinder.com](http://bboxfinder.com)")
        
        col1, col2 = st.columns(2)
        with col1:
            n = st.number_input("🔼 Nord (Latitude Max)", value=0.0, format="%.6f", step=0.1, key="north")
            s = st.number_input("🔽 Sud (Latitude Min)", value=0.0, format="%.6f", step=0.1, key="south")
        with col2:
            e = st.number_input("➡️ Est (Longitude Max)", value=0.0, format="%.6f", step=0.1, key="east")
            w = st.number_input("⬅️ Ouest (Longitude Min)", value=0.0, format="%.6f", step=0.1, key="west")
        
        # Si au moins une coordonnée non nulle, passer en mode bbox
        if any([n != 0.0, s != 0.0, e != 0.0, w != 0.0]):
            if mode != "country":  # Ne pas écraser si un pays est sélectionné
                mode = "bbox"
                st.info(f"📍 BBox : Nord={n}, Sud={s}, Est={e}, Ouest={w}")

    # Bouton d'extraction
    if st.button("🚀 Extraire les données", type="primary", use_container_width=True):
        if not mode:
            st.warning("⚠️ Veuillez sélectionner un pays OU entrer des coordonnées")
            return
        
        try:
            geom = None
            name = ""
            
            # Mode Pays
            if mode == "country":
                st.info(f"🌍 Mode : Sélection par pays - {choice}")
                
                # Extraire le code ISO du choix
                iso_code = choice.split('(')[-1].strip(')')
                
                # Charger le shapefile source
                url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
                if "World Bank" in source_name:
                    url = "https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip"
                
                with st.spinner("📥 Téléchargement du shapefile des frontières..."):
                    full_gdf = fetch_and_extract_shapefile(url)
                
                if full_gdf is None:
                    st.error("❌ Impossible de charger le shapefile")
                    return
                
                # Trouver la colonne ISO
                iso_col = find_iso_column(full_gdf)
                
                if not iso_col:
                    st.error(f"❌ Aucune colonne ISO trouvée. Colonnes disponibles : {list(full_gdf.columns)}")
                    return
                
                st.info(f"🔍 Recherche du code {iso_code} dans la colonne {iso_col}")
                
                # Filtrer le pays
                target_gdf = full_gdf[full_gdf[iso_col] == iso_code]
                
                if target_gdf.empty:
                    st.error(f"❌ Code ISO '{iso_code}' non trouvé dans {source_name}")
                    with st.expander("🔎 Voir les 20 premiers codes disponibles"):
                        st.write(sorted(full_gdf[iso_col].unique()[:20]))
                    return
                
                geom = target_gdf.dissolve().iloc[0].geometry
                name = iso_code
                st.success(f"✅ Pays trouvé : {choice}")
            
            # Mode BBox
            elif mode == "bbox":
                if n <= s or e <= w:
                    st.error("❌ Coordonnées invalides : Nord > Sud et Est > Ouest")
                    return
                
                st.info(f"📐 Mode : BBox personnalisée")
                geom = box(w, s, e, n)
                name = f"custom_{abs(hash(f'{n}{s}{e}{w}'))}"
                st.success("✅ Zone définie")
            
            # Extraction des données
            st.markdown("---")
            st.subheader("📥 Téléchargement des données Open Buildings")
            
            tokens = get_s2_tokens(geom)
            st.info(f"🔢 **{len(tokens)}** tuiles S2 à traiter")
            
            all_data = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            buildings_found = 0
            
            for i, token in enumerate(tokens):
                status_text.text(f"⏳ Traitement {i+1}/{len(tokens)} - Tuile {token}")
                
                csv_url = os.path.join(BUILDING_DOWNLOAD_PATH, f'{token}_buildings.csv.gz')
                
                try:
                    with tf.io.gfile.GFile(csv_url, 'rb') as gf:
                        df = pd.read_csv(gf, header=None, compression='gzip')
                        
                        if len(df.columns) >= 3:
                            # Colonnes : latitude, longitude, geometry_wkt
                            gdf_chunk = gpd.GeoDataFrame(
                                df,
                                geometry=gpd.GeoSeries.from_wkt(df[2]),
                                crs='EPSG:4326'
                            )
                            
                            # Filtrage spatial
                            gdf_chunk = gdf_chunk[gdf_chunk.intersects(geom)]
                            
                            if not gdf_chunk.empty:
                                all_data.append(gdf_chunk)
                                buildings_found += len(gdf_chunk)
                                status_text.text(f"✅ Tuile {i+1}/{len(tokens)} : {len(gdf_chunk)} bâtiments (Total : {buildings_found})")
                
                except Exception as e:
                    # Tuile vide ou erreur, on continue
                    pass
                
                progress_bar.progress((i + 1) / len(tokens))
            
            status_text.empty()
            progress_bar.empty()
            
            # Résultats
            if not all_data:
                st.warning("⚠️ Aucun bâtiment trouvé dans cette zone")
                st.info("Cela peut signifier :\n- La zone est vide\n- Les données ne sont pas disponibles\n- Les coordonnées sont incorrectes")
            else:
                final_gdf = pd.concat(all_data, ignore_index=True)
                st.success(f"🎉 **{len(final_gdf):,} bâtiments** extraits avec succès !")
                
                # Statistiques
                col1, col2, col3 = st.columns(3)
                col1.metric("🏗️ Bâtiments", f"{len(final_gdf):,}")
                col2.metric("🗂️ Tuiles traitées", len(tokens))
                col3.metric("✅ Tuiles avec données", len(all_data))
                
                # Export
                out_path = f"{name}_buildings.geojson"
                final_gdf.to_file(out_path, driver="GeoJSON")
                
                with open(out_path, "rb") as f:
                    st.download_button(
                        label="💾 Télécharger le GeoJSON",
                        data=f,
                        file_name=out_path,
                        mime="application/geo+json",
                        use_container_width=True
                    )
                
                # Aperçu des données
                with st.expander("👁️ Aperçu des 10 premiers bâtiments"):
                    st.dataframe(final_gdf.head(10))
                
                # Nettoyage
                try:
                    os.remove(out_path)
                except:
                    pass
        
        except Exception as e:
            st.error(f"❌ Erreur système : {e}")
            import traceback
            with st.expander("🔍 Détails de l'erreur"):
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
