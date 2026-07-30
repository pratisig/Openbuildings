"""Verrouille le correctif de deploiement (Render / Docker).

Deux defauts bloquants ont ete rencontres au premier deploiement Render :

1. « disks are not supported for free tier services » — le plan gratuit
   interdit tout disque persistant ; un bloc `disk:` dans render.yaml fait
   echouer le deploiement avant meme la construction de l'image.
2. Donnees de reference absentes de l'image — le contexte Docker etait
   `./apps/api` alors que `data/reference/countries.geojson` est a la racine :
   jamais copie, donc `/api/buildings/countries` renvoyait une liste vide
   sans erreur explicite.

Ces tests empechent toute regression sur ces deux points.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RENDER_YAML = REPO_ROOT / "render.yaml"
DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"
COUNTRIES = REPO_ROOT / "data" / "reference" / "countries.geojson"


class TestDeploymentRender:
    """render.yaml compatible avec le plan gratuit de Render."""

    def test_docker_context_a_la_racine(self) -> None:
        """Le contexte doit etre la racine pour embarquer data/reference/."""
        texte = RENDER_YAML.read_text(encoding="utf-8")
        assert re.search(r"^\s*dockerContext:\s*\.\s*$", texte, re.MULTILINE), (
            "dockerContext doit etre '.' (racine du depot) : avec './apps/api', "
            "data/reference/countries.geojson n'entre jamais dans l'image."
        )

    def test_aucun_bloc_disk(self) -> None:
        """Le plan gratuit refuse tout disque persistant."""
        texte = RENDER_YAML.read_text(encoding="utf-8")
        assert not re.search(r"^\s*disk:\s*$", texte, re.MULTILINE), (
            "Un bloc `disk:` fait echouer le deploiement : "
            "'disks are not supported for free tier services'."
        )

    def test_cache_dir_ephemere(self) -> None:
        """Sans disque, le cache doit vivre dans /tmp du conteneur."""
        texte = RENDER_YAML.read_text(encoding="utf-8")
        assert "PRATISIG_CACHE_DIR" in texte and "/tmp/" in texte, (
            "render.yaml doit definir PRATISIG_CACHE_DIR sous /tmp "
            "(aucun chemin persistant n'existe sur le plan gratuit)."
        )


class TestDeploymentDockerfile:
    """Le Dockerfile part du contexte racine et embarque les donnees."""

    def test_copie_donnees_de_reference(self) -> None:
        """Sans countries.geojson, /api/buildings/countries renvoie [] en silence."""
        texte = DOCKERFILE.read_text(encoding="utf-8")
        assert "COPY data/reference" in texte, (
            "Le Dockerfile doit copier data/reference : c'est ce fichier qui "
            "alimente la liste des pays du module buildings."
        )

    def test_copies_depuis_la_racine(self) -> None:
        """Tous les COPY portent le prefixe apps/api/ (contexte = racine)."""
        texte = DOCKERFILE.read_text(encoding="utf-8")
        assert "COPY apps/api/requirements.txt" in texte
        assert "COPY apps/api/pratisig_api" in texte
        assert not re.search(r"^COPY pratisig_api", texte, re.MULTILINE), (
            "COPY sans prefixe suppose un contexte ./apps/api : incompatible "
            "avec la copie de data/reference situe a la racine."
        )

    def test_data_dir_coherent_avec_le_copy(self) -> None:
        """PRATISIG_DATA_DIR=/app/data doit pointer la ou COPY depose les fichiers."""
        texte = DOCKERFILE.read_text(encoding="utf-8")
        assert "PRATISIG_DATA_DIR=/app/data" in texte, (
            "L'application cherche <data_dir>/reference/countries.geojson ; "
            "le COPY depose les donnees dans /app/data."
        )

    def test_cache_dir_dans_tmp(self) -> None:
        """Le cache ne doit pas exiger de volume persistant."""
        texte = DOCKERFILE.read_text(encoding="utf-8")
        assert re.search(r"PRATISIG_CACHE_DIR=/tmp/\S+", texte), (
            "Le cache par defaut de l'image doit etre ephemere (/tmp) : "
            "aucun hebergeur gratuit ne fournit de disque persistant."
        )


class TestDeploymentCompose:
    """docker-compose construit la meme image que Render."""

    def test_contexte_racine_et_dockerfile_explicite(self) -> None:
        texte = COMPOSE.read_text(encoding="utf-8")
        assert re.search(r"^\s*context:\s*\.\s*$", texte, re.MULTILINE), (
            "docker-compose doit construire depuis la racine, comme Render."
        )
        assert "dockerfile: apps/api/Dockerfile" in texte


class TestDeploymentData:
    """Le fichier critique est bien versionne dans le depot."""

    def test_countries_geojson_present(self) -> None:
        assert COUNTRIES.is_file(), (
            "data/reference/countries.geojson est requis par le module "
            "buildings et doit etre versionne (il entre dans l'image Docker)."
        )
