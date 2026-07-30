"""Gestion des identifiants de services externes.

Certains modules demandent un compte tiers : Google Earth Engine pour
l'imagerie et les inondations, un fournisseur LLM pour l'assistant. Jusqu'ici
il fallait éditer un fichier `.env` et redémarrer le serveur — infaisable pour
un utilisateur non technique.

Ce module permet de les renseigner depuis l'interface, avec application
immédiate. Deux garanties :

  * les valeurs ne sont **jamais** renvoyées en clair : les lectures ne
    retournent qu'un masque (`sk-...3f9a`) ;
  * la persistance sur disque est **facultative** et désactivée par défaut ;
    sans elle, les identifiants vivent en mémoire et disparaissent à l'arrêt.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings

log = logging.getLogger("pratisig.credentials")
router = APIRouter(prefix="/api/credentials", tags=["identifiants"])

STORE_PATH = settings.data_dir / "credentials.json"

# Catalogue des services configurables, affiché tel quel par l'interface.
PROVIDERS: dict[str, dict[str, Any]] = {
    "gee": {
        "label": "Google Earth Engine",
        "unlocks": ["raster", "flood"],
        "unlocks_label": "Imagerie satellite · Détection d'inondations",
        "description": (
            "Donne accès à Sentinel-1/2, Landsat, MODIS et WorldCover pour le "
            "calcul d'indices (NDVI, NDWI) et la détection des zones inondées."
        ),
        "signup_url": "https://console.cloud.google.com/iam-admin/serviceaccounts",
        "docs_url": "https://developers.google.com/earth-engine/guides/service_account",
        "free": True,
        "free_note": "Gratuit pour un usage recherche ou non commercial.",
        "steps": [
            "Créer un compte Earth Engine sur earthengine.google.com/signup",
            "Créer un projet Google Cloud et y activer l'API Earth Engine",
            "Créer un compte de service, rôle « Earth Engine Resource Viewer »",
            "Télécharger la clé au format JSON",
            "Enregistrer le compte de service sur code.earthengine.google.com/register",
        ],
        "fields": [
            {
                "key": "email",
                "label": "Adresse du compte de service",
                "placeholder": "mon-service@mon-projet.iam.gserviceaccount.com",
                "type": "text",
                "required": True,
                "env": "PRATISIG_GEE_SERVICE_ACCOUNT_EMAIL",
            },
            {
                "key": "key_json",
                "label": "Clé privée (contenu du fichier JSON)",
                "placeholder": '{"type": "service_account", "project_id": …}',
                "type": "textarea",
                "required": True,
                "secret": True,
                "env": "PRATISIG_GEE_SERVICE_ACCOUNT_KEY_JSON",
            },
        ],
    },
    "llm": {
        "label": "Assistant cartographique",
        "unlocks": ["agent"],
        "unlocks_label": "Pilotage de la carte en langage naturel",
        "description": (
            "Permet de dialoguer avec la carte : « montre les pharmacies autour "
            "du centre de Dakar », « calcule un itinéraire vers Thiès »."
        ),
        "signup_url": "https://platform.openai.com/api-keys",
        "docs_url": "https://docs.litellm.ai/docs/providers",
        "free": False,
        "free_note": "Facturé à l'usage par le fournisseur choisi.",
        "steps": [
            "Créer un compte chez un fournisseur (OpenAI, Anthropic, Mistral…)",
            "Générer une clé API",
            "Choisir le fournisseur et le modèle ci-dessous",
        ],
        "fields": [
            {
                "key": "provider",
                "label": "Fournisseur",
                "type": "select",
                "options": ["openai", "anthropic", "mistral", "deepseek", "openrouter", "ollama"],
                "default": "openai",
                "required": True,
                "env": "PRATISIG_LLM_PROVIDER",
            },
            {
                "key": "model",
                "label": "Modèle",
                "placeholder": "gpt-4o-mini",
                "type": "text",
                "default": "gpt-4o-mini",
                "required": True,
                "env": "PRATISIG_LLM_MODEL",
            },
            {
                "key": "api_key",
                "label": "Clé API",
                "placeholder": "sk-…",
                "type": "password",
                "required": True,
                "secret": True,
                "env": "PRATISIG_LLM_API_KEY",
            },
        ],
    },
    "mapbox": {
        "label": "Mapbox (facultatif)",
        "unlocks": [],
        "unlocks_label": "Fonds de carte supplémentaires",
        "description": (
            "La plateforme fonctionne sans : les fonds OpenStreetMap, CARTO et "
            "Esri sont utilisés par défaut, sans clé."
        ),
        "signup_url": "https://account.mapbox.com/access-tokens/",
        "docs_url": "https://docs.mapbox.com/help/getting-started/access-tokens/",
        "free": True,
        "free_note": "Palier gratuit généreux.",
        "steps": ["Créer un compte Mapbox", "Copier le jeton public"],
        "fields": [
            {
                "key": "token",
                "label": "Jeton public",
                "placeholder": "pk.eyJ1…",
                "type": "password",
                "required": True,
                "secret": True,
                "env": "PRATISIG_MAPBOX_TOKEN",
            },
        ],
    },
}


class CredentialUpdate(BaseModel):
    provider: str
    values: dict[str, str] = Field(default_factory=dict)
    persist: bool = Field(
        False,
        description=(
            "Écrire dans data/credentials.json. Sans cela, les identifiants "
            "restent en mémoire et sont perdus à l'arrêt du serveur."
        ),
    )


def _mask(value: str | None) -> str | None:
    """Masque une valeur sensible : jamais de secret renvoyé en clair."""
    if not value:
        return None
    text = str(value)
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:4]}…{text[-4:]}"


def _load_store() -> dict[str, dict[str, str]]:
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Fichier d'identifiants illisible : %s", exc)
        return {}


def _save_store(store: dict[str, dict[str, str]]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, indent=2))
    try:  # lecture réservée au propriétaire (sans effet sous Windows)
        os.chmod(STORE_PATH, 0o600)
    except OSError:
        pass


def _apply(provider: str, values: dict[str, str]) -> None:
    """Applique les valeurs à la configuration vivante et à l'environnement."""
    meta = PROVIDERS[provider]
    for field in meta["fields"]:
        value = values.get(field["key"])
        if value is None or value == "":
            continue
        os.environ[field["env"]] = value

    if provider == "gee":
        settings.gee_service_account_email = values.get("email") or settings.gee_service_account_email
        if values.get("key_json"):
            settings.gee_service_account_key_json = values["key_json"]
        # Force une nouvelle tentative d'initialisation
        from ..services import gee

        gee._state.update(ready=False, error=None, checked=False)

    elif provider == "llm":
        if values.get("provider"):
            settings.llm_provider = values["provider"]
        if values.get("model"):
            settings.llm_model = values["model"]
        if values.get("api_key"):
            settings.llm_api_key = values["api_key"]
            settings.llm_enabled = True


