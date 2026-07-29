"""Tests du socle géométrique partagé."""

from __future__ import annotations

import math

import pytest

from pratisig_api.core.geo import (
    BBox,
    GeoError,
    as_geometry,
    centroid,
    circle_polygon,
    geometry_area_m2,
    geometry_length_m,
    haversine_m,
    iter_coordinates,
    meters_to_degrees,
    point_in_polygon,
)

DAKAR = (-17.4467, 14.6928)
THIES = (-16.9246, 14.7886)

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-17.5, 14.6], [-17.4, 14.6], [-17.4, 14.7], [-17.5, 14.7], [-17.5, 14.6]]],
}


class TestBBox:
    def test_valid(self):
        bbox = BBox(-17.5, 14.6, -17.4, 14.7)
        assert bbox.center == pytest.approx((-17.45, 14.65))
        assert bbox.contains(-17.45, 14.65)
        assert not bbox.contains(0, 0)

    def test_rejects_inverted(self):
        with pytest.raises(GeoError):
            BBox(-17.4, 14.6, -17.5, 14.7)

    def test_rejects_out_of_bounds(self):
        with pytest.raises(GeoError):
            BBox(-200, 14.6, -17.4, 14.7)

    def test_from_list_requires_four(self):
        with pytest.raises(GeoError):
            BBox.from_list([1, 2, 3])

    def test_from_center_is_symmetric(self):
        bbox = BBox.from_center(DAKAR[0], DAKAR[1], 1000)
        assert bbox.center == pytest.approx(DAKAR, abs=1e-9)
        # 1 km de rayon → environ 2 km de large
        width_m = haversine_m(bbox.xmin, DAKAR[1], bbox.xmax, DAKAR[1])
        assert width_m == pytest.approx(2000, rel=0.02)

    def test_from_geojson(self):
        bbox = BBox.from_geojson(SQUARE)
        assert bbox.to_list() == [-17.5, 14.6, -17.4, 14.7]

    def test_expand(self):
        bbox = BBox(-17.5, 14.6, -17.4, 14.7).expand(0.5)
        assert bbox.xmin == pytest.approx(-17.55)
        assert bbox.xmax == pytest.approx(-17.35)

    def test_area_km2_positive(self):
        # 0.1° × 0.1° vers 14.65°N ≈ 10,7 km × 11,1 km
        area = BBox(-17.5, 14.6, -17.4, 14.7).area_km2
        assert 100 < area < 140

    def test_to_polygon_is_closed(self):
        ring = BBox(-17.5, 14.6, -17.4, 14.7).to_polygon()["coordinates"][0]
        assert ring[0] == ring[-1]
        assert len(ring) == 5


class TestConversions:
    def test_meters_to_degrees_widens_near_poles(self):
        lon_eq, _ = meters_to_degrees(1000, 0)
        lon_high, _ = meters_to_degrees(1000, 60)
        assert lon_high > lon_eq * 1.9  # 1/cos(60°) = 2

    def test_haversine_known_distance(self):
        # Dakar → Thiès, environ 57 km
        distance = haversine_m(*DAKAR, *THIES)
        assert 55_000 < distance < 60_000

    def test_haversine_zero(self):
        assert haversine_m(*DAKAR, *DAKAR) == pytest.approx(0, abs=1e-6)


class TestGeometryOps:
    def test_iter_coordinates_nested(self):
        coords = list(iter_coordinates(SQUARE))
        assert len(coords) == 5
        assert coords[0] == [-17.5, 14.6]

    def test_iter_coordinates_feature_collection(self):
        fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": SQUARE}]}
        assert len(list(iter_coordinates(fc))) == 5

    def test_area_of_square(self):
        # ~0,1° × 0,1° à 14,65°N ≈ 119 km²
        area_km2 = geometry_area_m2(SQUARE) / 1e6
        assert 100 < area_km2 < 140

    def test_area_of_line_is_zero(self):
        assert geometry_area_m2({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}) == 0

    def test_area_subtracts_holes(self):
        with_hole = {
            "type": "Polygon",
            "coordinates": [
                SQUARE["coordinates"][0],
                [[-17.48, 14.62], [-17.42, 14.62], [-17.42, 14.68], [-17.48, 14.68], [-17.48, 14.62]],
            ],
        }
        assert geometry_area_m2(with_hole) < geometry_area_m2(SQUARE)

    def test_length_of_line(self):
        line = {"type": "LineString", "coordinates": [list(DAKAR), list(THIES)]}
        assert geometry_length_m(line) == pytest.approx(haversine_m(*DAKAR, *THIES), rel=1e-6)

    def test_centroid(self):
        lon, lat = centroid(SQUARE)
        assert lon == pytest.approx(-17.45, abs=0.01)
        assert lat == pytest.approx(14.65, abs=0.01)

    def test_centroid_empty_raises(self):
        with pytest.raises(GeoError):
            centroid({"type": "Polygon", "coordinates": []})


