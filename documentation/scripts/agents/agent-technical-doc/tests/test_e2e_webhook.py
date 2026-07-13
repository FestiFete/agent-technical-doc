"""Phase 3 — Test E2E bout-en-bout (stack déployée requise).

Déclenche la chaîne réelle via un événement webhook synthétique **signé HMAC**
posté sur l'API Gateway, puis vérifie que la doc est commitée sous `docs/agent/`
et qu'un commentaire terminal de succès est posté.

**Skippé** par défaut : ne s'exécute que si les variables d'environnement d'une
stack déployée sont fournies. Marqueur ``e2e``.

Variables requises :
  - E2E_API_URL        URL du webhook (sortie Terraform ``ingestion.webhook_url``)
  - E2E_WEBHOOK_SECRET secret HMAC configuré côté GitHub/Secrets Manager
  - E2E_REPO           dépôt de test ``owner/repo`` (dans l'allowlist)
  - E2E_PR             numéro d'une PR ouverte
  - auth GitHub        ``GITHUB_TOKEN`` ou ``GITHUB_APP_SECRET`` (pour la vérification)
Optionnelles : E2E_MENTION (défaut ``@agent-technical-doc``), E2E_TIMEOUT (s).
"""
import os
import time

import pytest

from e2e import harness, smoke_check

pytestmark = pytest.mark.e2e

_REQUIRED = ("E2E_API_URL", "E2E_WEBHOOK_SECRET", "E2E_REPO", "E2E_PR")


def _env_or_skip() -> dict:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        pytest.skip("E2E désactivé (variables manquantes : %s)" % ", ".join(missing))
    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_APP_SECRET")):
        pytest.skip("E2E désactivé (auth GitHub manquante : GITHUB_TOKEN ou GITHUB_APP_SECRET)")
    return {
        "api_url": os.environ["E2E_API_URL"],
        "secret": os.environ["E2E_WEBHOOK_SECRET"],
        "repo": os.environ["E2E_REPO"],
        "pr": int(os.environ["E2E_PR"]),
        "mention": os.environ.get("E2E_MENTION", "@agent-technical-doc"),
        "timeout": float(os.environ.get("E2E_TIMEOUT", "420")),
    }


def test_end_to_end_webhook_to_doc():
    cfg = _env_or_skip()

    from docagent import config
    from docagent.github_client import GitHubClient
    from e2e.local_run import _resolve_local_token

    client = GitHubClient(_resolve_local_token(cfg["repo"]), api_base=config.GITHUB_API_BASE)

    # comment_id unique → pas de déduplication au niveau webhook.
    comment_id = int(time.time())
    event = harness.build_issue_comment_event(
        repo_full_name=cfg["repo"], pr_number=cfg["pr"], comment_id=comment_id,
        body=f"{cfg['mention']} génère la documentation (e2e {comment_id})",
    )

    status, body, delivery = harness.post_webhook(cfg["api_url"], secret=cfg["secret"], event=event)
    assert status in (200, 202), f"Webhook a répondu {status} : {body}"

    res = smoke_check.check(client, cfg["repo"], cfg["pr"],
                            timeout=cfg["timeout"], interval=10)
    assert res["status"] == "PASS", (
        f"E2E non concluant (delivery={delivery}) : {res}. "
        "Tracer via le correlation_id dans les logs des 3 composants."
    )
