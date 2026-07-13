"""Configuration centrale de l'agent (lue depuis l'environnement).

Toutes les valeurs ont un défaut sûr pour le POC. Les plafonds de lecture
bornent le contexte envoyé au LLM (coût + latence + sécurité).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _list_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "")
    items = [p.strip() for p in raw.split(",") if p.strip()]
    return items or list(default)


# Répertoire de sortie (dans le dépôt cible) : tous les livrables y sont écrits.
# Garde-fou de sécurité : le tool de commit refuse tout chemin hors de ce prefix.
DOC_OUTPUT_DIR = os.environ.get("DOC_OUTPUT_DIR", "docs/agent").strip("/")

# Handle mentionné qui déclenche l'agent (informe le prompt et les messages).
MENTION_HANDLE = os.environ.get("MENTION_HANDLE", "@agent-technical-doc")

# Dossiers et extensions ignorés lors de la lecture du dépôt.
VENDORED_DIRS = _list_env(
    "VENDORED_DIRS",
    [
        ".git", "node_modules", "vendor", "dist", "build", "target",
        ".venv", "venv", "__pycache__", ".terraform", ".idea", ".vscode",
        "coverage", ".next", ".nuxt", ".gradle", ".mvn", "bin", "obj",
    ],
)

# Extensions considérées comme binaires / non pertinentes (lecture ignorée).
BINARY_EXTENSIONS = _list_env(
    "BINARY_EXTENSIONS",
    [
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".pdf",
        ".zip", ".gz", ".tar", ".tgz", ".rar", ".7z", ".jar", ".war",
        ".class", ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
        ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".avi",
        ".lock", ".pyc", ".pdb", ".wasm",
    ],
)


@dataclass(frozen=True)
class ReadCaps:
    """Plafonds de lecture, bornant le contexte et l'usage mémoire.

    ``max_total_bytes`` est volontairement calé **sous la fenêtre de contexte** des
    modèles (~200K tokens ≈ ~800 Ko de texte) pour éviter tout dépassement, avec de
    la marge pour le prompt système et la réponse. Ces valeurs pilotent directement
    le coût Bedrock (tokens d'entrée) et la latence ; toutes surchargeables par env.
    """

    max_files: int = field(default_factory=lambda: _int_env("MAX_FILES", 400))
    max_file_bytes: int = field(default_factory=lambda: _int_env("MAX_FILE_BYTES", 80_000))
    max_total_bytes: int = field(default_factory=lambda: _int_env("MAX_TOTAL_BYTES", 1_200_000))
    max_selected_files: int = field(default_factory=lambda: _int_env("MAX_SELECTED_FILES", 40))


def read_caps() -> ReadCaps:
    return ReadCaps()


# Secrets Manager
GITHUB_TOKEN_SECRET_ARN = os.environ.get("GITHUB_TOKEN_SECRET_ARN", "")

# API GitHub (permet de cibler GitHub Enterprise plus tard sans changer le code).
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
GITHUB_SERVER = os.environ.get("GITHUB_SERVER", "github.com")

# Bedrock
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "eu-central-1"))

# Sélection de modèle à deux niveaux (coût / qualité).
# - MODEL_ID : modèle primaire, économique (Haiku), utilisé par défaut.
# - MODEL_ID_ESCALATION : modèle puissant (Sonnet), utilisé pour les dépôts
#   volumineux/complexes, où un contexte plus riche justifie une analyse plus fine.
# L'escalade est décidée par du code déterministe (voir analyzer.select_model)
# à partir de la taille du contexte sélectionné (nombre de fichiers / octets).
MODEL_ID = os.environ.get("MODEL_ID", "eu.anthropic.claude-haiku-4-5")
MODEL_ID_ESCALATION = os.environ.get("MODEL_ID_ESCALATION", "eu.anthropic.claude-sonnet-4-6")

# Seuils d'escalade sur le contexte sélectionné (0 = critère désactivé).
MODEL_ESCALATION_MAX_FILES = _int_env("MODEL_ESCALATION_MAX_FILES", 25)
MODEL_ESCALATION_MAX_BYTES = _int_env("MODEL_ESCALATION_MAX_BYTES", 400_000)
