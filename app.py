import os
import tempfile
import zipfile
import geopandas as gpd
import pandas as pd
import requests
import streamlit as st
from shapely.geometry import box
from io import BytesIO
import open_buildings as ob

# Configuration
st.set_page_config(page_title="Open Buildings Downloader", layout="wide")

@st.cache_data
def load_countries():
    """Charge le GeoJSON des pays depuis le fichier local"""
    geojson_path = "countries.geojson"
    
    if not os.path.exists(geojson_path):
        st.error(f"❌ Fichier {geojson_path} non trouvé")
        return None
    
    try:
        gdf = gpd.read_file(geojson_path)
        return gdf
    except Exception as e:
        st.error(f"Erreur chargement GeoJSON : {e}")
        return None

@st.cache_data
def fetch_and_extract_shapefile(url: str) -> gpd.GeoDataFrame:
    """Télécharge et extrait un shapefile depuis une URL (avec cache)"""
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
    
    name_col = 'name' if 'name' in countries_gdf.columns else None
    iso_col = None
    
    if 'ISO3166-1-Alpha-3' in countries_gdf.columns:
        iso_col = 'ISO3166-1-Alpha-3'
    elif 'ISO3166-1-Alpha-2' in countries_gdf.columns:
        iso_col = 'ISO3166-1-Alpha-2'
    
    if not name_col or not iso_col:
        return [""] + [f"Zone {i}" for i in range(len(countries_gdf))]
    
    regions = []
    for _, row in countries_gdf.iterrows():
        iso_val = str(row[iso_col]).strip()
        name_val = str(row[name_col]).strip()
        if iso_val and iso_val != 'nan' and name_val and name_val != 'nan':
            regions.append(f"{name_val} ({iso_val})")
    
    return [""] + sorted(regions)

def find_iso_column(gdf):
    """Trouve la colonne ISO dans un GeoDataFrame"""
    iso_columns = ['ISO_A3', 'ISO3', 'ADM0_A3', 'WB_A3', 'ISO_A2', 'ISO3166-1-Alpha-3', 'ISO3166-1-Alpha-2']
    
    for col in gdf.columns:
        if col in iso_columns:
            return col
    return None

