"""Agent cartographique — pilotage de la plateforme en langage naturel.

Repris de `openmapagents/backend/agent.py`, mais l'agent n'appelle plus
directement DuckDB : il appelle **les modules de la plateforme**. Ajouter un
module, c'est automatiquement enrichir l'agent.

Le module reste fonctionnel sans clé LLM : `/api/agent/tools` documente les
outils et `/api/agent/chat` renvoie une erreur 503 explicite.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings

log = logging.getLogger("pratisig.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"])

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "geocode",
            "description": (
                "Convertit un nom de lieu, une adresse ou un point de repère en coordonnées. "
                "À utiliser EN PREMIER dès qu'un lieu est mentionné."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Lieu à géocoder"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_overture",
            "description": (
                "Interroge les données Overture Maps (POI, bâtiments, routes, divisions) "
                "sur une zone. Fournir soit une bbox, soit un centre et un rayon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "theme": {
                        "type": "string",
                        "enum": ["places", "buildings", "transportation", "divisions", "base", "addresses"],
                    },
                    "center_lon": {"type": "number"},
                    "center_lat": {"type": "number"},
                    "radius_m": {"type": "number", "description": "Rayon en mètres"},
                    "bbox": {"type": "array", "items": {"type": "number"}, "description": "[xmin,ymin,xmax,ymax]"},
                    "category": {"type": "string", "description": "Catégorie de POI (restaurant, pharmacy...)"},
                    "limit": {"type": "integer", "description": "Défaut 500"},
                },
                "required": ["theme"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_buildings",
            "description": (
                "Extrait les empreintes de bâtiments Open Buildings (Google + Microsoft) "
                "pour un pays, éventuellement restreint à une zone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "country_iso3": {"type": "string", "description": "Code ISO3, ex: SEN"},
                    "center_lon": {"type": "number"},
                    "center_lat": {"type": "number"},
                    "radius_m": {"type": "number"},
                    "min_confidence": {"type": "number"},
                    "limit": {"type": "integer"},
                },
                "required": ["country_iso3"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_osm",
            "description": (
                "Extrait des données OpenStreetMap par gabarit : roads_all, roads_main, "
                "roads_strict, buildings, waterways, water_bodies, health, education, markets, landuse."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preset": {"type": "string"},
                    "center_lon": {"type": "number"},
                    "center_lat": {"type": "number"},
                    "radius_m": {"type": "number"},
                    "bbox": {"type": "array", "items": {"type": "number"}},
                    "limit": {"type": "integer"},
                },
                "required": ["preset"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_route",
            "description": "Calcule un itinéraire entre deux points ou plus. Géocoder les lieux d'abord.",
            "parameters": {
                "type": "object",
                "properties": {
                    "waypoints": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                        "description": "Liste de [lon, lat], au moins 2",
                    },
                    "profile": {"type": "string", "enum": ["foot", "bike", "car"]},
                },
                "required": ["waypoints"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_isochrone",
            "description": "Calcule les zones atteignables en X minutes depuis un point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "center": {"type": "array", "items": {"type": "number"}},
                    "minutes": {"type": "array", "items": {"type": "integer"}},
                    "profile": {"type": "string", "enum": ["foot", "bike", "car"]},
                },
                "required": ["center"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spatial_analysis",
            "description": (
                "Exécute une opération spatiale sur des couches affichées : buffer, clip, "
                "centroid, convex_hull, dissolve, points_in_polygon, nearest, stats."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "layer_a_name": {"type": "string", "description": "Nom exact d'une couche de la carte"},
                    "layer_b_name": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["operation", "layer_a_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fly_to",
            "description": "Déplace la caméra de la carte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "longitude": {"type": "number"},
                    "latitude": {"type": "number"},
                    "zoom": {"type": "number", "description": "Ville=11, quartier=14, rue=16"},
                },
                "required": ["longitude", "latitude"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_layer",
            "description": "Retire une couche de la carte ('all' pour tout effacer).",
            "parameters": {
                "type": "object",
                "properties": {"layer_name": {"type": "string"}},
                "required": ["layer_name"],
            },
        },
    },
]

SYSTEM_PROMPT = """Tu es l'assistant cartographique de la plateforme PratiSIG,
spécialisée sur le Sénégal et l'Afrique de l'Ouest.

