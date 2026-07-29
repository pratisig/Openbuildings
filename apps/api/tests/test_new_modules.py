"""Tests des modules issus des dépôts rendus accessibles.

Couvre `agriculture` (AGRISIGHT + AgriSight_v2), `land` (terracheck-senegal)
et les améliorations d'isochrone (sante-isochrones-app).
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from pratisig_api.main import app
from pratisig_api.modules.agriculture import (
    CROPS,
    agro_zone_for,
    growing_degree_days,
    phenological_stage,
    stress_indices,
    water_balance,
    yield_potential,
)
from pratisig_api.modules.land import WEIGHTS, _compute_score
from pratisig_api.modules.routing import _alpha_shape, _area_km2, _hull_polygon


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ─────────────────────────────────────────────────────────────────
# Agriculture — AGRISIGHT × AgriSight_v2
# ─────────────────────────────────────────────────────────────────
class TestCropDatabase:
    def test_crops_merged_from_both_repos(self, client):
        data = client.get("/api/agriculture/crops").json()
        ids = {c["id"] for c in data["crops"]}
        # Cultures communes aux deux dépôts
        assert {"mil", "sorgho", "mais", "riz", "arachide", "niebe"} <= ids
        # Cultures présentes uniquement dans AgriSight_v2
        assert {"manioc", "tomate", "oignon", "coton"} <= ids

    def test_every_crop_has_both_sources_fields(self, client):
        """Chaque culture combine les champs d'AGRISIGHT et d'AgriSight_v2."""
        for crop in client.get("/api/agriculture/crops").json()["crops"]:
            # AGRISIGHT : paramètres thermiques et phénologiques
            assert crop["base_temp"] < crop["opt_temp"] < crop["max_temp"]
            assert crop["cycle_days"] > 0
            assert len(crop["stages"]) >= 4
            # AgriSight_v2 : seuils pluviométriques, rendement, sols
            assert crop["rain_min"] < crop["rain_max"]
            assert crop["yield_max_t_ha"] > 0
            assert crop["soils"]
            assert 0 < crop["ndvi_optimal"] <= 1

    def test_crop_detail(self, client):
        data = client.get("/api/agriculture/crops/riz").json()
        assert data["label"] == "Riz"
        assert data["water_need"] == "très élevé"
        assert "argileux" in data["soils"]

    def test_unknown_crop(self, client):
        assert client.get("/api/agriculture/crops/quinoa").status_code == 404

    def test_zones_and_soils(self, client):
        data = client.get("/api/agriculture/zones").json()
        assert len(data["agro_zones"]) == 5
        assert "sableux" in data["soil_types"]


class TestAgronomicCalculations:
    def test_gdd_accumulates(self):
        temps = [20.0, 25.0, 30.0]
        gdd = growing_degree_days(temps, base_temp=10.0)
        assert gdd == [10.0, 25.0, 45.0]

    def test_gdd_ignores_below_base(self):
        """Sous la température de base, aucune croissance n'est comptée."""
        assert growing_degree_days([5.0, 5.0], base_temp=10.0) == [0.0, 0.0]

    def test_gdd_handles_missing_values(self):
        gdd = growing_degree_days([20.0, None, 20.0], base_temp=10.0)
        assert gdd == [10.0, 10.0, 20.0]

    def test_phenological_stage_progression(self):
        stages = CROPS["mil"]["stages"]
        first, progress_low = phenological_stage(0, 1000, stages)
        last, progress_high = phenological_stage(1000, 1000, stages)
        assert first == stages[0]
        assert progress_low == 0.0
        assert last == stages[-1]
        assert progress_high == 100.0

    def test_phenological_stage_capped(self):
        """Un dépassement thermique ne produit pas plus de 100 % de progression."""
        _, progress = phenological_stage(5000, 1000, CROPS["mil"]["stages"])
        assert progress == 100.0

    def test_water_balance_deficit(self):
        crop = CROPS["riz"]  # kc élevé
        balance = water_balance([1.0] * 100, crop, eto_daily=5.0)
        assert balance["etc_mm"] == pytest.approx(5.0 * 100 * crop["kc"])
        assert balance["deficit_mm"] > 0
        assert balance["irrigation_needed"] is True

    def test_water_balance_surplus(self):
        crop = CROPS["niebe"]  # kc faible
        balance = water_balance([50.0] * 100, crop, eto_daily=5.0)
        assert balance["deficit_mm"] == 0
        assert balance["irrigation_needed"] is False
        assert balance["satisfaction_pct"] == 100.0

    def test_stress_detects_heat(self):
        crop = CROPS["mil"]
        hot = [crop["max_temp"] + 5] * 10
        stress = stress_indices(hot, [10.0] * 10, crop)
        assert stress["heat"] == 100.0

    def test_stress_detects_cold(self):
        crop = CROPS["mil"]
        cold = [crop["base_temp"] - 5] * 10
        stress = stress_indices(cold, [10.0] * 10, crop)
        assert stress["cold"] == 100.0

    def test_stress_none_in_optimal_range(self):
        crop = CROPS["mil"]
        stress = stress_indices([crop["opt_temp"]] * 10, [100.0] * 10, crop)
        assert stress["heat"] == 0.0
        assert stress["cold"] == 0.0

    def test_yield_bounded_by_max(self):
        crop = CROPS["mais"]
        result = yield_potential(999_999, 999_999, crop)
        assert result["estimated_t_ha"] <= crop["yield_max_t_ha"]
        assert result["ratio_pct"] == 100.0

    def test_yield_zero_without_inputs(self):
        result = yield_potential(0, 0, CROPS["mais"])
        assert result["estimated_t_ha"] == 0.0

    def test_yield_weights_thermal_over_hydric(self):
        """La pondération est 60 % thermique / 40 % hydrique."""
        crop = CROPS["mil"]
        gdd_target = crop["cycle_days"] * (crop["opt_temp"] - crop["base_temp"]) * 0.8
        thermal_only = yield_potential(gdd_target, 0, crop)
        hydric_only = yield_potential(0, crop["water_req_mm"], crop)
        assert thermal_only["estimated_t_ha"] > hydric_only["estimated_t_ha"]

    def test_agro_zone_boundaries(self):
        assert agro_zone_for(200)["id"] == "sahel"
        assert agro_zone_for(500)["id"] == "sahelo_soudanien"
        assert agro_zone_for(750)["id"] == "soudanien"
        assert agro_zone_for(1500)["id"] == "guineen"


