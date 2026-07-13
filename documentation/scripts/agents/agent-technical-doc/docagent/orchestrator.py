"""Orchestration du run de documentation (clone → analyse → génération → commit
→ commentaire).

Conçu avec **injection de dépendances** (:class:`OrchestratorDeps`) pour être
testable de bout en bout sans réseau ni ``boto3``/``strands``. Les implémentations
réelles sont construites paresseusement par :func:`default_deps`.

Garanties :
- Les PR de fork sont refusées (garde-fou de sécurité).
- Un **commentaire terminal** est toujours posté (succès ou échec) dès qu'un
  client GitHub est disponible.
- Le commit est **unique** et confiné à ``docs/agent/`` (voir :mod:`committer`).
"""
from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

from . import comments, config, metrics
from .committer import commit_documents
from .correlation import mask_secrets
from .doc_builder import assemble_document_set
from .payload import InvocationRequest, status_response
from .selection import data_model_likely, select_files, stack_hints

logger = logging.getLogger(__name__)

COMMIT_MESSAGE = "docs(agent): documentation technique générée automatiquement"


@dataclass
class OrchestratorDeps:
    """Collaborateurs injectables (défauts réels via :func:`default_deps`)."""

    get_token: Callable[[str], str]  # (repo_full_name) -> token Bearer
    make_client: Callable[[str], object]
    fetch_repo: Callable[[object, str, str, str], object]  # (client, repo, ref, workdir) -> RepoReader
    analyze: Callable[[dict], dict]
    claim_idempotency: Callable[[str, str], bool]  # (key, correlation_id) -> True si à traiter
    # Relâche la revendication d'idempotence sur échec (autorise un re-run).
    # Défaut no-op : les tests qui n'en ont pas besoin restent inchangés.
    release_idempotency: Callable[[str], None] = lambda key: None


def default_deps() -> OrchestratorDeps:
    """Construit les dépendances réelles (imports différés)."""

    def _get_token(repo_full_name: str) -> str:
        from .github_auth import resolve_token
        from .secrets import get_secret_dict
        secret = get_secret_dict(config.GITHUB_TOKEN_SECRET_ARN, region=config.BEDROCK_REGION)
        return resolve_token(secret, repo_full_name, api_base=config.GITHUB_API_BASE)

    def _make_client(token: str):
        from .github_client import GitHubClient
        return GitHubClient(token, api_base=config.GITHUB_API_BASE)

    def _fetch_repo(client, repo_full_name: str, ref: str, workdir: str):
        from .repo_reader import RepoReader, extract_tarball_safely
        tar = client.download_tarball(repo_full_name, ref)
        root = extract_tarball_safely(tar, workdir)
        return RepoReader(root)

    def _analyze(repo_context: dict) -> dict:
        from .analyzer import BedrockAnalyzer
        return BedrockAnalyzer().analyze(repo_context)

    def _claim(key: str, correlation_id: str) -> bool:
        from .idempotency import claim
        return claim(key, correlation_id)

    def _release(key: str) -> None:
        from .idempotency import release
        release(key)

    return OrchestratorDeps(
        get_token=_get_token, make_client=_make_client,
        fetch_repo=_fetch_repo, analyze=_analyze, claim_idempotency=_claim,
        release_idempotency=_release,
    )


def _build_repo_context(request: InvocationRequest, reader) -> dict:
    tree = reader.list_tree()
    selected = select_files(tree)
    files = {path: reader.read_file(path) for path in selected}
    files = {p: c for p, c in files.items() if c}  # ignore lectures vides (budget)
    return {
        "repo_full_name": request.repo_full_name,
        "head_ref": request.head_ref,
        "pr_number": request.pr_number,
        "tree": selected,
        "stack_hints": stack_hints(tree),
        "data_model_likely": data_model_likely(tree),
        "files": files,
    }


def _resolve_pr_details(request: InvocationRequest, client, logger) -> InvocationRequest:
    """Complète head_sha/head_ref/is_fork via l'API GitHub (get pull request)."""
    pr = client.get_pull_request(request.base_repo_full_name, request.pr_number)
    head = pr.get("head", {}) or {}
    base = pr.get("base", {}) or {}
    head_repo = (head.get("repo") or {}).get("full_name", request.base_repo_full_name)
    base_repo = (base.get("repo") or {}).get("full_name", request.base_repo_full_name)
    is_fork = head_repo != base_repo
    resolved = request.resolved(
        head_sha=str(head.get("sha", "")),
        head_ref=str(head.get("ref", "")),
        base_repo_full_name=base_repo,
        is_fork=is_fork,
    )
    logger.info("PR résolue: head_ref=%s sha=%s fork=%s",
                resolved.head_ref, resolved.head_sha[:12], is_fork)
    return resolved


def run_documentation(
    request: InvocationRequest,
    *,
    session_id: str,
    logger=logger,
    deps: OrchestratorDeps | None = None,
    workdir: str | None = None,
) -> dict:
    """Exécute le run et émet une métrique EMF d'outcome (durée, fichiers)."""
    start = time.monotonic()
    resp = _execute(request, session_id=session_id, logger=logger, deps=deps, workdir=workdir)
    result = resp.get("result", {})
    try:
        metrics.emit_run(
            result.get("status", "unknown"),
            duration_ms=(time.monotonic() - start) * 1000.0,
            correlation_id=result.get("correlation_id", request.correlation_id),
            files=len(result.get("files", [])),
        )
    except Exception:  # noqa: BLE001 — l'observabilité ne doit jamais casser un run
        logger.debug("Emission métrique EMF échouée", exc_info=True)
    return resp