MÉTHODE
1. Un lieu est mentionné → `geocode` d'abord, puis la requête avec center + radius_m.
2. Zéro résultat → élargir le rayon ou retirer le filtre de catégorie, puis réessayer une fois.
3. Rayons usuels : « à côté » 500 m, « près » 800 m, « autour » 1500 m, « quartier » 2000 m.

CHOIX DE LA SOURCE
- POI, commerces, adresses, routes fines → `query_overture`.
- Empreintes de bâtiments exhaustives sur un pays africain → `query_buildings`.
- Équipements (santé, écoles, marchés) et réseau routier local → `query_osm`.

ANALYSE
- « dans la zone / dans l'isochrone » → `spatial_analysis` opération `clip`.
- « à moins de X mètres » → `spatial_analysis` opération `buffer` puis `clip`.
- « combien de X par Y » → `points_in_polygon`.

RÈGLES
- Réponds en français, de façon concise et factuelle.
- Appelle `fly_to` APRÈS avoir chargé les données, jamais avant.
- Ne jamais inventer de chiffres : ils viennent des résultats d'outils.
- Précise toujours la source des données dans ta réponse finale.

REPÈRES
  Dakar : [-17.55, 14.63, -17.33, 14.82]
  Thiès : [-17.00, 14.75, -16.85, 14.85]
  Saint-Louis : [-16.55, 15.95, -16.40, 16.10]
