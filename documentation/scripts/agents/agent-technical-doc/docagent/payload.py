"""Parsing du payload d'invocation et construction des réponses de statut.

Logique pure (aucune dépendance AWS/strands) afin d'être unit-testable.

Le payload transmis par la Lambda worker à ``InvokeAgentRuntime`` ne contient
que des métadonnées (pas de contenu de dépôt) :

    {
      "repo_full_name": "owner/repo",
      "pr_number": 42,
      "head_sha": "abc123...",
      "head_ref": "feature/x",
      "base_repo_full_name": "owner/repo",
      "comment_id": 123456,
      "is_fork": false,
      "correlation_id": "..."
    }
"""
from __future__ import annotations

from dataclasses import dataclass

from . import correlation


@dataclass(frozen=True)
class InvocationRequest:
    repo_full_name: str
    pr_number: int
    head_sha: str
    head_ref: str
    base_repo_full_name: str
    comment_id: int | None
    is_fork: bool
    correlation_id: str

    @property
    def idempotency_key(self) -> str:
        return correlation.idempotency_key(self.repo_full_name, self.pr_number, self.head_sha)

    @property
    def is_resolved(self) -> bool:
        """Vrai si les détails de PR (sha/ref) sont connus."""
        return bool(self.head_sha and self.head_ref)

    def resolved(self, *, head_sha: str, head_ref: str, base_repo_full_name: str,
                 is_fork: bool) -> "InvocationRequest":
        """Retourne une copie enrichie des détails de PR (résolus via l'API)."""
        return InvocationRequest(
            repo_full_name=self.repo_full_name,
            pr_number=self.pr_number,
            head_sha=head_sha,
            head_ref=head_ref,
            base_repo_full_name=base_repo_full_name,
            comment_id=self.comment_id,
            is_fork=is_fork,
            correlation_id=self.correlation_id,
        )


class PayloadError(ValueError):
    """Payload d'invocation invalide (champ requis manquant)."""


def parse_request(payload: dict, context=None) -> InvocationRequest:
    """Construit une ``InvocationRequest`` à partir du payload d'invocation.

    Champs requis : ``repo_full_name`` et ``pr_number``. Les détails de PR
    (``head_sha``, ``head_ref``, ``is_fork``, ``base_repo_full_name``) sont
    optionnels : s'ils sont absents, l'orchestrateur les résout via l'API GitHub
    (la Lambda webhook n'a pas besoin du token GitHub). Lève ``PayloadError`` si
    un champ requis est absent.
    """
    payload = payload or {}
    missing = [k for k in ("repo_full_name", "pr_number") if not payload.get(k)]
    if missing:
        raise PayloadError(f"Champs requis manquants dans le payload: {', '.join(missing)}")

    session_from_ctx = getattr(context, "session_id", None) if context is not None else None
    corr = correlation.coalesce_correlation_id(
        payload.get("correlation_id"), session_from_ctx
    )

    base_repo = payload.get("base_repo_full_name") or payload["repo_full_name"]
    return InvocationRequest(
        repo_full_name=str(payload["repo_full_name"]),
        pr_number=int(payload["pr_number"]),
        head_sha=str(payload.get("head_sha", "")),
        head_ref=str(payload.get("head_ref", "")),
        base_repo_full_name=str(base_repo),
        comment_id=(int(payload["comment_id"]) if payload.get("comment_id") else None),
        is_fork=bool(payload.get("is_fork", False)),
        correlation_id=corr,
    )


def status_response(
    *,
    status: str,
    session_id: str,
    correlation_id: str,
    message: str = "",
    commit_sha: str = "",
    files: list[str] | None = None,
    error: str = "",
) -> dict:
    """Réponse structurée renvoyée par l'entrypoint.

    ``status`` ∈ {accepted, complete, skipped_fork, skipped_duplicate, failed,
    invalid_request}. ``accepted`` = run lancé en tâche de fond (asynchrone) ;
    le statut terminal réel est restitué via le commentaire de PR.
    """
    return {
        "result": {
            "status": status,
            "sessionId": session_id,
            "correlation_id": correlation_id,
            "message": message,
            "commit_sha": commit_sha,
            "files": files or [],
            "error": error,
        }
    }
