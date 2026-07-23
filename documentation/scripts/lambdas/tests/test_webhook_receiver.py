"""Task 9 — Lambda webhook : signature HMAC, filtrage, autorisation, dedup."""
import base64
import hashlib
import hmac
import importlib.util
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "webhook-receiver", "handler.py")
_spec = importlib.util.spec_from_file_location("webhook_handler", _PATH)
handler = importlib.util.module_from_spec(_spec)
import sys as _sys
_sys.modules["webhook_handler"] = handler
_spec.loader.exec_module(handler)
Config = handler.Config


def _cfg(**over):
    cfg = Config(
        hmac_secret_arn="arn:secret", mention_handle="@agent-technical-doc",
        allowed_repos=["acme/widget"], allowed_assocs=["OWNER", "MEMBER", "COLLABORATOR"],
        queue_url="https://sqs/q", idempotency_table="tbl", ttl_days=30, region="eu-central-1",
    )
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def _payload(**over):
    base = {
        "action": "created",
        "issue": {"number": 42, "pull_request": {"url": "https://api/pr/42"}},
        "comment": {"id": 7, "body": "Salut @agent-technical-doc peux-tu documenter ?",
                    "author_association": "MEMBER"},
        "repository": {"full_name": "acme/widget"},
    }
    base.update(over)
    return base


# --- origine CloudFront (SEC-F1) ----------------------------------------------
def test_verify_origin_valid():
    assert handler.verify_origin("s3cr3t", "s3cr3t") is True


def test_verify_origin_invalid():
    assert handler.verify_origin("wrong", "s3cr3t") is False
    assert handler.verify_origin("", "s3cr3t") is False


def test_verify_origin_disabled_when_secret_empty():
    # secret non configuré (pas de CloudFront devant) -> vérification désactivée.
    assert handler.verify_origin("", "") is True
    assert handler.verify_origin("anything", "") is True


# --- signature ---------------------------------------------------------------
def test_verify_signature_valid():
    body = b'{"a":1}'
    secret = "s3cr3t"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert handler.verify_signature(body, sig, secret) is True


def test_verify_signature_invalid():
    assert handler.verify_signature(b"x", "sha256=deadbeef", "s") is False
    assert handler.verify_signature(b"x", "", "s") is False


# --- evaluate_comment --------------------------------------------------------
def test_evaluate_accepts_valid_mention():
    d = handler.evaluate_comment(_payload(), _cfg(), event_type="issue_comment", action="created")
    assert d.process is True
    assert d.repo_full_name == "acme/widget"
    assert d.pr_number == 42
    assert d.comment_id == 7


def test_evaluate_rejects_non_pr():
    p = _payload(issue={"number": 42})  # pas de pull_request
    d = handler.evaluate_comment(p, _cfg(), event_type="issue_comment", action="created")
    assert d.process is False


def test_evaluate_rejects_missing_mention():
    p = _payload(comment={"id": 7, "body": "sans mention", "author_association": "MEMBER"})
    d = handler.evaluate_comment(p, _cfg(), event_type="issue_comment", action="created")
    assert d.process is False


def test_evaluate_rejects_repo_not_in_allowlist():
    p = _payload(repository={"full_name": "evil/repo"})
    d = handler.evaluate_comment(p, _cfg(), event_type="issue_comment", action="created")
    assert d.process is False


def test_evaluate_rejects_empty_allowlist_failsafe():
    d = handler.evaluate_comment(_payload(), _cfg(allowed_repos=[]),
                                 event_type="issue_comment", action="created")
    assert d.process is False


def test_evaluate_rejects_unauthorized_author():
    p = _payload(comment={"id": 7, "body": "@agent-technical-doc", "author_association": "NONE"})
    d = handler.evaluate_comment(p, _cfg(), event_type="issue_comment", action="created")
    assert d.process is False


def test_evaluate_rejects_wrong_event_or_action():
    assert not handler.evaluate_comment(_payload(), _cfg(), event_type="push", action="created").process
    assert not handler.evaluate_comment(_payload(action="edited"), _cfg(),
                                        event_type="issue_comment", action="edited").process


# --- parse_api_event ---------------------------------------------------------
def test_parse_api_event_base64():
    raw = json.dumps({"x": 1}).encode()
    event = {"body": base64.b64encode(raw).decode(), "isBase64Encoded": True,
             "headers": {"X-Hub-Signature-256": "sha256=abc"}}
    body, headers = handler.parse_api_event(event)
    assert body == raw
    assert headers["x-hub-signature-256"] == "sha256=abc"


# --- garde-fou anti-DoS (rate limit) -----------------------------------------
def test_window_bucket_and_key():
    assert handler._window_bucket(7200, 3600) == 2
    assert handler._window_bucket(7199, 3600) == 1
    assert handler._rate_key("acme/widget", 2) == "ratelimit#acme/widget#2"


def test_rate_limit_disabled_when_zero():
    # max_runs<=0 → jamais limité, aucun accès DynamoDB.
    assert handler._rate_limited("tbl", "acme/widget", 0, 3600, "eu-central-1") is False


def test_rate_limit_allows_under_max(monkeypatch):
    monkeypatch.setattr(handler, "_increment_repo_counter", lambda *a, **k: 5)
    assert handler._rate_limited("tbl", "acme/widget", 20, 3600, "eu-central-1", now=1000) is False


def test_rate_limit_allows_exactly_at_max(monkeypatch):
    monkeypatch.setattr(handler, "_increment_repo_counter", lambda *a, **k: 20)
    assert handler._rate_limited("tbl", "acme/widget", 20, 3600, "eu-central-1", now=1000) is False


def test_rate_limit_blocks_over_max(monkeypatch):
    monkeypatch.setattr(handler, "_increment_repo_counter", lambda *a, **k: 21)
    assert handler._rate_limited("tbl", "acme/widget", 20, 3600, "eu-central-1", now=1000) is True
