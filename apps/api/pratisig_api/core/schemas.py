"""Schémas Pydantic communs à tous les modules."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .geo import BBox, GeoError


class BBoxModel(BaseModel):
    xmin: float = Field(..., ge=-180, le=180)
    ymin: float = Field(..., ge=-90, le=90)
    xmax: float = Field(..., ge=-180, le=180)
    ymax: float = Field(..., ge=-90, le=90)

    @model_validator(mode="after")
    def _check_order(self) -> "BBoxModel":
        if self.xmin > self.xmax or self.ymin > self.ymax:
            raise ValueError("BBox invalide : min doit être inférieur à max")
        return self

    def to_bbox(self) -> BBox:
        return BBox(self.xmin, self.ymin, self.xmax, self.ymax)


class AreaOfInterest(BaseModel):
    """Zone d'étude : bbox, centre+rayon, GeoJSON ou code administratif.

    Point d'entrée unifié pour tous les modules — avant, chaque projet
    définissait sa propre notion de zone (WKT, bbox, GADM, dessin Folium).
    """

    bbox: list[float] | None = Field(None, min_length=4, max_length=4)
    center: list[float] | None = Field(None, min_length=2, max_length=2)
    radius_m: float | None = Field(None, gt=0, le=200_000)
    geojson: dict[str, Any] | None = None
    admin_code: str | None = Field(None, description="Ex: SEN.1.2_1 (GADM) ou ISO3")

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is not None:
            BBox.from_list(value)
        return value

    @model_validator(mode="after")
    def _at_least_one(self) -> "AreaOfInterest":
        if not any([self.bbox, self.center, self.geojson, self.admin_code]):
            raise ValueError("Fournir bbox, center+radius_m, geojson ou admin_code")
        if self.center is not None and self.radius_m is None:
            raise ValueError("center nécessite radius_m")
        return self

    def resolve_bbox(self) -> BBox:
        """Résout la zone en bbox (hors admin_code, résolu par le module admin)."""
        if self.bbox:
            return BBox.from_list(self.bbox)
        if self.center and self.radius_m:
            return BBox.from_center(self.center[0], self.center[1], self.radius_m)
        if self.geojson:
            return BBox.from_geojson(self.geojson)
        raise GeoError("Zone non résoluble en bbox sans résolution administrative")

    def geometry(self) -> dict[str, Any] | None:
        """Géométrie de découpe si disponible."""
        if self.geojson:
            from .geo import as_geometry

            return as_geometry(self.geojson)
        return None


class FeatureCollectionResponse(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceStatus(BaseModel):
    name: str
    status: Literal["ok", "degraded", "unavailable"]
    detail: str | None = None
    requires: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    service: str | None = None