class TestAgricultureValidation:
    def test_unknown_crop_rejected(self, client):
        r = client.post(
            "/api/agriculture/season",
            json={"crop": "quinoa", "latitude": 14.7, "longitude": -17.4, "sowing_date": "2024-07-01"},
        )
        assert r.status_code == 422

    def test_bad_date_rejected(self, client):
        r = client.post(
            "/api/agriculture/season",
            json={"crop": "mil", "latitude": 14.7, "longitude": -17.4, "sowing_date": "01/07/2024"},
        )
        assert r.status_code == 422

    def test_unknown_soil_rejected(self, client):
        r = client.post(
            "/api/agriculture/season",
            json={
                "crop": "mil",
                "latitude": 14.7,
                "longitude": -17.4,
                "sowing_date": "2024-07-01",
                "soil": "lunaire",
            },
        )
        assert r.status_code == 422

    def test_vegetation_endpoint_refuses_simulation(self, client):
        """AGRISIGHT simulait le NDVI : la plateforme redirige vers le raster réel."""
        r = client.post("/api/agriculture/vegetation", json={})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "raster" in detail
        assert "simul" in detail.lower()


# ─────────────────────────────────────────────────────────────────
# Foncier — terracheck-senegal
# ─────────────────────────────────────────────────────────────────
class TestLandScoring:
    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_full_coverage(self):
        result = _compute_score({k: 80.0 for k in WEIGHTS})
        assert result["total"] == 80.0
        assert result["coverage_pct"] == 100.0
        assert result["missing"] == []

    def test_weight_redistribution(self):
        """Une composante absente voit son poids réparti, pas compté comme zéro."""
        partial = _compute_score({
            "flood": 80.0,
            "topography": 80.0,
            "landcover": None,
            "accessibility": None,
            "services": None,
            "travel": 80.0,
        })
        # Toutes les composantes présentes valent 80 → le total doit rester 80
        assert partial["total"] == 80.0
        assert partial["coverage_pct"] < 100.0
        assert sum(partial["weights_applied"].values()) == pytest.approx(1.0)

    def test_missing_is_not_penalised_as_zero(self):
        """Vérifie explicitement le défaut que TerraCheck évitait."""
        with_null = _compute_score({
            "flood": 90.0, "topography": 90.0, "landcover": None,
            "accessibility": None, "services": None, "travel": 90.0,
        })
        as_zero = (90 * 0.30 + 90 * 0.15 + 0 + 0 + 0 + 90 * 0.10)
        assert with_null["total"] > as_zero

    def test_no_data_returns_indeterminate(self):
        result = _compute_score({k: None for k in WEIGHTS})
        assert result["total"] is None
        assert result["label"] == "indéterminé"
        assert result["coverage_pct"] == 0.0

    def test_score_labels_thresholds(self):
        assert _compute_score({k: 95.0 for k in WEIGHTS})["label"] == "excellent"
        assert _compute_score({k: 60.0 for k in WEIGHTS})["label"] == "bon"
        assert _compute_score({k: 40.0 for k in WEIGHTS})["label"] == "moyen"
        assert _compute_score({k: 25.0 for k in WEIGHTS})["label"] == "faible"
        assert _compute_score({k: 5.0 for k in WEIGHTS})["label"] == "critique"

    def test_score_bounded(self):
        assert _compute_score({k: 200.0 for k in WEIGHTS})["total"] <= 100
        assert _compute_score({k: -50.0 for k in WEIGHTS})["total"] >= 0

    def test_criteria_endpoint(self, client):
        data = client.get("/api/land/criteria").json()
        assert sum(data["weights"].values()) == pytest.approx(1.0)
        assert "eau" in data["landcover_classes"]
        assert data["landcover_classes"]["eau"]["buildable"] is False

    def test_references_include_west_africa(self, client):
        ids = {c["id"] for c in client.get("/api/land/references").json()["cities"]}
        assert {"dakar", "thies", "saint-louis", "bamako"} <= ids

    def test_compare_requires_two_parcels(self, client):
        r = client.post(
            "/api/land/compare",
            json={"parcels": [{"latitude": 14.7, "longitude": -17.4}]},
        )
        assert r.status_code == 422

    def test_coordinates_validated(self, client):
        r = client.post("/api/land/analyze", json={"latitude": 200, "longitude": -17.4})
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────
# Isochrones — sante-isochrones-app
# ─────────────────────────────────────────────────────────────────
def _lobed_front(n: int = 72) -> list[tuple[float, float]]:
    """Front d'isochrone en lobes, typique d'un réseau routier étoilé."""
    lon0, lat0 = -17.44, 14.69
    cos_lat = math.cos(math.radians(lat0))
    points = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        radius = 0.02 * (0.45 + 0.55 * abs(math.cos(2 * angle)))
        points.append((lon0 + radius * math.cos(angle) / cos_lat, lat0 + radius * math.sin(angle)))
    return points


