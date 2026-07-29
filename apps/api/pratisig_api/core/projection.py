"""Projection UTM automatique — repris de `pratisig/sante-isochrones-app`.

Les calculs de surface et de distance sont faux en WGS84 (degrés). Le dépôt
d'origine détectait la zone UTM adaptée pour projeter avant mesure ; cette
logique est ici généralisée et rendue disponible à tous les modules, sans
dépendre de GeoPandas.
"""

from __future__ import annotations

import math
from typing import Any

from .geo import BBox


def utm_epsg(lon: float, lat: float) -> int:
    """Code EPSG de la zone UTM couvrant un point.

    326xx pour l'hémisphère nord, 327xx pour le sud.
    """
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Coordonnées hors bornes")
    zone = int((lon + 180) / 6) + 1
    zone = max(1, min(60, zone))
    return (32600 if lat >= 0 else 32700) + zone


def utm_label(epsg: int) -> str:
    zone = epsg % 100
    hemisphere = "N" if 32600 <= epsg < 32700 else "S"
    return f"UTM {zone}{hemisphere} (EPSG:{epsg})"


def utm_for_geometry(geometry: dict[str, Any]) -> int:
    """Zone UTM adaptée au centre d'une géométrie."""
    bbox = BBox.from_geojson(geometry)
    lon, lat = bbox.center
    return utm_epsg(lon, lat)


def utm_for_bbox(bbox: BBox) -> int:
    lon, lat = bbox.center
    return utm_epsg(lon, lat)


# ── Projection locale sans pyproj ──────────────────────────────────
def local_projector(lon0: float, lat0: float):
    """Projection azimutale équidistante locale, centrée sur (lon0, lat0).

    Suffisamment précise sur quelques dizaines de kilomètres pour mesurer
    surfaces et distances, sans dépendre de pyproj. Retourne deux fonctions
    (aller, retour) travaillant en mètres.
    """
    lat0_rad = math.radians(lat0)
    m_per_deg_lat = 110_574.0
    m_per_deg_lon = 111_320.0 * math.cos(lat0_rad)

    def forward(lon: float, lat: float) -> tuple[float, float]:
        return ((lon - lon0) * m_per_deg_lon, (lat - lat0) * m_per_deg_lat)

    def inverse(x: float, y: float) -> tuple[float, float]:
        return (lon0 + x / m_per_deg_lon, lat0 + y / m_per_deg_lat)

    return forward, inverse


def project_ring(ring: list[list[float]], forward) -> list[tuple[float, float]]:
    return [forward(c[0], c[1]) for c in ring]


def planar_area_m2(points: list[tuple[float, float]]) -> float:
    """Aire d'un polygone projeté (formule du lacet)."""
    if len(points) < 3:
        return 0.0
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0