class TestPointInPolygon:
    def test_inside(self):
        assert point_in_polygon(-17.45, 14.65, SQUARE)

    def test_outside(self):
        assert not point_in_polygon(-16.0, 14.65, SQUARE)

    def test_hole_is_excluded(self):
        with_hole = {
            "type": "Polygon",
            "coordinates": [
                SQUARE["coordinates"][0],
                [[-17.48, 14.62], [-17.42, 14.62], [-17.42, 14.68], [-17.48, 14.68], [-17.48, 14.62]],
            ],
        }
        assert not point_in_polygon(-17.45, 14.65, with_hole)
        assert point_in_polygon(-17.495, 14.605, with_hole)

    def test_multipolygon(self):
        multi = {
            "type": "MultiPolygon",
            "coordinates": [
                SQUARE["coordinates"],
                [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            ],
        }
        assert point_in_polygon(-17.45, 14.65, multi)
        assert point_in_polygon(0.5, 0.5, multi)
        assert not point_in_polygon(5, 5, multi)


class TestCirclePolygon:
    def test_closed_ring(self):
        ring = circle_polygon(*DAKAR, 1000, steps=32)["coordinates"][0]
        assert ring[0] == ring[-1]
        assert len(ring) == 33

    def test_radius_respected(self):
        ring = circle_polygon(*DAKAR, 1000, steps=8)["coordinates"][0]
        distances = [haversine_m(*DAKAR, p[0], p[1]) for p in ring[:-1]]
        assert all(900 < d < 1100 for d in distances), distances


class TestAsGeometry:
    def test_from_feature(self):
        assert as_geometry({"type": "Feature", "geometry": SQUARE}) == SQUARE

    def test_from_single_feature_collection(self):
        fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": SQUARE}]}
        assert as_geometry(fc) == SQUARE

    def test_from_multi_feature_collection(self):
        fc = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": SQUARE}, {"type": "Feature", "geometry": SQUARE}],
        }
        assert as_geometry(fc)["type"] == "GeometryCollection"

    def test_rejects_unknown(self):
        with pytest.raises(GeoError):
            as_geometry({"type": "Banana"})

    def test_rejects_empty_collection(self):
        with pytest.raises(GeoError):
            as_geometry({"type": "FeatureCollection", "features": []})


class TestCentroidAccuracy:
    """Le centroïde des polygones doit être surfacique, pas une moyenne de sommets."""

    def test_square_centroid_is_exact(self):
        lon, lat = centroid(SQUARE)
        assert lon == pytest.approx(-17.45, abs=1e-9)
        assert lat == pytest.approx(14.65, abs=1e-9)

    def test_unaffected_by_extra_vertices(self):
        """Densifier un côté ne doit pas déplacer le centroïde (le bug corrigé)."""
        dense = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-17.5, 14.6],
                    [-17.48, 14.6],
                    [-17.46, 14.6],
                    [-17.44, 14.6],
                    [-17.4, 14.6],
                    [-17.4, 14.7],
                    [-17.5, 14.7],
                    [-17.5, 14.6],
                ]
            ],
        }
        assert centroid(dense) == pytest.approx(centroid(SQUARE), abs=1e-9)

    def test_l_shape_centroid_inside_bbox(self):
        l_shape = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2], [0, 0]]],
        }
        lon, lat = centroid(l_shape)
        assert 0 < lon < 2 and 0 < lat < 2
        assert lon == pytest.approx(lat, abs=1e-9)  # forme symétrique sur la diagonale

    def test_multipolygon_weighted_by_area(self):
        multi = {
            "type": "MultiPolygon",
            "coordinates": [
                [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],  # grand carré, centre (1,1)
                [[[10, 10], [10.1, 10], [10.1, 10.1], [10, 10.1], [10, 10]]],  # petit
            ],
        }
        lon, lat = centroid(multi)
        assert lon < 2, "le grand polygone doit dominer"

    def test_point_centroid_is_itself(self):
        assert centroid({"type": "Point", "coordinates": [-17.4, 14.7]}) == (-17.4, 14.7)

    def test_closed_line_ignores_duplicate_vertex(self):
        line = {"type": "LineString", "coordinates": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]}
        assert centroid(line) == pytest.approx((1.0, 1.0), abs=1e-9)
