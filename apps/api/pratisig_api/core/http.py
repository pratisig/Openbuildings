"""Client HTTP partagé (httpx) avec User-Agent, timeouts et gestion d'erreurs.

Remplace les `requests.get(...)` dispersés dans tous les anciens projets,
chacun avec son propre timeout (ou aucun) et sans User-Agent conforme aux
politiques d'usage de Nominatim / Overpass.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger("pratisig.http")

_client: httpx.AsyncClient | None = None


class UpstreamError(RuntimeError):
    """Erreur renvoyée par un service tiers."""

    def __init__(self, service: str, detail: str, status_code: int = 502) -> None:
        super().__init__(f"[{service}] {detail}")
        self.service = service
        self.detail = detail
        self.status_code = status_code


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout),
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def get_json(service: str, url: str, **kwargs: Any) -> Any:
    try:
        resp = await get_client().get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(service, f"HTTP {exc.response.status_code}", exc.response.status_code) from exc
    except httpx.TimeoutException as exc:
        raise UpstreamError(service, "délai dépassé", 504) from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(service, str(exc)) from exc
    except ValueError as exc:
        raise UpstreamError(service, "réponse JSON invalide") from exc


async def post_json(service: str, url: str, **kwargs: Any) -> Any:
    try:
        resp = await get_client().post(url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(service, f"HTTP {exc.response.status_code}", exc.response.status_code) from exc
    except httpx.TimeoutException as exc:
        raise UpstreamError(service, "délai dépassé", 504) from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(service, str(exc)) from exc
    except ValueError as exc:
        raise UpstreamError(service, "réponse JSON invalide") from exc
