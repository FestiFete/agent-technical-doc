"""Task 1 — parsing du payload d'invocation + réponse de statut structurée."""
import pytest

from docagent import correlation
from docagent.orchestrator import run_documentation
from docagent.payload import PayloadError, parse_request, status_response


class _Ctx:
    def __init__(self, session_id):
        self.session_id = session_id


def _valid_payload(**over):
    base = {
        "repo_full_name": "acme/widget",
        "pr_number": 42,
        "head_sha": "abcdef1234567890",
        "head_ref": "feature/x",
        "base_repo_full_name": "acme/widget",
        "comment_id": 999,
        "is_fork": False,
        "correlation_id": "corr-123",
    }
    base.update(over)
    return base


def test_parse_request_ok():
    req = parse_request(_valid_payload(), _Ctx("sess-1"))
    assert req.repo_full_name == "acme/widget"
    assert req.pr_number == 42
    assert req.correlation_id == "corr-123"
    assert req.idempotency_key == "acme/widget#42#abcdef1234567890"


def test_parse_request_missing_fields():
    with pytest.raises(PayloadError):
        parse_request({"repo_full_name": "acme/widget"}, None)


def test_parse_request_generates_correlation_id_when_absent():
    req = parse_request(_valid_payload(correlation_id=None), None)
    assert req.correlation_id  # généré


def test_status_response_shape():
    resp = status_response(
        status="complete", session_id="s1", correlation_id="c1",
        message="ok", commit_sha="deadbeef", files=["docs/agent/overview.md"],
    )
    r = resp["result"]
    assert r["status"] == "complete"
    assert r["sessionId"] == "s1"
    assert r["correlation_id"] == "c1"
    assert r["files"] == ["docs/agent/overview.md"]


def test_orchestrator_rejects_fork():
    req = parse_request(_valid_payload(is_fork=True), _Ctx("sess-1"))
    resp = run_documentation(req, session_id="sess-1")
    assert resp["result"]["status"] == "skipped_fork"


def test_mask_secrets_redacts_pat():
    raw = "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 used"
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in correlation.mask_secrets(raw)
    assert "REDACTED" in correlation.mask_secrets(raw)
