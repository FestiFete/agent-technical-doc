#!/usr/bin/env python3
"""Phase 2 — Vérification du smoke test après déploiement.

Après avoir commenté ``@agent-technical-doc`` sur une PR d'un dépôt autorisé (chaîne
déployée : webhook → SQS → worker → runtime), ce helper **sonde GitHub** et rend un
verdict automatique :

  - la documentation est-elle commitée sous ``docs/agent/`` sur la branche head ?
  - un **commentaire terminal** (succès / échec) a-t-il été posté sur la PR ?

Il ne déclenche rien : il observe le résultat produit par la chaîne réelle. Auth
via les mêmes variables que ``local_run.py`` (``GITHUB_APP_SECRET`` ou ``GITHUB_TOKEN``).

Exemple :
  read -rs GITHUB_TOKEN && export GITHUB_TOKEN
  python3 e2e/smoke_check.py --repo FestiFete/RogerVoiceTest --pr 1 --timeout 300
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

from docagent import config  # noqa: E402

# Marqueurs des commentaires terminaux (cf. docagent/comments.py).
_SUCCESS_MARKER = "Documentation technique générée"
_FAILURE_MARKER = "Documentation technique — échec"
_FORK_MARKER = "Documentation technique non générée"


def _classify_comments(comments):
    """Classe le commentaire terminal le plus récent (fonction pure, testable).

    Retourne ``(outcome, body)`` avec ``outcome`` ∈ {'success', 'failure',
    'fork', None}. Parcourt du plus récent au plus ancien.
    """
    for c in reversed(comments or []):
        body = c.get("body", "") if isinstance(c, dict) else ""
        if _SUCCESS_MARKER in body:
            return "success", body
        if _FAILURE_MARKER in body:
            return "failure", body
        if _FORK_MARKER in body:
            return "fork", body
    return None, ""


def _resolve_token(repo_full_name: str) -> str:
    from e2e.local_run import _resolve_local_token
    return _resolve_local_token(repo_full_name)


def _docs_committed(client, repo: str, ref: str) -> bool:
    """Vrai si le dossier docs/agent existe sur la ref (agent a commité)."""
    from docagent.github_client import GitHubError
    out_dir = config.DOC_OUTPUT_DIR
    try:
        client._api("GET", f"/repos/{repo}/contents/{out_dir}?ref={ref}")
        return True
    except GitHubError as exc:
        if exc.status == 404:
            return False
        raise


def _list_comments(client, repo: str, pr: int):
    resp = client._api("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100")
    return resp.json() or []


def check(client, repo: str, pr: int, *, timeout: float, interval: float, sleep=time.sleep):
    """Sonde jusqu'à obtenir un verdict ou expiration. Retourne un dict de résultat."""
    pr_data = client.get_pull_request(repo, pr)
    head_ref = (pr_data.get("head") or {}).get("ref", "")
    deadline = time.monotonic() + timeout
    while True:
        outcome, body = _classify_comments(_list_comments(client, repo, pr))
        docs = _docs_committed(client, repo, head_ref)
        if outcome == "success" and docs:
            return {"status": "PASS", "head_ref": head_ref, "docs": True, "comment": body}
        if outcome in ("failure", "fork"):
            return {"status": "FAIL", "head_ref": head_ref, "docs": docs,
                    "outcome": outcome, "comment": body}
        if time.monotonic() >= deadline:
            return {"status": "TIMEOUT", "head_ref": head_ref, "docs": docs,
                    "outcome": outcome}
        sleep(interval)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Smoke check post-déploiement (Phase 2)")
    parser.add_argument("--repo", required=True, help="Dépôt owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="Numéro de la PR")
    parser.add_argument("--timeout", type=float, default=300.0, help="Attente max (s)")
    parser.add_argument("--interval", type=float, default=10.0, help="Intervalle de sondage (s)")
    args = parser.parse_args(argv)

    from docagent.github_client import GitHubClient
    token = _resolve_token(args.repo)
    client = GitHubClient(token, api_base=config.GITHUB_API_BASE)

    print(f"Sondage {args.repo}#{args.pr} (timeout {args.timeout:.0f}s)…")
    res = check(client, args.repo, args.pr, timeout=args.timeout, interval=args.interval)

    print(f"\nRésultat : {res['status']} (branche={res.get('head_ref')}, "
          f"docs/agent présent={res.get('docs')})")
    if res.get("comment"):
        print("\n--- commentaire terminal ---")
        print(res["comment"])
    if res["status"] != "PASS":
        print("\nTracer le run : chercher le X-GitHub-Delivery (correlation_id) dans "
              "les logs des 3 composants :", file=sys.stderr)
        print("  /aws/lambda/<projet>-webhook, -worker, "
              "/aws/bedrock-agentcore/runtime/<agent>-<env>", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
