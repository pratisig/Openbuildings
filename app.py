# Load the countries.geojson file
countries_gdf = gpd.read_file("countries.geojson")

# Print the column names
print(countries_gdf.columns)

# Print the first few rows to see the data
print(countries_gdf.head())
