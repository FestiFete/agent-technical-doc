#!/usr/bin/env python3
"""Phase 1 — Test « vraies dépendances » en local (sans déployer AWS).

Exécute la **vraie** orchestration contre un dépôt GitHub réel, avec les vraies
dépendances (auth GitHub App/PAT, téléchargement + extraction du tarball, analyse
Bedrock, génération draw.io, commit), **sans** la chaîne AWS (ni API Gateway, ni
SQS, ni Lambda, ni runtime AgentCore, ni Secrets Manager, ni DynamoDB).

Ce que ça valide, que l'injection de dépendances masque en tests unitaires :
  - signature JWT RS256 → token d'installation GitHub App (ou PAT) ;
  - ``download_tarball`` (⚠️ redirection 302 ``api.github.com`` → ``codeload``) ;
  - analyse LLM réelle (Strands + Bedrock) et parsing du JSON ;
  - assemblage Markdown + validation des schémas ``.drawio`` ;
  - restitution GitHub (commit + commentaire) — en mode réel uniquement.

Sécurité : **dry-run par défaut** (lectures + analyse réelles, écritures GitHub
interceptées et journalisées, aucune mutation du dépôt). ``--commit`` active les
écritures réelles — à réserver à un **dépôt bac-à-sable**.

Prérequis (voir e2e/README.md) :
  - dépendances Python : ``boto3``, ``strands-agents[otel]``, ``pyjwt[crypto]`` ;
  - credentials AWS avec accès Bedrock (``bedrock:InvokeModel``) + modèle activé ;
  - auth GitHub via env : ``GITHUB_APP_SECRET`` (JSON App) **ou** ``GITHUB_TOKEN`` (PAT) ;
  - une PR ouverte sur le dépôt de test (branche du dépôt, pas un fork).

Exemples :
  # Dry-run (par défaut) — rien n'est écrit sur GitHub
  GITHUB_TOKEN=ghp_xxx AWS_PROFILE=sandbox \\
    python e2e/local_run.py --repo acme/widget --pr 42

  # Commit réel sur la branche de la PR (dépôt bac-à-sable)
  GITHUB_APP_SECRET='{"app_id":"123","private_key":"-----BEGIN..."}' \\
    python e2e/local_run.py --repo acme/widget --pr 42 --commit
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid

# Rendre le package de l'agent importable quel que soit le cwd.
_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

from docagent import config  # noqa: E402
from docagent.orchestrator import OrchestratorDeps, run_documentation  # noqa: E402
from docagent.payload import parse_request  # noqa: E402

logger = logging.getLogger("e2e.local_run")

# Opérations d'écriture GitHub interceptées en dry-run.
_WRITE_METHODS = {
    "add_reaction", "create_blob", "create_tree", "create_commit",
    "update_ref", "post_issue_comment",
}


class DryRunClient:
    """Enveloppe un vrai ``GitHubClient`` : délègue les lectures, neutralise les
    écritures (journalisées) pour n'exercer aucune mutation du dépôt."""

    def __init__(self, real):
        self._real = real
        self._blob = 0

    # Lectures → vrai client (exercent RS256, tarball 302, API PR).
    def get_pull_request(self, *a, **k):
        return self._real.get_pull_request(*a, **k)

    def download_tarball(self, *a, **k):
        return self._real.download_tarball(*a, **k)

    def get_ref(self, *a, **k):
        return self._real.get_ref(*a, **k)

    def get_commit(self, *a, **k):
        return self._real.get_commit(*a, **k)

    # Écritures → no-op journalisé (formes de retour plausibles).
    def add_reaction(self, repo, comment_id, content="eyes"):
        logger.info("[dry-run] add_reaction(%s, comment=%s, %s)", repo, comment_id, content)
        return {}

    def create_blob(self, repo, content, encoding="utf-8"):
        self._blob += 1
        return {"sha": f"dryrun-blob-{self._blob}"}

    def create_tree(self, repo, base_tree, tree):
        logger.info("[dry-run] create_tree: %d entrées", len(tree))
        return {"sha": "dryrun-tree"}

    def create_commit(self, repo, message, tree_sha, parent_sha):
        logger.info("[dry-run] create_commit: %r (parent=%s)", message, parent_sha[:12])
        return {"sha": "DRYRUN0000000000000000000000000000000000"}

    def update_ref(self, repo, ref, sha, force=False):
        logger.info("[dry-run] update_ref(%s -> %s, force=%s)", ref, sha[:12], force)
        return {}

    def post_issue_comment(self, repo, issue, body):
        logger.info("[dry-run] post_issue_comment sur %s#%s :\n%s", repo, issue, body)
        return {}


