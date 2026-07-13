"""Tests du harnais E2E (Phase 3) — hors ligne.

Garantit que l'événement synthétique + signature produits par `harness` seraient
**acceptés par la vraie logique du webhook** (signature HMAC + filtrage), sans
stack déployée. La Lambda webhook est importée par chemin (comme sa propre suite).
"""
import hashlib
import hmac
import importlib.util
import json
import os
import sys

from e2e import harness

# Import de la Lambda webhook (…/scripts/lambdas/webhook-receiver/handler.py).
_SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_WH_PATH = os.path.join(_SCRIPTS, "lambdas", "webhook-receiver", "handler.py")
_spec = importlib.util.spec_from_file_location("webhook_handler_x", _WH_PATH)
webhook = importlib.util.module_from_spec(_spec)
sys.modules["webhook_handler_x"] = webhook  # requis avant exec (dataclass Config)
_spec.loader.exec_module(webhook)


def test_build_event_structure():
    ev = harness.build_issue_comment_event(
        repo_full_name="acme/widget", pr_number=42, comment_id=7,
        body="@agent-technical-doc documente stp",
    )
    assert ev["action"] == "created"
    assert ev["issue"]["number"] == 42
    assert "pull_request" in ev["issue"]
    assert ev["comment"]["id"] == 7
    assert ev["repository"]["full_name"] == "acme/widget"


def test_sign_payload_matches_hmac():
    body = b'{"x":1}'
    expected = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert harness.sign_payload("s3cr3t", body) == expected


def test_signature_accepted_by_real_webhook():
    secret = "un-secret-de-test"
    ev = harness.build_issue_comment_event(
        repo_full_name="acme/widget", pr_number=1, comment_id=123,
        body="@agent-technical-doc go",
    )
    body = json.dumps(ev).encode("utf-8")
    sig = harness.sign_payload(secret, body)
    assert webhook.verify_signature(body, sig, secret) is True
    # Une signature calculée avec un autre secret est rejetée.
    assert webhook.verify_signature(body, harness.sign_payload("autre", body), secret) is False


def test_event_accepted_by_real_evaluate_comment():
    ev = harness.build_issue_comment_event(
        repo_full_name="acme/widget", pr_number=1, comment_id=123,
        body="@agent-technical-doc go", author_association="MEMBER",
    )
    cfg = webhook.Config(
        hmac_secret_arn="arn", mention_handle="@agent-technical-doc",
        allowed_repos=["acme/widget"], allowed_assocs=["OWNER", "MEMBER", "COLLABORATOR"],
        queue_url="q", idempotency_table="t", ttl_days=30, region="eu-central-1",
    )
    decision = webhook.evaluate_comment(ev, cfg, event_type="issue_comment", action="created")
    assert decision.process is True
    assert decision.repo_full_name == "acme/widget"
    assert decision.pr_number == 1
    assert decision.comment_id == 123