def load_persisted() -> None:
    """Recharge les identifiants enregistrés. Appelé au démarrage."""
    store = _load_store()
    for provider, values in store.items():
        if provider in PROVIDERS:
            try:
                _apply(provider, values)
                log.info("Identifiants %s restaurés depuis le disque", provider)
            except Exception as exc:
                log.warning("Restauration %s impossible : %s", provider, exc)


def _current_values(provider: str) -> dict[str, str | None]:
    """Valeurs actuellement actives, masquées si sensibles."""
    meta = PROVIDERS[provider]
    result: dict[str, str | None] = {}
    for field in meta["fields"]:
        raw = os.environ.get(field["env"])
        result[field["key"]] = _mask(raw) if field.get("secret") else raw
    return result


def _provider_status(provider: str) -> dict[str, Any]:
    from ..services import gee

    if provider == "gee":
        state = gee.status()
        return {
            "configured": bool(settings.gee_service_account_email),
            "active": state["ready"],
            "detail": state.get("error") or ("connecté" if state["ready"] else "non configuré"),
        }
    if provider == "llm":
        configured = bool(settings.llm_api_key)
        return {
            "configured": configured,
            "active": configured and settings.llm_enabled,
            "detail": f"{settings.llm_provider} · {settings.llm_model}" if configured else "non configuré",
        }
    token = os.environ.get("PRATISIG_MAPBOX_TOKEN")
    return {
        "configured": bool(token),
        "active": bool(token),
        "detail": "jeton enregistré" if token else "non configuré (facultatif)",
    }


