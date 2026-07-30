# Génère une distribution Windows portable dans dist\OpenBuildings\.
# À lancer depuis PowerShell, à la racine du dépôt :
#   .\scripts\build_windows_portable.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

$python = ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt pyinstaller

# --onedir est volontaire : Streamlit, GDAL et GeoPandas s'exécutent de façon
# bien plus fiable sous Windows dans un dossier portable que dans un unique EXE.
& $python -m PyInstaller --noconfirm --clean --onedir --name OpenBuildings `
    --add-data "app.py;." `
    --add-data "countries.geojson;." `
    --collect-all streamlit `
    --collect-all streamlit_folium `
    --collect-all folium `
    launcher.py

Write-Host ""
Write-Host "Distribution créée : $PWD\dist\OpenBuildings" -ForegroundColor Green
Write-Host "Exécutez dist\OpenBuildings\OpenBuildings.exe puis ouvrez http://localhost:8501" -ForegroundColor Green
