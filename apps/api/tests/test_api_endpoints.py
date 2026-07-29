"""Tests d'intégration de l'API (sans accès réseau externe)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from pratisig_api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


POINTS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-17.44, 14.69]},
            "properties": {"name": "École A", "eleves": 320},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-17.46, 14.71]},
            "properties": {"name": "École B", "eleves": 145},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-16.90, 14.80]},
            "properties": {"name": "École C", "eleves": 210},
        },
    ],
}

ZONE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-17.50, 14.65], [-17.42, 14.65], [-17.42, 14.73], [-17.50, 14.73], [-17.50, 14.65]]
                ],
            },
            "properties": {"zone": "Dakar centre"},
        }
    ],
}


class TestSystem:
    def test_root_lists_modules(self, client):
        data = client.get("/").json()
        assert data["platform"].startswith("PratiSIG")
        assert "buildings" in data["modules"]
        assert "flood" in data["modules"]

    def test_health_reports_services(self, client):
        data = client.get("/health").json()
        assert data["status"] in ("ok", "degraded")
        for service in ("duckdb", "earthengine", "shapely", "geopandas", "llm"):
            assert service in data["services"]
            assert data["services"][service]["status"] in ("ok", "degraded", "unavailable")

    def test_openapi_is_valid(self, client):
        spec = client.get("/openapi.json").json()
        assert spec["info"]["title"]
        assert len(spec["paths"]) > 25


class TestCatalog:
    def test_catalog_lists_all_modules(self, client):
        data = client.get("/api/catalog").json()
        assert data["count"] == len(data["modules"])
        ids = {m["id"] for m in data["modules"]}
        assert {"buildings", "overture", "osm", "admin", "routing", "flood"} <= ids

    def test_every_module_declares_origin(self, client):
        for module in client.get("/api/catalog").json()["modules"]:
            assert module["origin"], f"{module['id']} sans dépôt d'origine"
            assert module["summary"]
            assert module["endpoints"]

    def test_module_detail(self, client):
        data = client.get("/api/catalog/modules/buildings").json()
        assert data["id"] == "buildings"
        assert "pratisig/Openbuildings" in data["origin"]

    def test_unknown_module(self, client):
        data = client.get("/api/catalog/modules/inexistant").json()
        assert "error" in data

    def test_migration_covers_15_repos(self, client):
        data = client.get("/api/catalog/migration").json()
        assert data["count"] == 15, "les 15 dépôts d'origine doivent être tracés"
        assert data["personnels"] + data["forks"] + data["inaccessibles"] == 15
        for entry in data["sources"]:
            assert entry["repo"].startswith("pratisig/")
            assert entry["destination"]


class TestSpatial:
    def test_operations_listed(self, client):
        data = client.get("/api/spatial/operations").json()
        ids = {op["id"] for op in data["operations"]}
        assert {"buffer", "clip", "centroid", "stats", "points_in_polygon"} <= ids

    def test_stats_with_attribute(self, client):
        r = client.post(
            "/api/spatial/run",
            json={"operation": "stats", "layer_a": POINTS, "params": {"attribute": "eleves"}},
        )
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["count"] == 3
        assert result["attribute"]["sum"] == 675
        assert result["attribute"]["min"] == 145
        assert result["attribute"]["max"] == 320

    def test_centroid_preserves_count(self, client):
        r = client.post("/api/spatial/run", json={"operation": "centroid", "layer_a": POINTS})
        assert r.status_code == 200
        assert r.json()["metadata"]["output_count"] == 3

    def test_buffer_requires_radius(self, client):
        r = client.post("/api/spatial/run", json={"operation": "buffer", "layer_a": POINTS})
        assert r.status_code == 400
        assert "radius_m" in r.json()["detail"]

    def test_buffer_produces_polygons(self, client):
        r = client.post(
            "/api/spatial/run",
            json={"operation": "buffer", "layer_a": POINTS, "params": {"radius_m": 500}},
        )
        assert r.status_code == 200
        for feature in r.json()["features"]:
            assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_clip_keeps_only_inside(self, client):
        r = client.post(
            "/api/spatial/run", json={"operation": "clip", "layer_a": POINTS, "layer_b": ZONE}
        )
        assert r.status_code == 200
        # École C (Thiès) est hors de la zone de Dakar
        assert r.json()["metadata"]["output_count"] == 2

    def test_points_in_polygon_counts(self, client):
        r = client.post(
            "/api/spatial/run",
            json={"operation": "points_in_polygon", "layer_a": POINTS, "layer_b": ZONE},
        )
        assert r.status_code == 200
        props = r.json()["features"][0]["properties"]
        assert props["point_count"] == 2
        assert props["density_per_km2"] is not None

    def test_convex_hull(self, client):
        r = client.post("/api/spatial/run", json={"operation": "convex_hull", "layer_a": POINTS})
        assert r.status_code == 200
        assert r.json()["features"][0]["geometry"]["type"] == "Polygon"

    def test_binary_op_requires_layer_b(self, client):
        r = client.post("/api/spatial/run", json={"operation": "clip", "layer_a": POINTS})
        assert r.status_code == 400

    def test_unknown_operation(self, client):
        r = client.post("/api/spatial/run", json={"operation": "teleport", "layer_a": POINTS})
        assert r.status_code == 404

    def test_empty_layer_rejected(self, client):
        r = client.post(
            "/api/spatial/run",
            json={"operation": "stats", "layer_a": {"type": "FeatureCollection", "features": []}},
        )
        assert r.status_code == 400


class TestExports:
    def test_formats_flag_availability(self, client):
        data = client.get("/api/exports/formats").json()
        by_id = {f["id"]: f for f in data["formats"]}
        assert by_id["geojson"]["available"] is True
        assert by_id["csv"]["available"] is True
        assert by_id["gpkg"]["available"] == data["geopandas_available"]

    def test_geojson_roundtrip(self, client):
        r = client.post(
            "/api/exports/create", json={"format": "geojson", "data": POINTS, "filename": "ecoles"}
        )
        assert r.status_code == 200
        assert 'filename="ecoles.geojson"' in r.headers["content-disposition"]
        assert r.headers["x-feature-count"] == "3"
        parsed = json.loads(r.content)
        assert len(parsed["features"]) == 3

    def test_csv_contains_wkt_and_headers(self, client):
        r = client.post("/api/exports/create", json={"format": "csv", "data": POINTS})
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert "geometry_wkt" in text
        assert "POINT (-17.44 14.69)" in text
        assert "École A" in text

    def test_geojsonl_one_line_per_feature(self, client):
        r = client.post("/api/exports/create", json={"format": "geojsonl", "data": POINTS})
        lines = [l for l in r.content.decode().splitlines() if l.strip()]
        assert len(lines) == 3
        assert json.loads(lines[0])["type"] == "Feature"

    def test_filename_is_sanitized(self, client):
        r = client.post(
            "/api/exports/create",
            json={"format": "geojson", "data": POINTS, "filename": "../../etc/passwd"},
        )
        assert r.status_code == 200
        assert ".." not in r.headers["content-disposition"]
        assert "/" not in r.headers["content-disposition"].split("filename=")[1]

    def test_unknown_format(self, client):
        r = client.post("/api/exports/create", json={"format": "dwg", "data": POINTS})
        assert r.status_code == 404

    def test_empty_data_rejected(self, client):
        r = client.post(
            "/api/exports/create",
            json={"format": "geojson", "data": {"type": "FeatureCollection", "features": []}},
        )
        assert r.status_code == 400

    def test_geopandas_formats_degrade_cleanly(self, client):
        from pratisig_api.modules.exports import GEOPANDAS

        r = client.post("/api/exports/create", json={"format": "gpkg", "data": POINTS})
        if GEOPANDAS:
            assert r.status_code == 200
        else:
            assert r.status_code == 501
            assert "GeoPandas" in r.json()["detail"]


class TestValidation:
    def test_area_requires_a_selector(self, client):
        r = client.post("/api/overture/query", json={"theme": "places", "area": {}})
        assert r.status_code == 422

    def test_center_requires_radius(self, client):
        r = client.post(
            "/api/overture/query", json={"theme": "places", "area": {"center": [-17.4, 14.7]}}
        )
        assert r.status_code == 422

    def test_invalid_bbox_rejected(self, client):
        r = client.post(
            "/api/overture/query", json={"theme": "places", "area": {"bbox": [-200, 14, -17, 15]}}
        )
        assert r.status_code == 422

    def test_unknown_theme(self, client):
        r = client.post(
            "/api/overture/query",
            json={"theme": "licornes", "area": {"bbox": [-17.5, 14.6, -17.4, 14.7]}},
        )
        assert r.status_code == 404

    def test_unknown_osm_preset(self, client):
        r = client.post(
            "/api/osm/query",
            json={"preset": "chateaux", "area": {"bbox": [-17.5, 14.6, -17.4, 14.7]}},
        )
        assert r.status_code == 404

    def test_osm_rejects_huge_area(self, client):
        r = client.post(
            "/api/osm/query", json={"preset": "roads_all", "area": {"bbox": [-30, 0, 10, 30]}}
        )
        assert r.status_code == 400
        assert "trop vaste" in r.json()["detail"]

    def test_climate_rejects_bad_dates(self, client):
        r = client.post(
            "/api/climate/timeseries",
            json={"latitude": 14.7, "longitude": -17.4, "start": "2024-12-01", "end": "2024-01-01"},
        )
        assert r.status_code == 422

    def test_climate_rejects_unknown_parameter(self, client):
        r = client.post(
            "/api/climate/timeseries",
            json={
                "latitude": 14.7,
                "longitude": -17.4,
                "start": "2024-01-01",
                "end": "2024-02-01",
                "parameters": ["MAGIE"],
            },
        )
        assert r.status_code == 422

    def test_routing_rejects_single_waypoint(self, client):
        r = client.post("/api/routing/route", json={"waypoints": [[-17.4, 14.7]]})
        assert r.status_code == 422


class TestReferenceData:
    def test_countries_loaded(self, client):
        data = client.get("/api/buildings/countries").json()
        assert data["count"] > 150
        senegal = next((c for c in data["countries"] if c["iso3"] == "SEN"), None)
        assert senegal is not None
        assert "bbox" in senegal

    def test_countries_search(self, client):
        data = client.get("/api/buildings/countries", params={"q": "sene"}).json()
        assert any(c["iso3"] == "SEN" for c in data["countries"])

    def test_country_detail_has_parquet_url(self, client):
        data = client.get("/api/buildings/countries/SEN").json()
        assert data["parquet_url"].endswith("SEN.parquet")

    def test_unknown_country(self, client):
        assert client.get("/api/buildings/countries/XYZ").status_code == 404

    def test_senegal_levels(self, client):
        data = client.get("/api/admin/senegal").json()
        ids = {lvl["id"] for lvl in data["levels"]}
        assert ids == {"regions", "departements", "arrondissements", "communes"}

    def test_unknown_senegal_level(self, client):
        assert client.get("/api/admin/senegal/quartiers").status_code == 404


class TestServiceDegradation:
    def test_agent_without_key_returns_503(self, client):
        r = client.post("/api/agent/chat", json={"messages": [{"role": "user", "content": "salut"}]})
        assert r.status_code == 503
        assert "PRATISIG_LLM" in r.json()["detail"]

    def test_agent_tools_always_documented(self, client):
        data = client.get("/api/agent/tools").json()
        names = {t["name"] for t in data["tools"]}
        assert {"geocode", "query_overture", "query_buildings", "compute_route"} <= names

    def test_raster_without_gee_returns_503(self, client):
        r = client.post(
            "/api/raster/tiles",
            json={
                "dataset": "sentinel2",
                "index": "NDVI",
                "area": {"bbox": [-17.5, 14.6, -17.4, 14.7]},
                "date_start": "2024-01-01",
                "date_end": "2024-03-01",
            },
        )
        assert r.status_code in (503, 500)

    def test_flood_status_is_honest(self, client):
        data = client.get("/api/flood/status").json()
        assert isinstance(data["available"], bool)
        assert "COPERNICUS/S1_GRD" in data["datasets"]


class TestCache:
    def test_clear_endpoint(self, client):
        r = client.post("/api/cache/clear", params={"namespace": "test-inexistant"})
        assert r.status_code == 200
        assert r.json()["cleared"] == 0