def _resolve_local_token(repo_full_name: str) -> str:
    """Token depuis l'environnement (App JSON prioritaire, sinon PAT)."""
    app_secret = os.environ.get("GITHUB_APP_SECRET")
    if app_secret:
        from docagent.github_auth import resolve_token
        return resolve_token(json.loads(app_secret), repo_full_name,
                             api_base=config.GITHUB_API_BASE)
    pat = os.environ.get("GITHUB_TOKEN")
    if pat:
        return pat.strip()
    raise SystemExit(
        "Auth manquante : définir GITHUB_APP_SECRET (JSON App) ou GITHUB_TOKEN (PAT)."
    )


def _build_deps(*, dry_run: bool) -> OrchestratorDeps:
    def _get_token(repo_full_name: str) -> str:
        return _resolve_local_token(repo_full_name)

    def _make_client(token: str):
        from docagent.github_client import GitHubClient
        real = GitHubClient(token, api_base=config.GITHUB_API_BASE)
        return DryRunClient(real) if dry_run else real

    def _fetch_repo(client, repo_full_name: str, ref: str, workdir: str):
        from docagent.repo_reader import RepoReader, extract_tarball_safely
        tar = client.download_tarball(repo_full_name, ref)
        root = extract_tarball_safely(tar, workdir)
        return RepoReader(root)

    def _analyze(repo_context: dict) -> dict:
        from docagent.analyzer import BedrockAnalyzer
        return BedrockAnalyzer().analyze(repo_context)

    # Idempotence désactivée en local (pas de DynamoDB).
    return OrchestratorDeps(
        get_token=_get_token,
        make_client=_make_client,
        fetch_repo=_fetch_repo,
        analyze=_analyze,
        claim_idempotency=lambda key, corr: True,
        release_idempotency=lambda key: None,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Runner local « vraies dépendances »")
    parser.add_argument("--repo", required=True, help="Dépôt cible owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="Numéro de la PR")
    parser.add_argument("--commit", action="store_true",
                        help="Écrit réellement (commit + commentaire). Défaut : dry-run.")
    parser.add_argument("--model", help="Override MODEL_ID (ex. profil Haiku)")
    parser.add_argument("--region", help="Override BEDROCK_REGION")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if args.model:
        os.environ["MODEL_ID"] = args.model
    if args.region:
        os.environ["BEDROCK_REGION"] = args.region

    dry_run = not args.commit
    mode = "DRY-RUN (aucune écriture GitHub)" if dry_run else "COMMIT RÉEL"
    logger.info("Mode : %s | repo=%s pr=%s | modèle=%s région=%s",
                mode, args.repo, args.pr, config.MODEL_ID, config.BEDROCK_REGION)
    if not dry_run:
        logger.warning("Écritures RÉELLES activées — assurez-vous d'un dépôt bac-à-sable.")

    correlation_id = f"local-{uuid.uuid4().hex[:8]}"
    request = parse_request(
        {"repo_full_name": args.repo, "pr_number": args.pr, "correlation_id": correlation_id},
        None,
    )
    deps = _build_deps(dry_run=dry_run)

    resp = run_documentation(request, session_id=correlation_id, deps=deps)
    result = resp.get("result", {})

    print("\n===== RÉSULTAT =====")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = result.get("status")
    if status in ("complete",):
        print(f"\nOK ({mode}). Fichiers : {len(result.get('files', []))}")
        return 0
    print(f"\nStatut non nominal : {status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
