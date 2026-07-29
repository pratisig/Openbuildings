"""Utilitaires géospatiaux partagés (sans dépendance lourde).

Rassemble les helpers qui étaient réécrits dans chaque projet :
conversion mètres/degrés, bbox, validation GeoJSON, WKT simple,
calcul de surface et de distance.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

EARTH_RADIUS_M = 6_371_008.8


class GeoError(ValueError):
    """Erreur de validation géométrique."""


@dataclass(frozen=True)
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def __post_init__(self) -> None:
        if self.xmin > self.xmax or self.ymin > self.ymax:
            raise GeoError("BBox invalide : min doit être inférieur à max")
        if not (-180 <= self.xmin <= 180 and -180 <= self.xmax <= 180):
            raise GeoError("Longitudes hors bornes [-180, 180]")
        if not (-90 <= self.ymin <= 90 and -90 <= self.ymax <= 90):
            raise GeoError("Latitudes hors bornes [-90, 90]")

    @classmethod
    def from_list(cls, values: Sequence[float]) -> BBox:
        if len(values) != 4:
            raise GeoError("BBox attendue sous la forme [xmin, ymin, xmax, ymax]")
        return cls(*(float(v) for v in values))

    @classmethod
    def from_center(cls, lon: float, lat: float, radius_m: float) -> BBox:
        dlon, dlat = meters_to_degrees(radius_m, lat)
        return cls(
            max(-180.0, lon - dlon),
            max(-90.0, lat - dlat),
            min(180.0, lon + dlon),
            min(90.0, lat + dlat),
        )

    @classmethod
    def from_geojson(cls, geometry: dict[str, Any]) -> BBox:
        coords = list(iter_coordinates(geometry))
        if not coords:
            raise GeoError("Géométrie sans coordonnées")
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        return cls(min(xs), min(ys), max(xs), max(ys))

    def to_list(self) -> list[float]:
        return [self.xmin, self.ymin, self.xmax, self.ymax]

    def expand(self, ratio: float) -> BBox:
        dx = (self.xmax - self.xmin) * ratio
        dy = (self.ymax - self.ymin) * ratio
        return BBox(
            max(-180.0, self.xmin - dx),
            max(-90.0, self.ymin - dy),
            min(180.0, self.xmax + dx),
            min(90.0, self.ymax + dy),
        )

    @property
    def center(self) -> tuple[float, float]:
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2)

    @property
    def area_km2(self) -> float:
        mid_lat = math.radians((self.ymin + self.ymax) / 2)
        width = (self.xmax - self.xmin) * 111.320 * math.cos(mid_lat)
        height = (self.ymax - self.ymin) * 110.574
        return abs(width * height)

    def contains(self, lon: float, lat: float) -> bool:
        return self.xmin <= lon <= self.xmax and self.ymin <= lat <= self.ymax

    def to_polygon(self) -> dict[str, Any]:
        return {
            "type": "Polygon",
            "coordinates": [
                [
                    [self.xmin, self.ymin],
                    [self.xmax, self.ymin],
                    [self.xmax, self.ymax],
                    [self.xmin, self.ymax],
                    [self.xmin, self.ymin],
                ]
            ],
        }


def meters_to_degrees(meters: float, latitude: float) -> tuple[float, float]:
    """Conversion approximative mètres → degrés (lon, lat) à une latitude donnée."""
    lat_deg = meters / 110_574.0
    cos_lat = max(math.cos(math.radians(latitude)), 1e-6)
    lon_deg = meters / (111_320.0 * cos_lat)
    return lon_deg, lat_deg


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distance orthodromique en mètres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def iter_coordinates(geometry: dict[str, Any]) -> Iterable[list[float]]:
    """Parcourt récursivement toutes les positions d'une géométrie GeoJSON."""
    if not isinstance(geometry, dict):
        return
    gtype = geometry.get("type")
    if gtype == "GeometryCollection":
        for geom in geometry.get("geometries", []):
            yield from iter_coordinates(geom)
        return
    if gtype == "Feature":
        yield from iter_coordinates(geometry.get("geometry") or {})
        return
    if gtype == "FeatureCollection":
        for feat in geometry.get("features", []):
            yield from iter_coordinates(feat.get("geometry") or {})
        return

    def walk(node: Any) -> Iterable[list[float]]:
        if isinstance(node, (list, tuple)):
            if node and isinstance(node[0], (int, float)):
                yield list(node)
            else:
                for child in node:
                    yield from walk(child)

    yield from walk(geometry.get("coordinates", []))


def feature_collection(features: list[dict[str, Any]], **metadata: Any) -> dict[str, Any]:
    fc: dict[str, Any] = {"type": "FeatureCollection", "features": features}
    if metadata:
        fc["metadata"] = metadata
    return fc


def feature(geometry: dict[str, Any] | None, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "Feature", "geometry": geometry, "properties": properties or {}}


def as_geometry(geojson: dict[str, Any]) -> dict[str, Any]:
    """Extrait une géométrie d'un Feature / FeatureCollection / geometry."""
    if not isinstance(geojson, dict):
        raise GeoError("GeoJSON attendu")
    gtype = geojson.get("type")
    if gtype == "Feature":
        geom = geojson.get("geometry")
        if not geom:
            raise GeoError("Feature sans géométrie")
        return geom
    if gtype == "FeatureCollection":
        feats = geojson.get("features") or []
        if not feats:
            raise GeoError("FeatureCollection vide")
        if len(feats) == 1:
            return as_geometry(feats[0])
        geoms = [as_geometry(f) for f in feats]
        return {"type": "GeometryCollection", "geometries": geoms}
    if gtype in {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }:
        return geojson
    raise GeoError(f"Type GeoJSON non supporté : {gtype}")


