"""Corrélation de bout en bout et masquage des secrets.

Le ``correlation_id`` relie l'événement GitHub (X-GitHub-Delivery), le message
SQS et la session AgentCore, pour tracer un run unique dans les logs des trois
composants (Operational Excellence).
"""
from __future__ import annotations

import re
import uuid


def new_correlation_id() -> str:
    """Génère un identifiant de corrélation court et lisible."""
    return uuid.uuid4().hex


def coalesce_correlation_id(*candidates: str | None) -> str:
    """Retourne le premier identifiant non vide, sinon en génère un."""
    for c in candidates:
        if c and str(c).strip():
            return str(c).strip()
    return new_correlation_id()


# Motifs de secrets fréquents (tokens GitHub, en-têtes Authorization, etc.).
_SECRET_PATTERNS = [
    re.compile(r"gh[posru]_[A-Za-z0-9]{20,}"),        # PAT GitHub (ghp_, gho_, ...)
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),       # fine-grained PAT
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer|token)\s+\S+"),
    re.compile(r"(?i)(x-hub-signature-256\s*[:=]\s*)\S+"),
]


def mask_secrets(text: str) -> str:
    """Masque les secrets connus dans une chaîne avant journalisation.

    Défense en profondeur : le token ne doit jamais apparaître dans les logs,
    même si un message d'erreur venait à l'inclure par accident.
    """
    if not text:
        return text
    masked = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            masked = pattern.sub(r"\1***REDACTED***", masked)
        else:
            masked = pattern.sub("***REDACTED***", masked)
    return masked


def idempotency_key(repo_full_name: str, pr_number: int | str, head_sha: str) -> str:
    """Clé d'idempotence stable ``owner/repo#<pr>#<sha>``."""
    return f"{repo_full_name}#{pr_number}#{head_sha}"