def _u_shape() -> list[tuple[float, float]]:
    """Zone en U réellement surfacique (deux branches + une base)."""
    points = []
    step = 0.004
    x = -17.48
    while x <= -17.40001:
        y = 14.66
        while y <= 14.72001:
            if y < 14.68 or x < -17.465 or x > -17.415:
                points.append((x, y))
            y += step
        x += step
    return points


class TestIsochroneGeometry:
    def test_alpha_shape_returns_closed_ring(self):
        geom = _alpha_shape(_lobed_front(), 1.0)
        assert geom is not None
        ring = geom["coordinates"][0]
        assert ring[0] == ring[-1]
        assert len(ring) >= 4

    def test_alpha_shape_is_concave(self):
        """Sur une forme en U, l'alpha-shape doit creuser l'échancrure."""
        points = _u_shape()
        alpha_geom = _alpha_shape(points, 1.5)
        hull_geom = _hull_polygon(-17.44, 14.69, points)
        assert alpha_geom is not None
        assert _area_km2(alpha_geom) < _area_km2(hull_geom) * 0.8

    def test_alpha_shape_never_exceeds_hull(self):
        points = _lobed_front()
        hull_area = _area_km2(_hull_polygon(-17.44, 14.69, points))
        for alpha in (0.3, 0.5, 1.0, 1.5):
            geom = _alpha_shape(points, alpha)
            if geom is not None:
                assert _area_km2(geom) <= hull_area * 1.01

    def test_degenerate_alpha_falls_back(self):
        """Un alpha trop élevé renvoie None plutôt qu'une aire absurde.

        Régression : le chaînage manuel d'arêtes renvoyait auparavant une
        boucle partielle, produisant 0,16 km² au lieu de ~11 km².
        """
        points = _lobed_front()
        hull_area = _area_km2(_hull_polygon(-17.44, 14.69, points))
        for alpha in (2.0, 3.0, 5.0):
            geom = _alpha_shape(points, alpha)
            if geom is not None:
                assert _area_km2(geom) > hull_area * 0.15

    def test_alpha_shape_needs_enough_points(self):
        assert _alpha_shape([(0, 0), (1, 0), (0, 1)], 1.0) is None

    def test_area_is_metric_not_degrees(self):
        """Mesurer en degrés donnerait une valeur absurde (bug corrigé)."""
        geom = _hull_polygon(-17.44, 14.69, _lobed_front())
        area = _area_km2(geom)
        assert 1 < area < 100, f"aire hors échelle plausible : {area}"

    def test_isochrone_validates_input(self, client):
        r = client.post("/api/routing/isochrone", json={"center": [-17.44]})
        assert r.status_code == 422

    def test_isochrone_rejects_bad_shape(self, client):
        r = client.post(
            "/api/routing/isochrone",
            json={"center": [-17.44, 14.69], "minutes": [10], "shape": "triangle"},
        )
        assert r.status_code == 422

    def test_isochrone_rejects_bad_alpha(self, client):
        r = client.post(
            "/api/routing/isochrone",
            json={"center": [-17.44, 14.69], "minutes": [10], "alpha": 99},
        )
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────
# Projection UTM — sante-isochrones-app
# ─────────────────────────────────────────────────────────────────
class TestProjection:
    def test_utm_zone_for_dakar(self):
        from pratisig_api.core.projection import utm_epsg

        assert utm_epsg(-17.44, 14.69) == 32628  # UTM 28N

    def test_utm_zone_southern_hemisphere(self):
        from pratisig_api.core.projection import utm_epsg

        assert utm_epsg(30.0, -25.0) == 32736  # UTM 36S

    def test_utm_label(self):
        from pratisig_api.core.projection import utm_label

        assert "28N" in utm_label(32628)
        assert "36S" in utm_label(32736)

    def test_utm_rejects_out_of_bounds(self):
        from pratisig_api.core.projection import utm_epsg

        with pytest.raises(ValueError):
            utm_epsg(500, 14.69)

    def test_local_projector_roundtrip(self):
        from pratisig_api.core.projection import local_projector

        forward, inverse = local_projector(-17.44, 14.69)
        x, y = forward(-17.43, 14.70)
        lon, lat = inverse(x, y)
        assert lon == pytest.approx(-17.43, abs=1e-9)
        assert lat == pytest.approx(14.70, abs=1e-9)

    def test_local_projector_distance_is_metric(self):
        from pratisig_api.core.geo import haversine_m
        from pratisig_api.core.projection import local_projector

        forward, _ = local_projector(-17.44, 14.69)
        x, y = forward(-17.43, 14.69)
        expected = haversine_m(-17.44, 14.69, -17.43, 14.69)
        assert math.hypot(x, y) == pytest.approx(expected, rel=0.01)