@router.get("", summary="Services configurables et leur état")
def list_providers() -> dict[str, Any]:
    return {
        "providers": [
            {
                "id": key,
                **{k: v for k, v in meta.items() if k != "fields"},
                "fields": [
                    {k: v for k, v in field.items() if k != "env"} for field in meta["fields"]
                ],
                "status": _provider_status(key),
                "values": _current_values(key),
            }
            for key, meta in PROVIDERS.items()
        ],
        "persistence": {
            "path": str(STORE_PATH),
            "enabled": STORE_PATH.exists(),
            "warning": (
                "Enregistrer les identifiants les écrit en clair dans un fichier "
                "local. À éviter sur un poste partagé."
            ),
        },
    }


@router.post("/{provider}", summary="Enregistrer les identifiants d'un service")
def update_provider(provider: str, payload: CredentialUpdate) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise HTTPException(404, f"Service inconnu. Disponibles : {list(PROVIDERS)}")

    meta = PROVIDERS[provider]
    missing = [
        field["label"]
        for field in meta["fields"]
        if field.get("required") and not payload.values.get(field["key"])
    ]
    if missing:
        raise HTTPException(400, f"Champs obligatoires manquants : {', '.join(missing)}")

    # Validation propre au service, avant application
    if provider == "gee":
        try:
            parsed = json.loads(payload.values["key_json"])
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"La clé n'est pas un JSON valide : {exc}") from exc
        if parsed.get("type") != "service_account":
            raise HTTPException(400, "Ce JSON n'est pas une clé de compte de service.")
        if not parsed.get("private_key"):
            raise HTTPException(400, "La clé JSON ne contient pas de champ `private_key`.")

    _apply(provider, payload.values)

    if payload.persist:
        store = _load_store()
        store[provider] = payload.values
        _save_store(store)

    status = _provider_status(provider)
    return {
        "provider": provider,
        "status": status,
        "persisted": payload.persist,
        "message": (
            f"{meta['label']} configuré et actif."
            if status["active"]
            else f"Identifiants enregistrés, mais le service ne répond pas : {status['detail']}"
        ),
    }


@router.post("/{provider}/test", summary="Tester les identifiants sans les enregistrer")
def test_provider(provider: str) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise HTTPException(404, f"Service inconnu. Disponibles : {list(PROVIDERS)}")

    if provider == "gee":
        from ..services import gee

        gee._state.update(ready=False, error=None, checked=False)
        ok = gee.initialize()
        return {
            "provider": provider,
            "ok": ok,
            "detail": "Connexion établie" if ok else (gee._state.get("error") or "échec"),
        }

    if provider == "llm":
        if not settings.llm_api_key:
            return {"provider": provider, "ok": False, "detail": "Aucune clé enregistrée"}
        try:
            import litellm  # noqa: F401
        except ImportError:
            return {
                "provider": provider,
                "ok": False,
                "detail": "Le paquet `litellm` n'est pas installé (requirements-full.txt)",
            }
        return {
            "provider": provider,
            "ok": True,
            "detail": f"Clé enregistrée pour {settings.llm_provider} · {settings.llm_model}",
        }

    return {"provider": provider, "ok": True, "detail": "Aucun test disponible"}


@router.delete("/{provider}", summary="Supprimer les identifiants d'un service")
def delete_provider(provider: str) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise HTTPException(404, f"Service inconnu. Disponibles : {list(PROVIDERS)}")

    for field in PROVIDERS[provider]["fields"]:
        os.environ.pop(field["env"], None)

    if provider == "gee":
        settings.gee_service_account_email = None
        settings.gee_service_account_key_json = None
        from ..services import gee

        gee._state.update(ready=False, error=None, checked=False)
    elif provider == "llm":
        settings.llm_api_key = None
        settings.llm_enabled = False

    store = _load_store()
    if store.pop(provider, None) is not None:
        _save_store(store)

    return {"provider": provider, "removed": True}
