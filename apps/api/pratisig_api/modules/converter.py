"""Import et normalisation de fichiers géographiques.

Le reste de PratiSIG échange des ``FeatureCollection`` GeoJSON. Ce module sert
donc de porte d'entrée unique aux fichiers externes : les formats texte
courants sont lus sans dépendance lourde et les formats SIG binaires utilisent
GeoPandas lorsqu'il est installé.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import settings

router = APIRouter(prefix="/api/converter", tags=["conversion"])

try:
    import geopandas as gpd

    GEOPANDAS = True
except ImportError:  # pragma: no cover - dépend de l'installation
    GEOPANDAS = False

try:
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping

    SHAPELY = True
except ImportError:  # pragma: no cover - Shapely fait partie du socle actuel
    SHAPELY = False

INPUT_FORMATS: dict[str, dict[str, Any]] = {
    "geojson": {
        "label": "GeoJSON",
        "extensions": [".geojson", ".json"],
        "description": "FeatureCollection, Feature ou géométrie GeoJSON.",
        "requires_geopandas": False,
    },
    "geojsonl": {
        "label": "GeoJSON Lines",
        "extensions": [".geojsonl", ".ndjson"],
        "description": "Une entité GeoJSON par ligne.",
        "requires_geopandas": False,
    },
    "csv": {
        "label": "CSV / TSV",
        "extensions": [".csv", ".tsv"],
        "description": "Colonnes longitude/latitude, lon/lat, x/y ou geometry_wkt.",
        "requires_geopandas": False,
    },
    "kml": {
        "label": "KML",
        "extensions": [".kml"],
        "description": "Repères, lignes, polygones et MultiGeometry KML.",
        "requires_geopandas": False,
    },
    "gpx": {
        "label": "GPX",
        "extensions": [".gpx"],
        "description": "Waypoints, routes et traces GPS.",
        "requires_geopandas": False,
    },
    "wkt": {
        "label": "WKT",
        "extensions": [".wkt", ".txt"],
        "description": "Une géométrie Well-Known Text par ligne.",
        "requires_geopandas": False,
    },
    "gpkg": {
        "label": "GeoPackage",
        "extensions": [".gpkg"],
        "description": "Première couche vectorielle d'un GeoPackage.",
        "requires_geopandas": True,
    },
    "shapefile": {
        "label": "Shapefile (ZIP)",
        "extensions": [".zip"],
        "description": "Archive ZIP contenant au minimum .shp, .shx et .dbf.",
        "requires_geopandas": True,
    },
    "geoparquet": {
        "label": "GeoParquet",
        "extensions": [".parquet", ".geoparquet"],
        "description": "Fichier GeoParquet avec métadonnées géométriques.",
        "requires_geopandas": True,
    },
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Encodage du fichier non reconnu")


def _feature(geometry: dict[str, Any], properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "Feature", "geometry": geometry, "properties": properties or {}}


def _validate_features(features: Any) -> list[dict[str, Any]]:
    if not isinstance(features, list):
        raise HTTPException(400, "La liste d'entités est invalide")

    valid: list[dict[str, Any]] = []
    for item in features:
        if not isinstance(item, dict) or item.get("type") != "Feature":
            raise HTTPException(400, "Chaque élément doit être une Feature GeoJSON")
        geometry = item.get("geometry")
        if geometry is not None and not isinstance(geometry, dict):
            raise HTTPException(400, "Une géométrie GeoJSON est invalide")
        item.setdefault("properties", {})
        valid.append(item)

    if not valid:
        raise HTTPException(400, "Le fichier ne contient aucune entité géographique")
    if len(valid) > settings.max_export_features:
        raise HTTPException(
            400,
            f"Import limité à {settings.max_export_features} entités ({len(valid)} trouvées)",
        )
    return valid


def _parse_geojson(content: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(_decode_text(content))
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"JSON invalide à la ligne {exc.lineno}") from exc

    if isinstance(data, list):
        features = data
    elif not isinstance(data, dict):
        raise HTTPException(400, "Le JSON doit contenir un objet géographique")
    elif data.get("type") == "FeatureCollection":
        features = data.get("features")
    elif data.get("type") == "Feature":
        features = [data]
    elif data.get("type") in {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }:
        features = [_feature(data)]
    else:
        raise HTTPException(400, "Objet GeoJSON non reconnu")
    return _validate_features(features)


def _parse_geojsonl(content: bytes) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for line_number, line in enumerate(_decode_text(content).splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"GeoJSONL invalide à la ligne {line_number}") from exc
        if isinstance(item, dict) and item.get("type") == "FeatureCollection":
            features.extend(item.get("features") or [])
        else:
            features.append(item)
    return _validate_features(features)


def _parse_number(value: Any) -> float:
    text = str(value).strip().replace("\u00a0", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    return float(text)


def _wkt_geometry(value: str) -> dict[str, Any]:
    if not SHAPELY:
        raise HTTPException(501, "La lecture WKT nécessite Shapely côté serveur")
    try:
        geometry = shapely_wkt.loads(value)
    except Exception as exc:
        raise ValueError("géométrie WKT invalide") from exc
    if geometry.is_empty:
        raise ValueError("géométrie WKT vide")
    return mapping(geometry)


def _parse_csv(content: bytes, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
    text = _decode_text(content)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if Path(filename).suffix.lower() == ".tsv" else csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(400, "Le CSV ne contient pas d'en-têtes")

    fields = {str(name).strip().lower(): name for name in reader.fieldnames if name}
    geometry_field = next(
        (fields[key] for key in ("geometry_wkt", "wkt", "geometry", "geom") if key in fields),
        None,
    )
    coordinate_fields = next(
        (
            (fields[lon], fields[lat])
            for lon, lat in (
                ("longitude", "latitude"),
                ("lon", "lat"),
                ("lng", "lat"),
                ("long", "lat"),
                ("x", "y"),
            )
            if lon in fields and lat in fields
        ),
        None,
    )
    if not geometry_field and not coordinate_fields:
        raise HTTPException(
            400,
            "Colonnes géographiques introuvables : utilisez longitude/latitude, lon/lat, x/y ou geometry_wkt",
        )

    features: list[dict[str, Any]] = []
    rejected = 0
    for row in reader:
        if not any(str(value or "").strip() for value in row.values()):
            continue
        try:
            if geometry_field and str(row.get(geometry_field) or "").strip():
                geometry = _wkt_geometry(str(row[geometry_field]))
            elif coordinate_fields:
                lon_field, lat_field = coordinate_fields
                lon = _parse_number(row.get(lon_field))
                lat = _parse_number(row.get(lat_field))
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError("coordonnées hors limites")
                geometry = {"type": "Point", "coordinates": [lon, lat]}
            else:
                raise ValueError("géométrie absente")
        except (TypeError, ValueError):
            rejected += 1
            continue

        properties = {
            str(key): value
            for key, value in row.items()
            if key is not None and key != geometry_field
        }
        features.append(_feature(geometry, properties))

    warnings = []
    if rejected:
        warnings.append(f"{rejected} ligne(s) sans géométrie valide ont été ignorées")
    return _validate_features(features), warnings


def _kml_coordinates(text: str | None) -> list[list[float]]:
    coordinates: list[list[float]] = []
    for token in (text or "").replace("\n", " ").split():
        values = token.split(",")
        if len(values) >= 2:
            coordinates.append([float(values[0]), float(values[1])])
    return coordinates


def _kml_geometry(element: ET.Element) -> dict[str, Any] | None:
    kind = _local_name(element.tag)
    if kind == "Point":
        coord = next((node for node in element.iter() if _local_name(node.tag) == "coordinates"), None)
        values = _kml_coordinates(coord.text if coord is not None else None)
        return {"type": "Point", "coordinates": values[0]} if values else None
    if kind == "LineString":
        coord = next((node for node in element.iter() if _local_name(node.tag) == "coordinates"), None)
        values = _kml_coordinates(coord.text if coord is not None else None)
        return {"type": "LineString", "coordinates": values} if len(values) >= 2 else None
    if kind == "Polygon":
        rings = []
        for ring in (node for node in element.iter() if _local_name(node.tag) == "LinearRing"):
            coord = next((node for node in ring.iter() if _local_name(node.tag) == "coordinates"), None)
            values = _kml_coordinates(coord.text if coord is not None else None)
            if len(values) >= 3:
                if values[0] != values[-1]:
                    values.append(values[0])
                rings.append(values)
        return {"type": "Polygon", "coordinates": rings} if rings else None
    if kind == "MultiGeometry":
        geometries = [
            geometry
            for child in element
            if (geometry := _kml_geometry(child)) is not None
        ]
        if len(geometries) == 1:
            return geometries[0]
        return {"type": "GeometryCollection", "geometries": geometries} if geometries else None
    return None


def _parse_kml(content: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise HTTPException(400, "Fichier KML/XML invalide") from exc

    features: list[dict[str, Any]] = []
    for placemark in (node for node in root.iter() if _local_name(node.tag) == "Placemark"):
        properties: dict[str, Any] = {}
        for child in placemark:
            name = _local_name(child.tag)
            if name in {"name", "description"} and child.text:
                properties[name] = child.text.strip()
        for data in (node for node in placemark.iter() if _local_name(node.tag) in {"Data", "SimpleData"}):
            key = data.attrib.get("name")
            value_node = next((node for node in data if _local_name(node.tag) == "value"), None)
            value = value_node.text if value_node is not None else data.text
            if key and value is not None:
                properties[key] = value.strip()

        geometry = next(
            (
                parsed
                for child in placemark
                if _local_name(child.tag) in {"Point", "LineString", "Polygon", "MultiGeometry"}
                and (parsed := _kml_geometry(child)) is not None
            ),
            None,
        )
        if geometry:
            features.append(_feature(geometry, properties))
    return _validate_features(features)


def _child_text(element: ET.Element, wanted: str) -> str | None:
    child = next((node for node in element if _local_name(node.tag) == wanted), None)
    return child.text.strip() if child is not None and child.text else None


def _gpx_point(element: ET.Element) -> list[float]:
    return [float(element.attrib["lon"]), float(element.attrib["lat"])]


def _parse_gpx(content: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise HTTPException(400, "Fichier GPX/XML invalide") from exc

    features: list[dict[str, Any]] = []
    for waypoint in (node for node in root.iter() if _local_name(node.tag) == "wpt"):
        props = {"name": _child_text(waypoint, "name")} if _child_text(waypoint, "name") else {}
        features.append(_feature({"type": "Point", "coordinates": _gpx_point(waypoint)}, props))

    for route in (node for node in root.iter() if _local_name(node.tag) == "rte"):
        coordinates = [_gpx_point(node) for node in route if _local_name(node.tag) == "rtept"]
        if len(coordinates) >= 2:
            props = {"name": _child_text(route, "name")} if _child_text(route, "name") else {}
            props["gpx_type"] = "route"
            features.append(_feature({"type": "LineString", "coordinates": coordinates}, props))

    for track in (node for node in root.iter() if _local_name(node.tag) == "trk"):
        name = _child_text(track, "name")
        for index, segment in enumerate(
            (node for node in track.iter() if _local_name(node.tag) == "trkseg"), 1
        ):
            coordinates = [_gpx_point(node) for node in segment if _local_name(node.tag) == "trkpt"]
            if len(coordinates) >= 2:
                props: dict[str, Any] = {"gpx_type": "track", "segment": index}
                if name:
                    props["name"] = name
                features.append(_feature({"type": "LineString", "coordinates": coordinates}, props))
    return _validate_features(features)


def _parse_wkt(content: bytes) -> list[dict[str, Any]]:
    features = []
    for line_number, line in enumerate(_decode_text(content).splitlines(), 1):
        value = line.strip()
        if not value:
            continue
        try:
            features.append(_feature(_wkt_geometry(value), {"line": line_number}))
        except ValueError as exc:
            raise HTTPException(400, f"WKT invalide à la ligne {line_number}") from exc
    return _validate_features(features)


def _validate_shapefile_archive(content: bytes) -> None:
    """Refuse les ZIP incomplets, chiffrés ou démesurés avant de les passer à GDAL."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "Archive Shapefile ZIP invalide") from exc

    if not members or len(members) > 1_000:
        raise HTTPException(400, "Archive Shapefile vide ou contenant trop de fichiers")
    if any(member.flag_bits & 0x1 for member in members):
        raise HTTPException(400, "Les archives Shapefile chiffrées ne sont pas acceptées")
    if sum(member.file_size for member in members) > settings.max_import_bytes * 5:
        raise HTTPException(413, "Contenu décompressé du Shapefile trop volumineux")
    if any(".." in Path(member.filename).parts or Path(member.filename).is_absolute() for member in members):
        raise HTTPException(400, "Chemin non sûr dans l'archive Shapefile")

    stems_by_extension: dict[str, set[str]] = {extension: set() for extension in (".shp", ".shx", ".dbf")}
    for member in members:
        path = Path(member.filename)
        extension = path.suffix.lower()
        if extension in stems_by_extension:
            stems_by_extension[extension].add(str(path.with_suffix("")))
    complete_layers = set.intersection(*stems_by_extension.values())
    if not complete_layers:
        raise HTTPException(400, "Le ZIP doit contenir les fichiers .shp, .shx et .dbf d'une même couche")


