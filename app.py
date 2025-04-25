# Load the countries.geojson file
countries_gdf = gpd.read_file("https://github.com/pratisig/Openbuildings/blob/d1fdfcff0a004f154c92db6a32362a55ed8384d0/countries.geojson")

# Print the column names
print(countries_gdf.columns)

# Print the first few rows to see the data
print(countries_gdf.head())
