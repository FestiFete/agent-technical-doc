"""Garde-fou de chemin des livrables — invariant de sécurité central.

Tout fichier produit par l'agent DOIT résider sous ``DOC_OUTPUT_DIR``
(``docs/agent`` par défaut). Cette contrainte est appliquée par le code, pas par
le prompt : ni le contenu du dépôt ni le LLM ne peuvent faire écrire l'agent
ailleurs (anti prompt-injection). Utilisé par :mod:`doc_builder` (Task 4) et par
le committer GitHub (Task 6).
"""
from __future__ import annotations

import posixpath

from .config import DOC_OUTPUT_DIR

ALLOWED_EXTENSIONS = (".md", ".drawio")


class PathNotAllowedError(ValueError):
    """Chemin de sortie hors périmètre autorisé."""


def normalize_output_path(path: str, *, output_dir: str = DOC_OUTPUT_DIR) -> str:
    """Normalise et valide un chemin de livrable.

    - Interdit les chemins absolus et le path traversal (``..``).
    - Force la résidence sous ``output_dir`` (l'ajoute si absent).
    - Restreint aux extensions autorisées (``.md``, ``.drawio``).

    Retourne le chemin relatif POSIX normalisé, ou lève ``PathNotAllowedError``.
    """
    if not path or not str(path).strip():
        raise PathNotAllowedError("Chemin vide")

    raw = str(path).strip().replace("\\", "/")
    output_dir = output_dir.strip("/")

    if raw.startswith("/"):
        raise PathNotAllowedError(f"Chemin absolu interdit: {path}")

    # Préfixe avec output_dir si le chemin ne commence pas déjà par lui.
    if raw == output_dir or raw.startswith(output_dir + "/"):
        candidate = raw
    else:
        candidate = f"{output_dir}/{raw}"

    normalized = posixpath.normpath(candidate)

    # normpath résout les ".." : on vérifie qu'on reste bien confiné.
    if normalized != output_dir and not normalized.startswith(output_dir + "/"):
        raise PathNotAllowedError(
            f"Chemin hors du répertoire autorisé '{output_dir}/': {path}"
        )
    if ".." in normalized.split("/"):
        raise PathNotAllowedError(f"Path traversal interdit: {path}")

    ext = posixpath.splitext(normalized)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise PathNotAllowedError(
            f"Extension non autorisée '{ext}' (autorisées: {', '.join(ALLOWED_EXTENSIONS)})"
        )

    return normalized
