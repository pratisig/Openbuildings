"""Module d'analyse spatiale vectorielle.

`openmapagents` exécutait ces opérations côté navigateur avec turf.js, ce qui
les rendait inaccessibles à l'API, aux scripts et à l'agent. Ici elles sont
disponibles côté serveur, avec Shapely si présent et un repli pur Python sinon.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.geo import (
    BBox,
    centroid,
    circle_polygon,
    feature,
    geometry_area_m2,
    geometry_length_m,
    haversine_m,
    point_in_polygon,
)

log = logging.getLogger("pratisig.spatial")
router = APIRouter(prefix="/api/spatial", tags=["analyse-spatiale"])

try:  # Shapely améliore la précision mais reste optionnel
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    SHAPELY = True
except ImportError:  # pragma: no cover
    SHAPELY = False

OPERATIONS: dict[str, dict[str, Any]] = {
    "buffer": {
        "label": "Zone tampon",
        "inputs": 1,
        "params": {"radius_m": "Rayon en mètres (obligatoire)"},
        "description": "Génère une zone tampon autour de chaque entité.",
    },
    "centroid": {"label": "Centroïdes", "inputs": 1, "params": {}, "description": "Point central de chaque entité."},
    "convex_hull": {
        "label": "Enveloppe convexe",
        "inputs": 1,
        "params": {},
        "description": "Plus petit polygone convexe englobant la couche.",
    },
    "dissolve": {
        "label": "Fusion",
        "inputs": 1,
        "params": {"attribute": "Attribut de regroupement (optionnel)"},
        "description": "Fusionne les entités, éventuellement par attribut.",
    },
    "clip": {
        "label": "Découpe",
        "inputs": 2,
        "params": {},
        "description": "Conserve les entités de A situées dans B.",
    },
    "intersection": {
        "label": "Intersection",
        "inputs": 2,
        "params": {},
        "description": "Géométrie commune entre A et B (Shapely requis).",
    },
    "difference": {
        "label": "Différence",
        "inputs": 2,
        "params": {},
        "description": "Partie de A hors de B (Shapely requis).",
    },
    "points_in_polygon": {
        "label": "Points dans polygones",
        "inputs": 2,
        "params": {},
        "description": "Compte les points de A par polygone de B.",
    },
    "nearest": {
        "label": "Plus proche voisin",
        "inputs": 2,
        "params": {},
        "description": "Associe chaque entité de A à la plus proche de B.",
    },
    "stats": {
        "label": "Statistiques de couche",
        "inputs": 1,
        "params": {"attribute": "Attribut numérique à résumer (optionnel)"},
        "description": "Comptage, surfaces, longueurs et emprise.",
    },
}


class SpatialRequest(BaseModel):
    operation: str = Field(..., description="Voir /api/spatial/operations")
    layer_a: dict[str, Any] = Field(..., description="FeatureCollection source")
    layer_b: dict[str, Any] | None = Field(None, description="FeatureCollection secondaire")
    params: dict[str, Any] = Field(default_factory=dict)


def _features(collection: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not collection:
        return []
    if collection.get("type") == "FeatureCollection":
        return [f for f in collection.get("features", []) if f.get("geometry")]
    if collection.get("type") == "Feature":
        return [collection] if collection.get("geometry") else []
    return [feature(collection)]


def _geom_point(geometry: dict[str, Any]) -> tuple[float, float]:
    if geometry.get("type") == "Point":
        c = geometry["coordinates"]
        return float(c[0]), float(c[1])
    return centroid(geometry)


def _op_buffer(feats: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    radius = params.get("radius_m")
    if not radius or float(radius) <= 0:
        raise HTTPException(400, "Le paramètre `radius_m` est obligatoire et doit être positif")
    radius = float(radius)
    out = []
    for f in feats:
        if SHAPELY:
            try:
                geom = shape(f["geometry"])
                lat = geom.centroid.y
                deg = radius / (111_320.0 * max(abs(__import__("math").cos(__import__("math").radians(lat))), 1e-6))
                buffered = geom.buffer(deg)
                out.append(feature(mapping(buffered), {**f.get("properties", {}), "buffer_m": radius}))
                continue
            except Exception:
                pass
        lon, lat = _geom_point(f["geometry"])
        out.append(
            feature(circle_polygon(lon, lat, radius), {**f.get("properties", {}), "buffer_m": radius})
        )
    return out


def _op_centroid(feats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in feats:
        try:
            lon, lat = _geom_point(f["geometry"])
        except Exception:
            continue
        out.append(feature({"type": "Point", "coordinates": [lon, lat]}, dict(f.get("properties", {}))))
    return out


def _op_convex_hull(feats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from ..core.geo import iter_coordinates

    points = sorted({(c[0], c[1]) for f in feats for c in iter_coordinates(f["geometry"])})
    if len(points) < 3:
        raise HTTPException(400, "Au moins 3 points distincts sont nécessaires")

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    ring = [list(p) for p in lower[:-1] + upper[:-1]]
    ring.append(ring[0])
    geom = {"type": "Polygon", "coordinates": [ring]}
    return [feature(geom, {"vertices": len(ring) - 1, "area_km2": round(geometry_area_m2(geom) / 1e6, 3)})]


def _op_dissolve(feats: list[dict[str, Any]], params: dict[str, Any]) -> list[dict[str, Any]]:
    if not SHAPELY:
        raise HTTPException(501, "L'opération `dissolve` nécessite Shapely côté serveur")
    attribute = params.get("attribute")
    groups: dict[Any, list[Any]] = {}
    for f in feats:
        key = f.get("properties", {}).get(attribute) if attribute else "__all__"
        try:
            groups.setdefault(key, []).append(shape(f["geometry"]))
        except Exception:
            continue
    out = []
    for key, geoms in groups.items():
        merged = unary_union(geoms)
        props: dict[str, Any] = {"count": len(geoms)}
        if attribute:
            props[attribute] = key
        merged_geom = mapping(merged)
        props["area_km2"] = round(geometry_area_m2(merged_geom) / 1e6, 3)
        out.append(feature(merged_geom, props))
    return out


def _op_clip(feats_a: list[dict[str, Any]], feats_b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if SHAPELY:
        try:
            mask = unary_union([shape(f["geometry"]) for f in feats_b])
            out = []
            for f in feats_a:
                try:
                    geom = shape(f["geometry"])
                    if geom.intersects(mask):
                        clipped = geom.intersection(mask)
                        if not clipped.is_empty:
                            out.append(feature(mapping(clipped), dict(f.get("properties", {}))))
                except Exception:
                    continue
            return out
        except Exception:
            pass
    masks = [f["geometry"] for f in feats_b]
    out = []
    for f in feats_a:
        try:
            lon, lat = _geom_point(f["geometry"])
        except Exception:
            continue
        if any(point_in_polygon(lon, lat, m) for m in masks):
            out.append(f)
    return out


def _op_binary_shapely(
    feats_a: list[dict[str, Any]], feats_b: list[dict[str, Any]], mode: str
) -> list[dict[str, Any]]:
    if not SHAPELY:
        raise HTTPException(501, f"L'opération `{mode}` nécessite Shapely côté serveur")
    geom_a = unary_union([shape(f["geometry"]) for f in feats_a])
    geom_b = unary_union([shape(f["geometry"]) for f in feats_b])
    result = geom_a.intersection(geom_b) if mode == "intersection" else geom_a.difference(geom_b)
    if result.is_empty:
        return []
    geom = mapping(result)
    return [feature(geom, {"operation": mode, "area_km2": round(geometry_area_m2(geom) / 1e6, 3)})]


def _op_points_in_polygon(
    feats_a: list[dict[str, Any]], feats_b: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    points: list[tuple[float, float]] = []
    for f in feats_a:
        try:
            points.append(_geom_point(f["geometry"]))
        except Exception:
            continue
    out = []
    for poly in feats_b:
        count = sum(1 for lon, lat in points if point_in_polygon(lon, lat, poly["geometry"]))
        area_km2 = geometry_area_m2(poly["geometry"]) / 1e6
        out.append(
            feature(
                poly["geometry"],
                {
                    **poly.get("properties", {}),
                    "point_count": count,
                    "density_per_km2": round(count / area_km2, 2) if area_km2 > 0 else None,
                },
            )
        )
    return out


def _op_nearest(feats_a: list[dict[str, Any]], feats_b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[tuple[float, float, dict[str, Any]]] = []
    for f in feats_b:
        try:
            lon, lat = _geom_point(f["geometry"])
            targets.append((lon, lat, f.get("properties", {})))
        except Exception:
            continue
    if not targets:
        raise HTTPException(400, "La couche B ne contient aucune géométrie exploitable")

    out = []
    for f in feats_a:
        try:
            lon, lat = _geom_point(f["geometry"])
        except Exception:
            continue
        best = min(targets, key=lambda t: haversine_m(lon, lat, t[0], t[1]))
        distance = haversine_m(lon, lat, best[0], best[1])
        out.append(
            feature(
                f["geometry"],
                {
                    **f.get("properties", {}),
                    "nearest_name": best[2].get("name") or best[2].get("nom"),
                    "nearest_distance_m": round(distance, 1),
                    "nearest_distance_km": round(distance / 1000, 3),
                },
            )
        )
    return out


def _op_stats(feats: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    from ..core.geo import iter_coordinates

    types: dict[str, int] = {}
    total_area = 0.0
    total_length = 0.0
    all_coords: list[list[float]] = []
    for f in feats:
        geom = f["geometry"]
        gtype = geom.get("type", "?")
        types[gtype] = types.get(gtype, 0) + 1
        total_area += geometry_area_m2(geom)
        total_length += geometry_length_m(geom)
        all_coords.extend(iter_coordinates(geom))

    stats: dict[str, Any] = {
        "count": len(feats),
        "geometry_types": types,
        "total_area_km2": round(total_area / 1e6, 4),
        "total_length_km": round(total_length / 1000, 3),
    }
    if all_coords:
        xs = [c[0] for c in all_coords]
        ys = [c[1] for c in all_coords]
        bbox = BBox(min(xs), min(ys), max(xs), max(ys))
        stats["bbox"] = bbox.to_list()
        stats["bbox_area_km2"] = round(bbox.area_km2, 2)
        stats["center"] = list(bbox.center)

    attribute = params.get("attribute")
    if attribute:
        values = []
        for f in feats:
            raw = f.get("properties", {}).get(attribute)
            try:
                if raw is not None:
                    values.append(float(raw))
            except (TypeError, ValueError):
                continue
        if values:
            ordered = sorted(values)
            mid = len(ordered) // 2
            stats["attribute"] = {
                "name": attribute,
                "count": len(values),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "mean": round(sum(values) / len(values), 4),
                "median": round(
                    ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2, 4
                ),
                "sum": round(sum(values), 4),
            }
    return stats


@router.get("/operations", summary="Opérations spatiales disponibles")
def operations() -> dict[str, Any]:
    return {
        "operations": [{"id": key, **meta} for key, meta in OPERATIONS.items()],
        "shapely_available": SHAPELY,
        "note": "Sans Shapely, intersection/difference/dissolve sont indisponibles.",
    }


@router.post("/run", summary="Exécuter une opération spatiale")
def run(payload: SpatialRequest) -> dict[str, Any]:
    op = payload.operation
    if op not in OPERATIONS:
        raise HTTPException(404, f"Opération inconnue. Disponibles : {list(OPERATIONS)}")

    feats_a = _features(payload.layer_a)
    if not feats_a:
        raise HTTPException(400, "`layer_a` ne contient aucune entité géométrique")

    needs_b = OPERATIONS[op]["inputs"] == 2
    feats_b = _features(payload.layer_b)
    if needs_b and not feats_b:
        raise HTTPException(400, f"L'opération `{op}` requiert une couche `layer_b`")

    if op == "stats":
        return {"operation": op, "result": _op_stats(feats_a, payload.params)}

    if op == "buffer":
        features_out = _op_buffer(feats_a, payload.params)
    elif op == "centroid":
        features_out = _op_centroid(feats_a)
    elif op == "convex_hull":
        features_out = _op_convex_hull(feats_a)
    elif op == "dissolve":
        features_out = _op_dissolve(feats_a, payload.params)
    elif op == "clip":
        features_out = _op_clip(feats_a, feats_b)
    elif op in ("intersection", "difference"):
        features_out = _op_binary_shapely(feats_a, feats_b, op)
    elif op == "points_in_polygon":
        features_out = _op_points_in_polygon(feats_a, feats_b)
    elif op == "nearest":
        features_out = _op_nearest(feats_a, feats_b)
    else:  # pragma: no cover
        raise HTTPException(501, f"Opération non implémentée : {op}")

    return {
        "type": "FeatureCollection",
        "features": features_out,
        "metadata": {
            "operation": op,
            "label": OPERATIONS[op]["label"],
            "input_a_count": len(feats_a),
            "input_b_count": len(feats_b) if needs_b else None,
            "output_count": len(features_out),
            "engine": "shapely" if SHAPELY else "python",
        },
    }