def point_in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray casting sur un anneau."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            x_at = (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1
            if lon < x_at:
                inside = not inside
    return inside


def point_in_polygon(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    """Test point-dans-polygone pur Python (Polygon / MultiPolygon / collection)."""
    gtype = geometry.get("type")
    if gtype == "Polygon":
        rings = geometry.get("coordinates", [])
        if not rings or not point_in_ring(lon, lat, rings[0]):
            return False
        return not any(point_in_ring(lon, lat, hole) for hole in rings[1:])
    if gtype == "MultiPolygon":
        return any(
            point_in_polygon(lon, lat, {"type": "Polygon", "coordinates": poly})
            for poly in geometry.get("coordinates", [])
        )
    if gtype == "GeometryCollection":
        return any(point_in_polygon(lon, lat, g) for g in geometry.get("geometries", []))
    return False


def ring_area_m2(ring: Sequence[Sequence[float]]) -> float:
    """Aire sphérique signée d'un anneau (formule de l'excès sphérique)."""
    if len(ring) < 4:
        return 0.0
    total = 0.0
    for i in range(len(ring) - 1):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total * EARTH_RADIUS_M**2 / 2.0)


def geometry_area_m2(geometry: dict[str, Any]) -> float:
    gtype = geometry.get("type")
    if gtype == "Polygon":
        rings = geometry.get("coordinates", [])
        if not rings:
            return 0.0
        return ring_area_m2(rings[0]) - sum(ring_area_m2(r) for r in rings[1:])
    if gtype == "MultiPolygon":
        return sum(
            geometry_area_m2({"type": "Polygon", "coordinates": poly})
            for poly in geometry.get("coordinates", [])
        )
    if gtype == "GeometryCollection":
        return sum(geometry_area_m2(g) for g in geometry.get("geometries", []))
    return 0.0


def geometry_length_m(geometry: dict[str, Any]) -> float:
    gtype = geometry.get("type")
    if gtype == "LineString":
        coords = geometry.get("coordinates", [])
        return sum(
            haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
            for i in range(len(coords) - 1)
        )
    if gtype == "MultiLineString":
        return sum(
            geometry_length_m({"type": "LineString", "coordinates": line})
            for line in geometry.get("coordinates", [])
        )
    if gtype == "GeometryCollection":
        return sum(geometry_length_m(g) for g in geometry.get("geometries", []))
    return 0.0


def _ring_centroid(ring: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    """Centroïde surfacique signé d'un anneau : (cx, cy, aire_signée)."""
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area2) < 1e-14:  # anneau dégénéré : repli sur la moyenne
        pts = ring[:-1] if n > 1 and list(ring[0]) == list(ring[-1]) else ring
        if not pts:
            raise GeoError("Anneau vide")
        return (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
            0.0,
        )
    area = area2 / 2.0
    return cx / (3 * area2), cy / (3 * area2), area


def centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    """Centroïde d'une géométrie.

    Pour les polygones on calcule le centroïde surfacique (pondéré par l'aire,
    trous déduits) et non la moyenne des sommets : celle-ci est biaisée par le
    sommet de fermeture dupliqué et par la densité inégale des vertex.
    """
    gtype = geometry.get("type")

    if gtype == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings:
            raise GeoError("Polygone sans anneau")
        cx, cy, area = _ring_centroid(rings[0])
        if area == 0.0:
            return cx, cy
        wx, wy, total = cx * abs(area), cy * abs(area), abs(area)
        for hole in rings[1:]:  # les trous retirent de la masse
            hx, hy, harea = _ring_centroid(hole)
            wx -= hx * abs(harea)
            wy -= hy * abs(harea)
            total -= abs(harea)
        if total <= 0:
            return cx, cy
        return wx / total, wy / total

    if gtype == "MultiPolygon":
        parts = [
            centroid({"type": "Polygon", "coordinates": poly})
            for poly in geometry.get("coordinates") or []
        ]
        weights = [
            abs(geometry_area_m2({"type": "Polygon", "coordinates": poly}))
            for poly in geometry.get("coordinates") or []
        ]
        if not parts:
            raise GeoError("MultiPolygon vide")
        total = sum(weights)
        if total <= 0:
            return (
                sum(p[0] for p in parts) / len(parts),
                sum(p[1] for p in parts) / len(parts),
            )
        return (
            sum(p[0] * w for p, w in zip(parts, weights, strict=True)) / total,
            sum(p[1] * w for p, w in zip(parts, weights, strict=True)) / total,
        )

    if gtype == "GeometryCollection":
        parts = [centroid(g) for g in geometry.get("geometries") or []]
        if not parts:
            raise GeoError("GeometryCollection vide")
        return (
            sum(p[0] for p in parts) / len(parts),
            sum(p[1] for p in parts) / len(parts),
        )

    coords = list(iter_coordinates(geometry))
    if not coords:
        raise GeoError("Géométrie vide")
    # Retire le sommet de fermeture éventuel (lignes fermées)
    if len(coords) > 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return (
        sum(c[0] for c in coords) / len(coords),
        sum(c[1] for c in coords) / len(coords),
    )


def circle_polygon(lon: float, lat: float, radius_m: float, steps: int = 64) -> dict[str, Any]:
    """Cercle géodésique approximé — utilisé pour buffers et isochrones de secours."""
    ring: list[list[float]] = []
    for i in range(steps + 1):
        angle = 2 * math.pi * i / steps
        dlon, dlat = meters_to_degrees(radius_m, lat)
        ring.append([lon + dlon * math.cos(angle), lat + dlat * math.sin(angle)])
    return {"type": "Polygon", "coordinates": [ring]}
