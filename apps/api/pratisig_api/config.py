"""Configuration centrale de la plateforme PratiSIG.

Toute la configuration provient de variables d'environnement (fichier `.env`
en développement). C'est le point unique remplaçant les constantes éparpillées
dans les anciens dépôts (`app.py` Streamlit, `agent.py`, `config.py` Flask...).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(REPO_ROOT / ".env")),
        env_prefix="PRATISIG_",
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────
    app_name: str = "PratiSIG Platform API"
    version: str = "1.0.0"
    environment: str = "development"
    debug: bool = True
    # Origines autorisées. En production, ajouter le domaine du front via
    # PRATISIG_CORS_ORIGINS='["https://mon-front.vercel.app"]'.
    # La valeur "*" est acceptée pour un déploiement de test.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]
    )
    # Autorise tous les sous-domaines d'aperçu (Vercel, Netlify) par expression
    # régulière — indispensable car chaque déploiement a une URL différente.
    cors_origin_regex: str | None = Field(
        None,
        description=r"Ex: https://.*\.vercel\.app",
    )

    # ── Stockage / cache ───────────────────────────────────────────
    data_dir: Path = REPO_ROOT / "data"
    cache_dir: Path = REPO_ROOT / "data" / "cache"
    cache_ttl_seconds: int = 86_400
    cache_enabled: bool = True

    # ── DuckDB (moteur commun Overture + Open Buildings) ───────────
    # Sur un plan gratuit (512 Mo), descendre à "300MB" et 2 threads,
    # sinon DuckDB se fait tuer par l'OOM killer.
    duckdb_memory_limit: str = "4GB"
    duckdb_threads: int = 4
    duckdb_extensions: list[str] = Field(default_factory=lambda: ["spatial", "httpfs"])

    # ── Overture Maps ──────────────────────────────────────────────
    overture_release: str = "2025-06-25.0"
    # Le bucket S3 d'Overture est en mode « requester pays » : DuckDB ne peut
    # pas le lire sans identifiants AWS, d'ou les « No files found » observes.
    # L'acces HTTPS public fonctionne sans authentification et reste le
    # comportement par defaut. Mettre overture_use_s3=true si des identifiants
    # AWS sont configures sur la machine.
    overture_use_s3: bool = False
    overture_s3_base: str = "s3://overturemaps-us-west-2/release"
    overture_https_base: str = "https://overturemaps-us-west-2.s3.amazonaws.com/release"
    overture_s3_region: str = "us-west-2"

    # ── Open Buildings (VIDA Google + Microsoft) ───────────────────
    open_buildings_base: str = (
        "https://data.source.coop/vida/google-microsoft-open-buildings/geoparquet/by_country"
    )
    open_buildings_max_features: int = 200_000

    # ── Services externes ──────────────────────────────────────────
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Plusieurs miroirs Overpass : l'instance principale renvoie
    # regulierement des 504 aux heures chargees. Essayes dans l'ordre.
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_mirrors: list[str] = Field(
        default_factory=lambda: [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        ]
    )
    osrm_url: str = "https://router.project-osrm.org"
    nasa_power_url: str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    gadm_base_url: str = "https://geodata.ucdavis.edu/gadm/gadm4.1/json"
    user_agent: str = "PratiSIG-Platform/1.0 (https://github.com/pratisig)"
    http_timeout: float = 30.0

    # ── Google Earth Engine (optionnel) ────────────────────────────
    gee_service_account_email: str | None = None
    gee_service_account_key_file: str | None = None
    gee_service_account_key_json: str | None = None

    # ── Agent LLM (optionnel) ──────────────────────────────────────
    llm_enabled: bool = False
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    llm_max_iterations: int = 6

    # ── Sécurité / quotas ──────────────────────────────────────────
    max_export_features: int = 500_000

    @property
    def overture_release_path(self) -> str:
        base = self.overture_s3_base if self.overture_use_s3 else self.overture_https_base
        return f"{base}/{self.overture_release}"

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "reference").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if os.getenv("PRATISIG_SKIP_DIR_INIT") != "1":
        settings.ensure_dirs()
    return settings


settings = get_settings()
