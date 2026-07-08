"""Construction des commentaires terminaux postés sur la PR (logique pure)."""
from __future__ import annotations

from .config import DOC_OUTPUT_DIR


def success_comment(*, summary: str, files: list[str], commit_sha: str,
                    missing: str = "") -> str:
    file_lines = "\n".join(f"- `{f}`" for f in sorted(files)) or "_aucun_"
    missing_block = f"\n\n**Limites / à compléter :** {missing}" if missing.strip() else ""
    short_sha = commit_sha[:7] if commit_sha else ""
    return (
        "## 📚 Documentation technique générée\n\n"
        f"{summary.strip()}\n\n"
        f"**Fichiers ajoutés/mis à jour** (`{DOC_OUTPUT_DIR}/`), commit `{short_sha}` :\n"
        f"{file_lines}"
        f"{missing_block}\n"
    )


def failure_comment(*, reason: str, correlation_id: str = "") -> str:
    corr = f"\n\n_Réf. corrélation : `{correlation_id}`_" if correlation_id else ""
    return (
        "## ⚠️ Documentation technique — échec\n\n"
        "La génération de documentation n'a pas pu aboutir.\n\n"
        f"**Raison :** {reason.strip()}"
        f"{corr}\n"
    )


def fork_comment() -> str:
    return (
        "## ℹ️ Documentation technique non générée\n\n"
        "Les Pull Requests issues de **forks** ne sont pas prises en charge pour "
        "le moment (le contenu n'est pas maîtrisé et la branche n'est pas "
        "accessible en écriture). Relancez depuis une branche du dépôt d'origine.\n"
    )