# ─────────────────────────────────────────────────────────────────
# Catalogue mis à jour
# ─────────────────────────────────────────────────────────────────
class TestCatalogUpdated:
    def test_new_modules_registered(self, client):
        ids = {m["id"] for m in client.get("/api/catalog").json()["modules"]}
        assert "agriculture" in ids
        assert "land" in ids

    def test_only_zone_remains_inaccessible(self, client):
        data = client.get("/api/catalog/migration").json()
        assert data["count"] == 15
        inaccessible = [s for s in data["sources"] if s["type"] == "inaccessible"]
        assert len(inaccessible) == 1
        assert inaccessible[0]["repo"] == "pratisig/Zone"

    def test_recovered_repos_have_real_destinations(self, client):
        data = client.get("/api/catalog/migration").json()
        recovered = {
            "pratisig/AGRISIGHT",
            "pratisig/AgriSight_v2",
            "pratisig/terracheck-senegal",
            "pratisig/sante-isochrones-app",
        }
        for source in data["sources"]:
            if source["repo"] in recovered:
                assert source["type"] == "personnel"
                assert source["destination"] != "—"
                assert len(source["role_origine"]) > 40, "le rôle doit être documenté"

    def test_all_modules_reachable(self, client):
        """Chaque module du catalogue expose au moins un endpoint GET vivant."""
        spec = client.get("/openapi.json").json()
        paths = set(spec["paths"])
        for module in client.get("/api/catalog").json()["modules"]:
            prefix = f"/api/{module['id']}"
            if module["id"] == "geocoding":
                prefix = "/api/geocoding"
            assert any(p.startswith(prefix) for p in paths), f"{module['id']} sans route"
