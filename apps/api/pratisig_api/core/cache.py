"""Cache disque JSON partagé par tous les modules.

Remplace les trois implémentations de cache dupliquées trouvées dans
`openmapagents/backend/backend.py`, `openmapagents/backend/agent.py` et
`Carto-facileSN/backend/services/geo_cache.py`.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from ..config import settings


def cache_key(*parts: Any) -> str:
    """Clé stable à partir de n'importe quels arguments sérialisables."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _path_for(namespace: str, key: str) -> Path:
    directory = settings.cache_dir / namespace
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{key}.json"


def get(namespace: str, key: str, ttl: int | None = None) -> Any | None:
    if not settings.cache_enabled:
        return None
    path = _path_for(namespace, key)
    if not path.exists():
        return None
    ttl = settings.cache_ttl_seconds if ttl is None else ttl
    if ttl > 0 and (time.time() - path.stat().st_mtime) > ttl:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def set(namespace: str, key: str, value: Any) -> None:  # noqa: A001
    if not settings.cache_enabled:
        return
    path = _path_for(namespace, key)
    try:
        path.write_text(json.dumps(value, default=str))
    except OSError:
        pass


def memoize(namespace: str, key: str, producer: Callable[[], Any], ttl: int | None = None) -> Any:
    """Récupère depuis le cache, sinon exécute `producer` et met en cache."""
    cached = get(namespace, key, ttl=ttl)
    if cached is not None:
        return cached
    value = producer()
    set(namespace, key, value)
    return value


def clear(namespace: str | None = None) -> int:
    """Vide un namespace (ou tout le cache). Retourne le nombre de fichiers supprimés."""
    root = settings.cache_dir / namespace if namespace else settings.cache_dir
    if not root.exists():
        return 0
    removed = 0
    for path in root.rglob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def stats() -> dict[str, Any]:
    root = settings.cache_dir
    namespaces: dict[str, dict[str, int]] = {}
    total_bytes = 0
    if root.exists():
        for path in root.rglob("*.json"):
            ns = path.parent.name
            size = path.stat().st_size
            total_bytes += size
            entry = namespaces.setdefault(ns, {"entries": 0, "bytes": 0})
            entry["entries"] += 1
            entry["bytes"] += size
    return {
        "enabled": settings.cache_enabled,
        "ttl_seconds": settings.cache_ttl_seconds,
        "directory": str(root),
        "total_bytes": total_bytes,
        "namespaces": namespaces,
    }
