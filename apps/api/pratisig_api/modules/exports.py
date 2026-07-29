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