def _parse_geopandas(content: bytes, filename: str, input_format: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not GEOPANDAS:
        raise HTTPException(
            501,
            f"Le format {INPUT_FORMATS[input_format]['label']} nécessite GeoPandas côté serveur "
            "(pip install -r apps/api/requirements-full.txt).",
        )

    if input_format == "shapefile":
        _validate_shapefile_archive(content)

    warnings: list[str] = []
    suffix = Path(filename).suffix.lower() or INPUT_FORMATS[input_format]["extensions"][0]
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"import{suffix}"
        target.write_bytes(content)
        try:
            if input_format == "geoparquet":
                frame = gpd.read_parquet(target)
            elif input_format == "shapefile":
                frame = gpd.read_file(f"zip://{target}")
            else:
                frame = gpd.read_file(target)
        except Exception as exc:
            raise HTTPException(400, f"Impossible de lire ce {INPUT_FORMATS[input_format]['label']}: {exc}") from exc

        if frame.empty:
            raise HTTPException(400, "Le fichier ne contient aucune entité")
        if frame.crs is None:
            warnings.append("CRS absent : les coordonnées sont supposées être en WGS 84 (EPSG:4326)")
            frame = frame.set_crs("EPSG:4326")
        elif frame.crs.to_epsg() != 4326:
            frame = frame.to_crs("EPSG:4326")
        data = json.loads(frame.to_json(drop_id=True, to_wgs84=True))
    return _validate_features(data.get("features")), warnings


def _detect_format(filename: str, requested: str | None) -> str:
    if requested:
        value = requested.lower().strip()
        if value not in INPUT_FORMATS:
            raise HTTPException(404, f"Format d'entrée inconnu : {requested}")
        return value
    suffix = Path(filename).suffix.lower()
    for format_id, meta in INPUT_FORMATS.items():
        if suffix in meta["extensions"]:
            return format_id
    raise HTTPException(
        400,
        f"Extension {suffix or '(absente)'} non reconnue. Formats : {', '.join(INPUT_FORMATS)}",
    )


def _summary(features: list[dict[str, Any]]) -> dict[str, Any]:
    geometry_types = sorted(
        {
            feature.get("geometry", {}).get("type")
            for feature in features
            if feature.get("geometry")
        }
    )
    attributes: list[str] = []
    for feature in features[:100]:
        for key in (feature.get("properties") or {}):
            if key not in attributes:
                attributes.append(key)
    return {"feature_count": len(features), "geometry_types": geometry_types, "attributes": attributes}


@router.get("/formats", summary="Formats de fichiers importables")
def formats() -> dict[str, Any]:
    return {
        "formats": [
            {
                "id": format_id,
                **meta,
                "available": not meta["requires_geopandas"] or GEOPANDAS,
            }
            for format_id, meta in INPUT_FORMATS.items()
        ],
        "max_upload_bytes": settings.max_import_bytes,
        "max_features": settings.max_export_features,
        "geopandas_available": GEOPANDAS,
    }


@router.post("/import", summary="Importer et normaliser un fichier en GeoJSON")
async def import_file(
    file: UploadFile = File(..., description="Fichier géographique à convertir"),
    input_format: str | None = Form(None, description="Détection automatique si omis"),
) -> dict[str, Any]:
    filename = Path(file.filename or "import").name
    format_id = _detect_format(filename, input_format)
    content = await file.read(settings.max_import_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(400, "Le fichier est vide")
    if len(content) > settings.max_import_bytes:
        limit_mb = settings.max_import_bytes // (1024 * 1024)
        raise HTTPException(413, f"Fichier trop volumineux (maximum {limit_mb} Mo)")

    warnings: list[str] = []
    if format_id == "geojson":
        features = _parse_geojson(content)
    elif format_id == "geojsonl":
        features = _parse_geojsonl(content)
    elif format_id == "csv":
        features, warnings = _parse_csv(content, filename)
    elif format_id == "kml":
        features = _parse_kml(content)
    elif format_id == "gpx":
        features = _parse_gpx(content)
    elif format_id == "wkt":
        features = _parse_wkt(content)
    else:
        features, warnings = _parse_geopandas(content, filename, format_id)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source_filename": filename,
            "input_format": format_id,
            "crs": "EPSG:4326",
            "warnings": warnings,
            **_summary(features),
        },
    }