def create_shapefile_zip(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée un ZIP contenant le shapefile"""
    with tempfile.TemporaryDirectory() as temp_dir:
        shp_path = os.path.join(temp_dir, f"{base_name}.shp")
        
        # Limitation des noms de colonnes à 10 caractères pour shapefile
        gdf_copy = gdf.copy()
        gdf_copy.columns = [col[:10] if col != 'geometry' else col for col in gdf_copy.columns]
        gdf_copy.to_file(shp_path, driver="ESRI Shapefile")
        
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for ext in ['.shp', '.shx', '.dbf', '.prj', '.cpg']:
                file_path = os.path.join(temp_dir, f"{base_name}{ext}")
                if os.path.exists(file_path):
                    zip_file.write(file_path, f"{base_name}{ext}")
        
        return zip_buffer.getvalue()

def create_geopackage(gdf: gpd.GeoDataFrame, base_name: str) -> bytes:
    """Crée un fichier GeoPackage (SQLite spatial)"""
    with tempfile.TemporaryDirectory() as temp_dir:
        gpkg_path = os.path.join(temp_dir, f"{base_name}.gpkg")
        gdf.to_file(gpkg_path, driver="GPKG", layer="buildings")
        
        with open(gpkg_path, 'rb') as f:
            return f.read()

def main():
    st.title("🏢 Open Buildings Extractor")
    st.markdown("Téléchargez les données de bâtiments depuis Google Open Buildings")
    
    # Sidebar - Paramètres
    with st.sidebar:
        st.header("⚙️ Paramètres")
        
        st.markdown("---")
        
        export_format = st.selectbox(
            "📦 Format d'export",
            ["GeoJSON", "Shapefile (ZIP)", "GeoPackage (GPKG)", "CSV"],
            help="GeoJSON : universel\nShapefile : compatible SIG\nGeoPackage : SQLite spatial\nCSV : données brutes"
        )
        
        simplify_geom = st.checkbox(
            "Simplifier les géométries",
            value=False,
            help="Réduit la précision pour alléger le fichier (recommandé pour > 50k bâtiments)"
        )
        
        if simplify_geom:
            tolerance = st.slider(
                "Tolérance de simplification",
                min_value=0.00001,
                max_value=0.0001,
                value=0.00001,
                format="%.5f",
                help="Plus la valeur est élevée, plus la simplification est forte"
            )
        
        st.markdown("---")
        st.markdown("### 💡 Astuces")
        st.markdown("""
        - **open-buildings** : Utilise la bibliothèque officielle
        - **Formats optimisés** : GPKG pour grandes zones
        - **CSV** : Données brutes avec WKT
        """)
    
    # Chargement des pays
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
            help="Natural Earth est recommandé"
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
            n = st.number_input("🔼 Nord (Lat Max)", value=0.0, format="%.6f", step=0.1, key="north")
            s = st.number_input("🔽 Sud (Lat Min)", value=0.0, format="%.6f", step=0.1, key="south")
        with col2:
            e = st.number_input("➡️ Est (Lon Max)", value=0.0, format="%.6f", step=0.1, key="east")
            w = st.number_input("⬅️ Ouest (Lon Min)", value=0.0, format="%.6f", step=0.1, key="west")
        
        if any([n != 0.0, s != 0.0, e != 0.0, w != 0.0]):
            if mode != "country":
                mode = "bbox"
                st.info(f"📍 BBox : N={n}, S={s}, E={e}, O={w}")

    # Bouton d'extraction
    if st.button("🚀 Extraire les données", type="primary", use_container_width=True):
        if not mode:
            st.warning("⚠️ Veuillez sélectionner un pays OU entrer des coordonnées")
            return
        
        try:
            geom = None
            name = ""
            region_poly = None
            
            # Mode Pays
            if mode == "country":
                st.info(f"🌍 Mode : Sélection par pays - {choice}")
                
                iso_code = choice.split('(')[-1].strip(')')
                
                url = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
                if "World Bank" in source_name:
                    url = "https://datacatalogfiles.worldbank.org/ddh-published/0038272/DR0046659/wb_countries_admin0_10m.zip"
                
                with st.spinner("📥 Téléchargement des frontières..."):
                    full_gdf = fetch_and_extract_shapefile(url)
                
                if full_gdf is None:
                    st.error("❌ Impossible de charger le shapefile")
                    return
                
                iso_col = find_iso_column(full_gdf)
                
                if not iso_col:
                    st.error(f"❌ Aucune colonne ISO trouvée")
                    return
                
                target_gdf = full_gdf[full_gdf[iso_col] == iso_code]
                
                if target_gdf.empty:
                    st.error(f"❌ Code ISO '{iso_code}' non trouvé")
                    return
                
                geom = target_gdf.dissolve().iloc[0].geometry
                region_poly = geom
                name = iso_code
                st.success(f"✅ Pays trouvé : {choice}")
            
            # Mode BBox
            elif mode == "bbox":
                if n <= s or e <= w:
                    st.error("❌ Coordonnées invalides")
                    return
                
                st.info(f"📐 Mode : BBox personnalisée")
                geom = box(w, s, e, n)
                region_poly = geom
                name = f"custom_{abs(hash(f'{n}{s}{e}{w}'))}"
                st.success("✅ Zone définie")
            
            # Extraction des données avec open-buildings
            st.markdown("---")
            st.subheader("📥 Téléchargement des bâtiments")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            status_text.text("🔍 Téléchargement des bâtiments en cours...")
            
            # Téléchargement avec open-buildings
            try:
                buildings_gdf = ob.download_buildings(
                    region_poly,
                    output_format="GeoDataFrame",
                    max_workers=10
                )
                
                progress_bar.progress(100)
                status_text.empty()
                
            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                st.error(f"❌ Erreur lors du téléchargement : {e}")
                st.info("💡 Essayez avec une zone plus petite ou vérifiez votre connexion")
                return
            
            # Résultats
            if buildings_gdf is None or buildings_gdf.empty:
                st.warning("⚠️ Aucun bâtiment trouvé dans cette zone")
                st.info("Cela peut signifier :\n- Zone vide\n- Données non disponibles\n- Coordonnées incorrectes")
            else:
                # Simplification optionnelle
                if simplify_geom and len(buildings_gdf) > 1000:
                    with st.spinner("🔧 Simplification des géométries..."):
                        buildings_gdf['geometry'] = buildings_gdf['geometry'].simplify(tolerance=tolerance)
                
                st.success(f"🎉 **{len(buildings_gdf):,} bâtiments** extraits !")
                
                # Statistiques
                col1, col2, col3 = st.columns(3)
                col1.metric("🏗️ Bâtiments", f"{len(buildings_gdf):,}")
                
                # Calculer la surface totale si disponible
                if 'area_in_meters' in buildings_gdf.columns:
                    total_area = buildings_gdf['area_in_meters'].sum()
                    col2.metric("📐 Surface totale", f"{total_area:,.0f} m²")
                
                # Confidence moyenne si disponible
                if 'confidence' in buildings_gdf.columns:
                    avg_confidence = buildings_gdf['confidence'].mean()
                    col3.metric("🎯 Confiance moy.", f"{avg_confidence:.2%}")
                
                # Export selon le format choisi
                st.markdown("### 💾 Téléchargement")
                
                if export_format == "GeoJSON":
                    geojson_buffer = BytesIO()
                    buildings_gdf.to_file(geojson_buffer, driver="GeoJSON")
                    
                    st.download_button(
                        label="📥 Télécharger GeoJSON",
                        data=geojson_buffer.getvalue(),
                        file_name=f"{name}_buildings.geojson",
                        mime="application/geo+json",
                        use_container_width=True
                    )
                
                elif export_format == "Shapefile (ZIP)":
                    with st.spinner("📦 Création du shapefile..."):
                        shp_zip = create_shapefile_zip(buildings_gdf, f"{name}_buildings")
                    
                    st.download_button(
                        label="📥 Télécharger Shapefile (ZIP)",
                        data=shp_zip,
                        file_name=f"{name}_buildings.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                
                elif export_format == "GeoPackage (GPKG)":
                    with st.spinner("📦 Création du GeoPackage..."):
                        gpkg_data = create_geopackage(buildings_gdf, f"{name}_buildings")
                    
                    st.download_button(
                        label="📥 Télécharger GeoPackage",
                        data=gpkg_data,
                        file_name=f"{name}_buildings.gpkg",
                        mime="application/geopackage+sqlite3",
                        use_container_width=True
                    )
                
                elif export_format == "CSV":
                    csv_buffer = BytesIO()
                    # Convertir geometry en WKT pour CSV
                    df_export = buildings_gdf.copy()
                    df_export['geometry_wkt'] = df_export['geometry'].apply(lambda x: x.wkt)
                    df_export = df_export.drop(columns=['geometry'])
                    df_export.to_csv(csv_buffer, index=False)
                    
                    st.download_button(
                        label="📥 Télécharger CSV",
                        data=csv_buffer.getvalue(),
                        file_name=f"{name}_buildings.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                
                # Aperçu
                with st.expander("👁️ Aperçu des données"):
                    st.dataframe(buildings_gdf.head(10))
                    
                    # Info sur les colonnes
                    st.markdown("**Colonnes disponibles :**")
                    st.write(", ".join(buildings_gdf.columns.tolist()))
                
                # Statistiques avancées
                with st.expander("📊 Statistiques détaillées"):
                    if 'area_in_meters' in buildings_gdf.columns:
                        st.write(f"**Surface min :** {buildings_gdf['area_in_meters'].min():.2f} m²")
                        st.write(f"**Surface max :** {buildings_gdf['area_in_meters'].max():.2f} m²")
                        st.write(f"**Surface moyenne :** {buildings_gdf['area_in_meters'].mean():.2f} m²")
                    
                    if 'confidence' in buildings_gdf.columns:
                        st.write(f"**Confiance min :** {buildings_gdf['confidence'].min():.2%}")
                        st.write(f"**Confiance max :** {buildings_gdf['confidence'].max():.2%}")
        
        except Exception as e:
            st.error(f"❌ Erreur système : {e}")
            import traceback
            with st.expander("🔍 Détails"):
                st.code(traceback.format_exc())

if __name__ == "__main__":
    main()
