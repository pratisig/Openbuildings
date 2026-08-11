"""Module d'export unifié.

Chaque ancien projet réécrivait son exporteur : `Openbuildings` (Shapefile ZIP
+ GeoPackage via GeoPandas), `Carto-facileSN` (PNG/PDF matplotlib), les apps
Streamlit (téléchargements ad hoc). Ici un service unique qui accepte
n'importe quelle FeatureCollection produite par la plateforme.

Les formats GeoJSON, CSV et GeoJSONL n'ont aucune dépendance ; GeoPackage,
Shapefile et GeoParquet s'appuient sur GeoPandas s'il est installé.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from ..config import settings

log = logging.getLogger("pratisig.exports")
router = APIRouter(prefix="/api/exports", tags=["exports"])

try:
    import geopandas  # noqa: F401

    GEOPANDAS = True
except ImportError:  # pragma: no cover
    GEOPANDAS = False

FORMATS: dict[str, dict[str, Any]] = {
    "geojson": {
        "label": "GeoJSON",
        "extension": "geojson",
        "media_type": "application/geo+json",
        "requires_geopandas": False,
        "description": "Format universel, lisible partout.",
    },
    "geojsonl": {
        "label": "GeoJSON Lines",
        "extension": "geojsonl",
        "media_type": "application/x-ndjson",
        "requires_geopandas": False,
        "description": "Une entité par ligne, adapté aux gros volumes en flux.",
    },
    "csv": {
        "label": "CSV (WKT)",
        "extension": "csv",
        "media_type": "text/csv",
        "requires_geopandas": False,
        "description": "Tableur, géométrie en colonne WKT.",
    },
    "wkt": {
        "label": "WKT",
        "extension": "wkt",
        "media_type": "text/plain",
        "requires_geopandas": False,
        "description": "Une géométrie Well-Known Text par ligne.",
    },
    "kml": {
        "label": "KML",
        "extension": "kml",
        "media_type": "application/vnd.google-earth.kml+xml",
        "requires_geopandas": False,
        "description": "Compatible Google Earth et de nombreux logiciels SIG.",
    },
    "gpkg": {
        "label": "GeoPackage",
        "extension": "gpkg",
        "media_type": "application/geopackage+sqlite3",
        "requires_geopandas": True,
        "description": "Recommandé pour les SIG : un seul fichier, pas de limite de noms.",
    },
    "shapefile": {
        "label": "Shapefile (ZIP)",
        "extension": "zip",
        "media_type": "application/zip",
        "requires_geopandas": True,
        "description": "Compatibilité maximale, noms d'attributs tronqués à 10 caractères.",
    },
    "geoparquet": {
        "label": "GeoParquet",
        "extension": "parquet",
        "media_type": "application/vnd.apache.parquet",
        "requires_geopandas": True,
        "description": "Format cloud-native, compact et rapide.",
    },
}


class ExportRequest(BaseModel):
    format: str = Field("geojson", description="Voir /api/exports/formats")
    data: dict[str, Any] = Field(..., description="FeatureCollection à exporter")
    filename: str = Field("export", max_length=80)
    layer_name: str = Field("data", max_length=50)


def _sanitize(name: str) -> str:
    keep = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
    return (keep.strip("_") or "export")[:80]


def _features_or_400(data: dict[str, Any]) -> list[dict[str, Any]]:
    if data.get("type") == "Feature":
        features = [data]
    else:
        features = data.get("features") or []
    if not features:
        raise HTTPException(400, "Aucune entité à exporter")
    if len(features) > settings.max_export_features:
        raise HTTPException(
            400, f"Export limité à {settings.max_export_features} entités ({len(features)} fournies)"
        )
    return features


def _geometry_to_wkt(geometry: dict[str, Any] | None) -> str:
    """Conversion GeoJSON → WKT sans dépendance."""
    if not geometry:
        return ""
    gtype = geometry.get("type", "").upper()
    coords = geometry.get("coordinates")

    def pt(c) -> str:
        return " ".join(str(round(float(v), 7)) for v in c[:2])

    def ring(r) -> str:
        return "(" + ", ".join(pt(c) for c in r) + ")"

    def poly(p) -> str:
        return "(" + ", ".join(ring(r) for r in p) + ")"

    try:
        if gtype == "POINT":
            return f"POINT ({pt(coords)})"
        if gtype == "MULTIPOINT":
            return "MULTIPOINT (" + ", ".join(pt(c) for c in coords) + ")"
        if gtype == "LINESTRING":
            return f"LINESTRING {ring(coords)}"
        if gtype == "MULTILINESTRING":
            return "MULTILINESTRING (" + ", ".join(ring(r) for r in coords) + ")"
        if gtype == "POLYGON":
            return f"POLYGON {poly(coords)}"
        if gtype == "MULTIPOLYGON":
            return "MULTIPOLYGON (" + ", ".join(poly(p) for p in coords) + ")"
        if gtype == "GEOMETRYCOLLECTION":
            inner = ", ".join(_geometry_to_wkt(g) for g in geometry.get("geometries", []))
            return f"GEOMETRYCOLLECTION ({inner})"
    except (TypeError, ValueError, IndexError):
        return ""
    return ""


def _to_csv(features: list[dict[str, Any]]) -> bytes:
    columns: list[str] = []
    for f in features:
        for key in (f.get("properties") or {}):
            if key not in columns:
                columns.append(key)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([*columns, "geometry_wkt"])
    for f in features:
        props = f.get("properties") or {}
        row = []
        for col in columns:
            value = props.get(col)
            row.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
        row.append(_geometry_to_wkt(f.get("geometry")))
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def _to_geojsonl(features: list[dict[str, Any]]) -> bytes:
    lines = (json.dumps(f, ensure_ascii=False, default=str) for f in features)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _to_wkt(features: list[dict[str, Any]]) -> bytes:
    lines = (_geometry_to_wkt(feature.get("geometry")) for feature in features)
    return ("\n".join(line for line in lines if line) + "\n").encode("utf-8")


def _kml_geometry(parent: ET.Element, geometry: dict[str, Any]) -> None:
    """Ajoute une géométrie GeoJSON à un Placemark KML."""
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    def coordinates_text(values: list[list[float]]) -> str:
        return " ".join(f"{point[0]},{point[1]}" for point in values)

    if geometry_type == "Point":
        node = ET.SubElement(parent, "Point")
        ET.SubElement(node, "coordinates").text = f"{coordinates[0]},{coordinates[1]}"
    elif geometry_type == "LineString":
        node = ET.SubElement(parent, "LineString")
        ET.SubElement(node, "coordinates").text = coordinates_text(coordinates)
    elif geometry_type == "Polygon":
        node = ET.SubElement(parent, "Polygon")
        for index, ring in enumerate(coordinates):
            boundary = ET.SubElement(node, "outerBoundaryIs" if index == 0 else "innerBoundaryIs")
            linear_ring = ET.SubElement(boundary, "LinearRing")
            ET.SubElement(linear_ring, "coordinates").text = coordinates_text(ring)
    elif geometry_type in {"MultiPoint", "MultiLineString", "MultiPolygon"}:
        multi = ET.SubElement(parent, "MultiGeometry")
        child_type = geometry_type.removeprefix("Multi")
        for child_coordinates in coordinates:
            _kml_geometry(multi, {"type": child_type, "coordinates": child_coordinates})
    elif geometry_type == "GeometryCollection":
        multi = ET.SubElement(parent, "MultiGeometry")
        for child in geometry.get("geometries") or []:
            _kml_geometry(multi, child)


def _to_kml(features: list[dict[str, Any]], name: str) -> bytes:
    namespace = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}kml")
    document = ET.SubElement(root, "Document")
    ET.SubElement(document, "name").text = name

    for index, feature in enumerate(features, 1):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        placemark = ET.SubElement(document, "Placemark")
        properties = feature.get("properties") or {}
        ET.SubElement(placemark, "name").text = str(properties.get("name") or f"Entité {index}")
        if properties:
            extended = ET.SubElement(placemark, "ExtendedData")
            for key, value in properties.items():
                data = ET.SubElement(extended, "Data", name=str(key))
                ET.SubElement(data, "value").text = (
                    json.dumps(value, ensure_ascii=False, default=str)
                    if isinstance(value, (dict, list))
                    else str(value if value is not None else "")
                )
        _kml_geometry(placemark, geometry)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _to_geopandas(features: list[dict[str, Any]], fmt: str, name: str) -> bytes:
    if not GEOPANDAS:
        raise HTTPException(
            501,
            f"Le format {FORMATS[fmt]['label']} nécessite GeoPandas côté serveur "
            "(pip install 'pratisig-api[geo]'). Utilisez GeoJSON ou CSV.",
        )
    import geopandas as gpd

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    if gdf.empty:
        raise HTTPException(400, "Aucune géométrie valide à exporter")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if fmt == "gpkg":
            target = tmp_path / f"{name}.gpkg"
            gdf.to_file(target, driver="GPKG", layer=name)
            return target.read_bytes()

        if fmt == "geoparquet":
            target = tmp_path / f"{name}.parquet"
            gdf.to_parquet(target)
            return target.read_bytes()

        # Shapefile : noms d'attributs limités à 10 caractères
        renamed = gdf.rename(columns={c: c[:10] for c in gdf.columns if c != "geometry"})
        shp_dir = tmp_path / name
        shp_dir.mkdir()
        renamed.to_file(shp_dir / f"{name}.shp", driver="ESRI Shapefile", encoding="utf-8")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in shp_dir.iterdir():
                archive.write(path, path.name)
        return buffer.getvalue()


@router.get("/formats", summary="Formats d'export disponibles")
def formats() -> dict[str, Any]:
    return {
        "formats": [
            {
                "id": key,
                **meta,
                "available": (not meta["requires_geopandas"]) or GEOPANDAS,
            }
            for key, meta in FORMATS.items()
        ],
        "geopandas_available": GEOPANDAS,
        "max_features": settings.max_export_features,
    }


@router.post("/create", summary="Exporter une couche")
def create(payload: ExportRequest) -> Response:
    fmt = payload.format.lower()
    if fmt not in FORMATS:
        raise HTTPException(404, f"Format inconnu. Disponibles : {list(FORMATS)}")

    features = _features_or_400(payload.data)
    meta = FORMATS[fmt]
    name = _sanitize(payload.filename)
    layer = _sanitize(payload.layer_name)

    if fmt == "geojson":
        content = json.dumps(
            {"type": "FeatureCollection", "features": features}, ensure_ascii=False, default=str
        ).encode("utf-8")
    elif fmt == "geojsonl":
        content = _to_geojsonl(features)
    elif fmt == "csv":
        content = _to_csv(features)
    elif fmt == "wkt":
        content = _to_wkt(features)
    elif fmt == "kml":
        content = _to_kml(features, layer)
    else:
        content = _to_geopandas(features, fmt, layer)

    filename = f"{name}.{meta['extension']}"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=meta["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Feature-Count": str(len(features)),
        },
    )
