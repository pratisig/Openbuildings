import gzip
import tempfile
from google.cloud import storage
import pandas as pd

def download_building_data(region_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Télécharge et filtre les données des bâtiments pour la région donnée."""
    # Initialiser le client Google Cloud Storage
    storage_client = storage.Client.create_anonymous_client()
    bucket_name = 'open-buildings-data'
    bucket = storage_client.bucket(bucket_name)
    
    # Récupérer les tuiles S2 couvrant la région
    region_bounds = region_df.total_bounds
    s2_covering_tokens = get_bounding_box_s2_covering_tokens(region_df.iloc[0].geometry)
    
    # Liste pour stocker les données des bâtiments
    building_data_list = []
    
    for token in s2_covering_tokens:
        blob_name = f'v3/building_data_s2_level_6_gzip_no_header/{token}_buildings.csv.gz'
        blob = bucket.blob(blob_name)
        
        if not blob.exists():
            continue
        
        # Télécharger le fichier CSV.gz temporairement
        with tempfile.NamedTemporaryFile(suffix='.csv.gz', delete=False) as tmp_file:
            blob.download_to_filename(tmp_file.name)
            
            # Lire le fichier CSV.gz
            with gzip.open(tmp_file.name, 'rt') as gz_file:
                df = pd.read_csv(gz_file, header=None, names=['latitude', 'longitude', 'area_in_meters', 'confidence'])
            
            # Convertir en GeoDataFrame
            gdf = gpd.GeoDataFrame(
                df,
                geometry=gpd.points_from_xy(df['longitude'], df['latitude']),
                crs='EPSG:4326'
            )
            
            # Filtrer les bâtiments dans la région
            filtered_gdf = gpd.sjoin(gdf, region_df, predicate='within')
            building_data_list.append(filtered_gdf)
    
    # Concaténer toutes les données filtrées
    if not building_data_list:
        raise ValueError("Aucun bâtiment trouvé dans la région spécifiée.")
    
    return pd.concat(building_data_list, ignore_index=True)
