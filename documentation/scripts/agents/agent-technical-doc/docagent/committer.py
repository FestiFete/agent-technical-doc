"""Commit atomique des livrables via l'API Git Data de GitHub.

Invariant de sécurité : tous les fichiers sont validés par
:func:`paths.normalize_output_path` (résidence forcée sous ``docs/agent/``) AVANT
tout appel réseau. La branche et le dépôt cibles sont **injectés** par
l'orchestrateur (issus du payload signé), jamais dérivés du contenu lu.

La restitution se fait en **un seul commit** (create tree → create commit →
update ref), quel que soit le nombre de fichiers.
"""
from __future__ import annotations

import logging

from .config import DOC_OUTPUT_DIR
from .paths import PathNotAllowedError, normalize_output_path

logger = logging.getLogger(__name__)


class CommitTargetError(RuntimeError):
    """Cible de commit invalide (branche vide, fichier hors périmètre)."""


def validate_files(files: dict[str, str], *, output_dir: str = DOC_OUTPUT_DIR) -> dict[str, str]:
    """Normalise et valide tous les chemins. Lève si l'un sort du périmètre."""
    if not files:
        raise CommitTargetError("Aucun fichier à commiter")
    validated: dict[str, str] = {}
    for path, content in files.items():
        try:
            norm = normalize_output_path(path, output_dir=output_dir)
        except PathNotAllowedError as exc:
            raise CommitTargetError(str(exc)) from exc
        validated[norm] = content
    return validated


def commit_documents(
    client,
    *,
    repo_full_name: str,
    head_ref: str,
    files: dict[str, str],
    message: str,
    output_dir: str = DOC_OUTPUT_DIR,
) -> dict:
    """Commite ``files`` en un seul commit sur la branche ``head_ref``.

    Retourne ``{"commit_sha", "files", "branch"}``. Lève ``CommitTargetError`` si
    la cible est invalide, ou propage ``GitHubError`` en cas d'échec API.
    """
    if not head_ref or not str(head_ref).strip():
        raise CommitTargetError("Branche head vide — cible de commit invalide")
    head_ref = str(head_ref).strip()
    # Garde-fou : jamais de branche par défaut protégée dérivée d'ailleurs ;
    # on écrit exactement sur la branche de la PR fournie.
    ref = f"heads/{head_ref}"

    validated = validate_files(files, output_dir=output_dir)

    # 1. Tip actuel de la branche (parent + base_tree) — évite les
    #    non-fast-forward et garde le commit sur la bonne branche.
    ref_data = client.get_ref(repo_full_name, ref)
    tip_sha = ref_data["object"]["sha"]
    base_commit = client.get_commit(repo_full_name, tip_sha)
    base_tree_sha = base_commit["tree"]["sha"]

    # 2. Un blob par fichier.
    tree_entries = []
    for path, content in sorted(validated.items()):
        blob = client.create_blob(repo_full_name, content, encoding="utf-8")
        tree_entries.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })

    # 3. Arbre + commit + mise à jour de la ref (fast-forward only).
    new_tree = client.create_tree(repo_full_name, base_tree_sha, tree_entries)
    new_commit = client.create_commit(repo_full_name, message, new_tree["sha"], tip_sha)
    client.update_ref(repo_full_name, ref, new_commit["sha"], force=False)

    logger.info(
        "Commit documentation: %d fichiers sur %s (commit=%s)",
        len(validated), head_ref, new_commit["sha"][:12],
    )
    return {
        "commit_sha": new_commit["sha"],
        "files": sorted(validated.keys()),
        "branch": head_ref,
    }