def _execute(
    request: InvocationRequest,
    *,
    session_id: str,
    logger=logger,
    deps: OrchestratorDeps | None = None,
    workdir: str | None = None,
) -> dict:
    """Exécute le run pour une PR. Renvoie une réponse de statut structurée."""
    # Garde-fou : refus des PR de fork.
    if request.is_fork or request.repo_full_name != request.base_repo_full_name:
        logger.info("PR de fork — run ignoré (repo=%s)", request.repo_full_name)
        return status_response(
            status="skipped_fork", session_id=session_id,
            correlation_id=request.correlation_id, message=comments.fork_comment(),
        )

    deps = deps or default_deps()
    client = None
    claimed = False
    try:
        token = deps.get_token(request.base_repo_full_name)
        client = deps.make_client(token)

        # Résolution des détails de PR si le payload ne les fournit pas
        # (la Lambda webhook n'a pas le token GitHub). On obtient head sha/ref
        # et le statut fork depuis l'API.
        if not request.is_resolved:
            request = _resolve_pr_details(request, client, logger)

        # Garde-fou fork (après résolution) : refus explicite + commentaire.
        if request.is_fork or request.repo_full_name != request.base_repo_full_name:
            logger.info("PR de fork (résolue) — run ignoré (repo=%s)", request.repo_full_name)
            try:
                client.post_issue_comment(
                    request.base_repo_full_name, request.pr_number, comments.fork_comment()
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Commentaire fork impossible: %s", mask_secrets(str(exc)))
            return status_response(
                status="skipped_fork", session_id=session_id,
                correlation_id=request.correlation_id, message=comments.fork_comment(),
            )

        # Accusé de réception (best-effort) — n'interrompt pas le run en cas d'échec.
        if request.comment_id:
            try:
                client.add_reaction(request.base_repo_full_name, request.comment_id, "eyes")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Réaction d'accusé impossible: %s", mask_secrets(str(exc)))

        # Idempotence forte (repo#pr#sha) : garantit UN seul run/commit même en
        # cas de rejeu SQS du worker ou de demandes concurrentes.
        if not deps.claim_idempotency(request.idempotency_key, request.correlation_id):
            logger.info("Run déjà traité/en cours (%s) — ignoré", request.idempotency_key)
            return status_response(
                status="skipped_duplicate", session_id=session_id,
                correlation_id=request.correlation_id,
                message="Documentation déjà générée pour ce commit.",
            )
        claimed = True

        # Clone (lecture seule) + contexte borné.
        wd = workdir or tempfile.mkdtemp(prefix="docagent-")
        reader = deps.fetch_repo(client, request.base_repo_full_name, request.head_sha, wd)
        repo_context = _build_repo_context(request, reader)

        # Analyse LLM (structurée) → assemblage déterministe.
        analysis = deps.analyze(repo_context)
        doc_set, diagram_paths, warnings = assemble_document_set(analysis)
        if warnings:
            logger.info("Avertissements d'assemblage: %s", "; ".join(warnings))

        # Commit unique confiné à docs/agent/.
        commit = commit_documents(
            client, repo_full_name=request.repo_full_name, head_ref=request.head_ref,
            files=doc_set.files, message=COMMIT_MESSAGE,
        )

        # Commentaire terminal de succès.
        missing = str(analysis.get("missing", "")) + (
            ("\n" + "\n".join(warnings)) if warnings else ""
        )
        body = comments.success_comment(
            summary=str(analysis.get("summary", "Documentation générée.")),
            files=commit["files"], commit_sha=commit["commit_sha"], missing=missing,
        )
        client.post_issue_comment(request.repo_full_name, request.pr_number, body)

        return status_response(
            status="complete", session_id=session_id,
            correlation_id=request.correlation_id,
            message="Documentation générée et commitée.",
            commit_sha=commit["commit_sha"], files=commit["files"],
        )

    except Exception as exc:  # noqa: BLE001 — on garantit un commentaire terminal
        reason = mask_secrets(str(exc))
        logger.error("Echec du run: %s", reason, exc_info=True)
        # Relâche la revendication d'idempotence pour autoriser un re-run sur le
        # même commit (sinon la clé in_progress bloquerait jusqu'au TTL).
        if claimed:
            try:
                deps.release_idempotency(request.idempotency_key)
            except Exception as exc2:  # noqa: BLE001 — best-effort
                logger.warning("Relâche idempotence impossible: %s", mask_secrets(str(exc2)))
        if client is not None:
            try:
                client.post_issue_comment(
                    request.repo_full_name, request.pr_number,
                    comments.failure_comment(reason=reason, correlation_id=request.correlation_id),
                )
            except Exception as exc2:  # noqa: BLE001
                logger.error("Commentaire d'échec impossible: %s", mask_secrets(str(exc2)))
        return status_response(
            status="failed", session_id=session_id,
            correlation_id=request.correlation_id, error=reason,
        )
