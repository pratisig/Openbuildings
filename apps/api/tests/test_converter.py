"""Tests du convertisseur de fichiers et de l'export KML."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from pratisig_api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, filename: str, content: str | bytes, content_type: str = "text/plain"):
    payload = content.encode() if isinstance(content, str) else content
    return client.post(
        "/api/converter/import",
        files={"file": (filename, payload, content_type)},
    )


class TestConverterFormats:
    def test_lists_text_and_optional_formats(self, client):
        data = client.get("/api/converter/formats").json()
        formats = {item["id"]: item for item in data["formats"]}
        assert {"geojson", "csv", "kml", "gpx", "wkt", "gpkg", "shapefile"} <= formats.keys()
        assert formats["geojson"]["available"] is True
        assert formats["gpkg"]["available"] == data["geopandas_available"]
        assert data["max_upload_bytes"] > 0

    def test_unknown_extension_is_rejected(self, client):
        response = upload(client, "dessin.dwg", "binary")
        assert response.status_code == 400
        assert "Extension" in response.json()["detail"]

    def test_empty_file_is_rejected(self, client):
        response = upload(client, "empty.geojson", b"")
        assert response.status_code == 400
        assert "vide" in response.json()["detail"]


class TestTextImports:
    def test_geojson_feature_collection(self, client):
        source = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-17.44, 14.69]},
                    "properties": {"name": "Dakar"},
                }
            ],
        }
        response = upload(client, "lieux.geojson", json.dumps(source), "application/geo+json")
        assert response.status_code == 200
        data = response.json()
        assert data["features"] == source["features"]
        assert data["metadata"]["feature_count"] == 1
        assert data["metadata"]["geometry_types"] == ["Point"]
        assert data["metadata"]["crs"] == "EPSG:4326"

    def test_geojsonl(self, client):
        lines = "\n".join(
            json.dumps(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [index, index]},
                    "properties": {"id": index},
                }
            )
            for index in (1, 2)
        )
        response = upload(client, "points.ndjson", lines)
        assert response.status_code == 200
        assert response.json()["metadata"]["feature_count"] == 2

    def test_semicolon_csv_with_french_decimal_separator(self, client):
        source = "nom;longitude;latitude\nDakar;-17,44;14,69\nThiès;-16,93;14,79\n"
        response = upload(client, "villes.csv", source, "text/csv")
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["feature_count"] == 2
        assert data["features"][0]["geometry"]["coordinates"] == [-17.44, 14.69]
        assert data["features"][0]["properties"]["nom"] == "Dakar"

    def test_csv_wkt_and_rejected_rows_warning(self, client):
        source = 'name,geometry_wkt\nÉcole,"POINT (-17.44 14.69)"\nInvalide,not-wkt\n'
        response = upload(client, "points.csv", source, "text/csv")
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["feature_count"] == 1
        assert data["metadata"]["warnings"]
        assert "1 ligne" in data["metadata"]["warnings"][0]

    def test_kml_points_lines_and_extended_data(self, client):
        source = """<?xml version="1.0"?>
        <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
          <Placemark><name>Dakar</name><ExtendedData><Data name="type"><value>ville</value></Data></ExtendedData>
            <Point><coordinates>-17.44,14.69,0</coordinates></Point></Placemark>
          <Placemark><name>Route</name><LineString><coordinates>-17.44,14.69 -17.3,14.8</coordinates></LineString></Placemark>
        </Document></kml>"""
        response = upload(client, "carte.kml", source, "application/vnd.google-earth.kml+xml")
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["feature_count"] == 2
        assert data["metadata"]["geometry_types"] == ["LineString", "Point"]
        assert data["features"][0]["properties"]["type"] == "ville"

    def test_gpx_waypoint_route_and_track(self, client):
        source = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <wpt lat="14.69" lon="-17.44"><name>Dakar</name></wpt>
          <rte><name>R1</name><rtept lat="14.69" lon="-17.44"/><rtept lat="14.70" lon="-17.40"/></rte>
          <trk><name>T1</name><trkseg><trkpt lat="14.70" lon="-17.40"/><trkpt lat="14.71" lon="-17.39"/></trkseg></trk>
        </gpx>"""
        response = upload(client, "trace.gpx", source, "application/gpx+xml")
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["feature_count"] == 3
        assert {f["properties"].get("gpx_type") for f in data["features"]} == {None, "route", "track"}

    def test_wkt_one_geometry_per_line(self, client):
        response = upload(client, "geometries.wkt", "POINT (-17.44 14.69)\nLINESTRING (0 0, 1 1)\n")
        assert response.status_code == 200
        assert response.json()["metadata"]["feature_count"] == 2


class TestConversionExports:
    def test_exports_one_wkt_geometry_per_line(self, client):
        data = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-17.44, 14.69]}, "properties": {}},
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}, "properties": {}},
            ],
        }
        response = client.post("/api/exports/create", json={"format": "wkt", "data": data})
        assert response.status_code == 200
        assert response.text.splitlines() == ["POINT (-17.44 14.69)", "LINESTRING (0.0 0.0, 1.0 1.0)"]

    def test_exports_valid_kml(self, client):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-17.44, 14.69]},
                    "properties": {"name": "Dakar", "population": 100},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                    "properties": {"name": "Zone"},
                },
            ],
        }
        response = client.post(
            "/api/exports/create",
            json={"format": "kml", "data": data, "filename": "dakar"},
        )
        assert response.status_code == 200
        assert 'filename="dakar.kml"' in response.headers["content-disposition"]
        root = ET.fromstring(response.content)
        assert root.tag.endswith("kml")
        placemarks = [node for node in root.iter() if node.tag.endswith("Placemark")]
        assert len(placemarks) == 2
