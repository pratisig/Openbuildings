"""Résolution dynamique de la version Overture Maps.

Overture **supprime ses versions au bout de 60 jours**
(https://docs.overturemaps.org). Coder une version en dur condamne donc le
module à cesser de fonctionner deux mois après chaque publication — c'est
exactement ce qui s'est produit : les huit versions testées renvoyaient
« No files found » parce que les fichiers avaient été supprimés.

Ce service interroge le catalogue officiel pour obtenir la version courante,
la met en cache sur disque, et retombe sur une valeur configurée si le réseau
est indisponible.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Any

from ..config import settings
from ..core import cache

log = logging.getLogger("pratisig.overture")

RELEASES_URL = "https://labs.overturemaps.org/data/releases.json"
STAC_URL = "https://stac.overturemaps.org/catalog.json"

CACHE_NS = "overture-release"
CACHE_KEY = "latest"
CACHE_TTL = 6 * 3600  # 6 heures : les publications sont mensuelles

_lock = threading.Lock()
_memo: dict[str, Any] = {"release": None, "checked_at": 0.0, "source": None}


def _fetch(url: str, timeout: float = 8.0) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": settings.user_agent})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        log.debug("Catalogue Overture injoignable (%s) : %s", url, exc)
        return None


def _discover() -> tuple[str | None, str]:
    """Interroge les catalogues officiels. Retourne (version, origine)."""
    data = _fetch(RELEASES_URL)
    if isinstance(data, dict) and data.get("latest"):
        return str(data["latest"]), "labs.overturemaps.org"

    data = _fetch(STAC_URL)
    if isinstance(data, dict) and data.get("latest"):
        return str(data["latest"]), "stac.overturemaps.org"

    return None, "aucune"


def get_release(force_refresh: bool = False) -> str:
    """Version Overture à utiliser.

    Ordre de préférence :
      1. version fixée explicitement par l'utilisateur ;
      2. mémoire du processus (6 h) ;
      3. cache disque ;
      4. catalogue officiel ;
      5. valeur par défaut, qui peut être périmée.
    """
    if settings.overture_release_pinned:
        return settings.overture_release_pinned

    with _lock:
        now = time.time()
        if not force_refresh and _memo["release"] and (now - _memo["checked_at"]) < CACHE_TTL:
            return _memo["release"]

        if not force_refresh:
            cached = cache.get(CACHE_NS, CACHE_KEY, ttl=CACHE_TTL)
            if isinstance(cached, dict) and cached.get("release"):
                _memo.update(
                    release=cached["release"],
                    checked_at=now,
                    source=cached.get("source", "cache"),
                )
                return cached["release"]

        release, source = _discover()
        if release:
            log.info("Version Overture courante : %s (via %s)", release, source)
            _memo.update(release=release, checked_at=now, source=source)
            cache.set(CACHE_NS, CACHE_KEY, {"release": release, "source": source})
            return release

        fallback = settings.overture_release_fallback
        log.warning(
            "Catalogue Overture injoignable — repli sur %s. "
            "Overture supprimant ses versions après 60 jours, celle-ci peut être périmée.",
            fallback,
        )
        _memo.update(release=fallback, checked_at=now, source="repli")
        return fallback


def release_path() -> str:
    """Chemin de base de la version courante."""
    base = settings.overture_s3_base if settings.overture_use_s3 else settings.overture_https_base
    return f"{base}/{get_release()}"


def status() -> dict[str, Any]:
    release = get_release()
    return {
        "release": release,
        "source": _memo.get("source") or ("épinglée" if settings.overture_release_pinned else "inconnue"),
        "pinned": bool(settings.overture_release_pinned),
        "access": "s3" if settings.overture_use_s3 else "https",
        "note": "Overture supprime ses versions après 60 jours ; elle est résolue automatiquement.",
    }
