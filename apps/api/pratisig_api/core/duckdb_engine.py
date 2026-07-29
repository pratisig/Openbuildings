"""Moteur DuckDB unique partagé par les modules Overture et Open Buildings.

Avant : `backend.py` et `agent.py` (openmapagents) ouvraient chacun leur
connexion DuckDB avec la même configuration copiée-collée. Ici une seule
connexion, thread-safe, chargée paresseusement.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from ..config import settings

log = logging.getLogger("pratisig.duckdb")


class DuckDBUnavailable(RuntimeError):
    """DuckDB (ou une extension requise) n'est pas disponible."""


class DuckDBEngine:
    """Connexion DuckDB paresseuse avec extensions spatial + httpfs."""

    def __init__(self) -> None:
        self._conn: Any | None = None
        self._lock = threading.RLock()
        self._loaded_extensions: list[str] = []

    # ── Cycle de vie ───────────────────────────────────────────────
    def connect(self) -> DuckDBEngine:
        with self._lock:
            if self._conn is not None:
                return self
            try:
                import duckdb
            except ImportError as exc:  # pragma: no cover
                raise DuckDBUnavailable("Le paquet `duckdb` n'est pas installé") from exc

            conn = duckdb.connect(":memory:")
            for ext in settings.duckdb_extensions:
                try:
                    conn.execute(f"INSTALL {ext}; LOAD {ext};")
                    self._loaded_extensions.append(ext)
                except Exception as exc:  # extension optionnelle / hors-ligne
                    log.warning("Extension DuckDB '%s' indisponible: %s", ext, exc)
            try:
                conn.execute(f"SET s3_region='{settings.overture_s3_region}';")
            except Exception:
                pass
            conn.execute(f"SET memory_limit='{settings.duckdb_memory_limit}';")
            conn.execute(f"SET threads={settings.duckdb_threads};")
            self._conn = conn
            log.info("DuckDB prêt (extensions: %s)", ", ".join(self._loaded_extensions) or "aucune")
            return self

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                self._loaded_extensions = []

    @property
    def connection(self) -> Any:
        if self._conn is None:
            self.connect()
        return self._conn

    @property
    def available(self) -> bool:
        try:
            self.connect()
            return self._conn is not None
        except DuckDBUnavailable:
            return False

    def health(self) -> dict[str, Any]:
        try:
            self.connect()
            version = self.connection.execute("SELECT version()").fetchone()[0]
            return {
                "status": "ok",
                "version": version,
                "extensions": self._loaded_extensions,
                "spatial": "spatial" in self._loaded_extensions,
                "httpfs": "httpfs" in self._loaded_extensions,
            }
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    # ── Requêtes ───────────────────────────────────────────────────
    def execute(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        with self._lock:
            cur = self.connection.execute(sql, params or [])
            return cur.fetchall()

    def query_dicts(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.connection.execute(sql, params or [])
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def query_geojson(
        self,
        sql: str,
        params: list[Any] | None = None,
        geometry_column: str = "geom_json",
    ) -> dict[str, Any]:
        """Exécute une requête et convertit le résultat en FeatureCollection.

        La colonne géométrie doit être produite par `ST_AsGeoJSON(...)`.
        """
        rows = self.query_dicts(sql, params)
        features: list[dict[str, Any]] = []
        for row in rows:
            raw_geom = row.pop(geometry_column, None)
            geometry = _parse_geometry(raw_geom)
            if geometry is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {k: _jsonify(v) for k, v in row.items()},
                }
            )
        return {"type": "FeatureCollection", "features": features}


def _parse_geometry(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw or None
    text = str(raw)
    if text in ("", "None", "nan", "NULL"):
        return None
    try:
        geom = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return geom if geom and geom.get("coordinates") is not None else None


def _jsonify(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):  # numpy scalars
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    return None if text in ("nan", "NaT", "None") else text


engine = DuckDBEngine()