"""


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    map_context: dict[str, Any] | None = Field(
        None, description="État de la carte : couches, emprise, zoom"
    )
    max_iterations: int | None = Field(None, ge=1, le=10)


def _area_from_args(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("bbox"):
        return {"bbox": args["bbox"]}
    if args.get("center_lon") is not None and args.get("center_lat") is not None:
        return {
            "center": [args["center_lon"], args["center_lat"]],
            "radius_m": args.get("radius_m", 1000),
        }
    raise ValueError("Zone manquante : fournir bbox ou center_lon/center_lat/radius_m")


async def execute_tool(name: str, args: dict[str, Any], map_context: dict[str, Any] | None) -> dict[str, Any]:
    """Exécute un outil en appelant les modules de la plateforme."""
    try:
        if name == "geocode":
            from .geocoding import geocode_one

            result = await geocode_one(args.get("query", ""))
            return result or {"error": f"Lieu introuvable : {args.get('query')}"}

        if name == "query_overture":
            from ..core.schemas import AreaOfInterest
            from .overture import OvertureQuery, query_overture

            payload = OvertureQuery(
                theme=args["theme"],
                area=AreaOfInterest(**_area_from_args(args)),
                category=args.get("category"),
                limit=min(args.get("limit", 500), 5000),
            )
            result = query_overture(payload)
            return _summarize_features(result)

        if name == "query_buildings":
            from ..core.schemas import AreaOfInterest
            from .buildings import BuildingsQuery, query_buildings

            area = None
            try:
                area = AreaOfInterest(**_area_from_args(args))
            except ValueError:
                pass
            payload = BuildingsQuery(
                country_iso3=args["country_iso3"],
                area=area,
                min_confidence=args.get("min_confidence", 0.0),
                limit=min(args.get("limit", 2000), 20000),
            )
            return _summarize_features(query_buildings(payload))

        if name == "query_osm":
            from ..core.schemas import AreaOfInterest
            from .osm import OSMQuery, query_osm

            payload = OSMQuery(
                preset=args["preset"],
                area=AreaOfInterest(**_area_from_args(args)),
                limit=min(args.get("limit", 2000), 10000),
            )
            return _summarize_features(await query_osm(payload))

        if name == "compute_route":
            from .routing import RouteRequest, route

            payload = RouteRequest(
                waypoints=args["waypoints"], profile=args.get("profile", "car")
            )
            return _summarize_features(await route(payload))

        if name == "compute_isochrone":
            from .routing import IsochroneRequest, isochrone

            payload = IsochroneRequest(
                center=args["center"],
                minutes=args.get("minutes", [5, 10, 15]),
                profile=args.get("profile", "foot"),
            )
            return _summarize_features(await isochrone(payload))

        if name == "spatial_analysis":
            from .spatial import SpatialRequest, run

            layers = {l.get("name"): l for l in (map_context or {}).get("layers", [])}
            layer_a = layers.get(args.get("layer_a_name"))
            if not layer_a or not layer_a.get("data"):
                return {
                    "error": f"Couche introuvable : {args.get('layer_a_name')}",
                    "available": list(layers),
                }
            layer_b = layers.get(args.get("layer_b_name")) if args.get("layer_b_name") else None
            payload = SpatialRequest(
                operation=args["operation"],
                layer_a=layer_a["data"],
                layer_b=layer_b["data"] if layer_b else None,
                params=args.get("params") or {},
            )
            return _summarize_features(run(payload))

        if name in ("fly_to", "remove_layer"):
            return {"action": name, **args}

        return {"error": f"Outil inconnu : {name}"}
    except Exception as exc:
        log.exception("Erreur d'exécution de l'outil %s", name)
        return {"error": str(exc)}


def _summarize_features(result: dict[str, Any]) -> dict[str, Any]:
    """Réduit un résultat volumineux pour le contexte du LLM.

    Les géométries complètes vont à la carte, pas au modèle : on ne renvoie
    au LLM qu'un résumé et un échantillon.
    """
    if "features" not in result:
        return result
    features = result["features"]
    sample = [
        {"properties": f.get("properties", {}), "geometry_type": (f.get("geometry") or {}).get("type")}
        for f in features[:5]
    ]
    return {
        "count": len(features),
        "metadata": result.get("metadata", {}),
        "sample": sample,
        "_layer_data": result,  # consommé par la couche transport, retiré du prompt
    }


@router.get("/tools", summary="Outils disponibles pour l'agent")
def tools() -> dict[str, Any]:
    return {
        "tools": [t["function"] for t in TOOLS],
        "count": len(TOOLS),
        "llm": {
            "enabled": settings.llm_enabled and bool(settings.llm_api_key),
            "provider": settings.llm_provider,
            "model": settings.llm_model,
        },
        "system_prompt": SYSTEM_PROMPT,
    }


@router.post("/chat", summary="Dialoguer avec l'agent cartographique")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    if not settings.llm_enabled or not settings.llm_api_key:
        raise HTTPException(
            503,
            "Agent désactivé. Définir PRATISIG_LLM_ENABLED=true et PRATISIG_LLM_API_KEY "
            "pour l'activer. Les autres modules restent utilisables directement.",
        )
    try:
        from litellm import acompletion
    except ImportError as exc:
        raise HTTPException(
            501, "Le paquet `litellm` n'est pas installé (pip install 'pratisig-api[agent]')"
        ) from exc

    map_context = payload.map_context or {}
    context_note = ""
    if map_context.get("layers"):
        names = [
            f"- {l.get('name')} ({l.get('count', '?')} entités, type {l.get('geometry_type', '?')})"
            for l in map_context["layers"]
        ]
        context_note = "\n\nCOUCHES ACTUELLEMENT SUR LA CARTE :\n" + "\n".join(names)
    if map_context.get("bbox"):
        context_note += f"\nEmprise visible : {map_context['bbox']}"

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT + context_note}]
    messages += [
        {"role": m.role, "content": m.content or ""} for m in payload.messages if m.role != "system"
    ]

    max_iterations = payload.max_iterations or settings.llm_max_iterations
    layers_produced: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        try:
            response = await acompletion(
                model=settings.llm_model,
                messages=messages,
                tools=TOOLS,
                api_key=settings.llm_api_key,
                temperature=0.2,
            )
        except Exception as exc:
            raise HTTPException(502, f"Erreur du fournisseur LLM : {exc}") from exc

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            return {
                "reply": message.content or "",
                "layers": layers_produced,
                "actions": actions,
                "tool_calls": tool_trace,
            }

        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for call in tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            result = await execute_tool(name, args, map_context)
            tool_trace.append({"tool": name, "arguments": args})

            layer_data = result.pop("_layer_data", None)
            if layer_data is not None:
                layers_produced.append(
                    {
                        "name": f"{name}:{args.get('theme') or args.get('preset') or args.get('operation') or 'résultat'}",
                        "data": layer_data,
                    }
                )
            if result.get("action"):
                actions.append(result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
                }
            )

    return {
        "reply": "Analyse interrompue : nombre maximal d'étapes atteint.",
        "layers": layers_produced,
        "actions": actions,
        "tool_calls": tool_trace,
        "truncated": True,
    }
