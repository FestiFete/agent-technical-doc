"""Sélection heuristique des fichiers à lire et indices neutres de stack.

Conformément à la décision 6a, l'analyse repose sur le raisonnement du LLM. Ce
module ne fait PAS de parsing sémantique : il se contente de **prioriser** quels
fichiers lire (budget de contexte borné) à partir de leur **chemin/nom** — jamais
de leur contenu. C'est un point de sécurité : le classement est insensible au
contenu, donc un fichier hostile (prompt-injection) ne peut pas modifier la
sélection ni la cible d'écriture.

Les « indices » (``stack_hints``, ``data_model_likely``) sont dérivés uniquement
des noms de fichiers et servent à orienter la lecture ; ils sont transmis au LLM
comme données neutres, pas comme vérité.
"""
from __future__ import annotations

import os

from .config import ReadCaps, read_caps

# Manifestes de dépendances par écosystème (nom de fichier -> écosystème).
MANIFEST_FILES: dict[str, str] = {
    "package.json": "node",
    "yarn.lock": "node",
    "pnpm-lock.yaml": "node",
    "tsconfig.json": "typescript",
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "pipfile": "python",
    "pom.xml": "java-maven",
    "build.gradle": "java-gradle",
    "build.gradle.kts": "java-gradle",
    "go.mod": "go",
    "cargo.toml": "rust",
    "composer.json": "php",
    "gemfile": "ruby",
    "csproj": "dotnet",
    "build.sbt": "scala",
    "mix.exs": "elixir",
    "pubspec.yaml": "dart",
}

# Fichiers de haute valeur documentaire (nom exact ou préfixe, en minuscules).
HIGH_VALUE_NAMES = (
    "readme", "architecture", "contributing", "changelog", "makefile",
    "dockerfile", "docker-compose", "openapi", "swagger", "serverless.yml",
    "main.tf", "variables.tf", "outputs.tf",
)

# Indices de points d'entrée applicatifs (nom de fichier, sans extension).
ENTRYPOINT_STEMS = ("main", "index", "app", "server", "wsgi", "asgi", "manage", "cli", "program")

# Indices d'un modèle de données (pour décider l'inclusion du diagramme ER).
DATA_MODEL_DIR_HINTS = ("migrations", "models", "entities", "schema", "domain")
DATA_MODEL_FILE_HINTS = (".sql", ".prisma", "schema.rb", "models.py", "entity.")


def _basename_lower(rel_path: str) -> str:
    return os.path.basename(rel_path).lower()


def _score(rel_path: str) -> int:
    """Score de priorité (plus haut = lu en premier). Basé sur le chemin seul."""
    name = _basename_lower(rel_path)
    stem, ext = os.path.splitext(name)
    depth = rel_path.count("/")
    score = 0

    if name in MANIFEST_FILES or ext.lstrip(".") in ("csproj",):
        score += 100
    if any(name.startswith(h) for h in HIGH_VALUE_NAMES):
        score += 80
    if name.endswith(".tf"):
        score += 40
    if stem in ENTRYPOINT_STEMS:
        score += 50
    if any(h in rel_path.lower().split("/") for h in DATA_MODEL_DIR_HINTS):
        score += 25
    if ext in (".md", ".rst"):
        score += 20
    if ext in (".yml", ".yaml", ".toml", ".ini", ".cfg", ".json"):
        score += 10
    # Les fichiers proches de la racine sont souvent plus structurants.
    score += max(0, 10 - depth)
    return score


def select_files(tree: list[str], caps: ReadCaps | None = None) -> list[str]:
    """Retourne les fichiers à lire, triés par priorité et plafonnés.

    Tri déterministe : score décroissant, puis chemin alphabétique (stable).
    """
    caps = caps or read_caps()
    ranked = sorted(tree, key=lambda p: (-_score(p), p))
    return ranked[: caps.max_selected_files]


def stack_hints(tree: list[str]) -> dict[str, list[str]]:
    """Indices d'écosystèmes détectés à partir des noms de manifestes présents.

    Retourne {écosystème: [chemins des manifestes]}. Purement indicatif.
    """
    hints: dict[str, list[str]] = {}
    for rel in tree:
        name = _basename_lower(rel)
        eco = MANIFEST_FILES.get(name)
        if eco is None and name.endswith(".csproj"):
            eco = "dotnet"
        if eco:
            hints.setdefault(eco, []).append(rel)
    return hints


def data_model_likely(tree: list[str]) -> bool:
    """Vrai si l'arborescence suggère un modèle de données (→ diagramme ER)."""
    for rel in tree:
        low = rel.lower()
        parts = low.split("/")
        if any(h in parts for h in DATA_MODEL_DIR_HINTS):
            return True
        if any(h in low for h in DATA_MODEL_FILE_HINTS):
            return True
    return False
