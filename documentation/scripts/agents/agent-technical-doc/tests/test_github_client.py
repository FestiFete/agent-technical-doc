"""Task 2 — client GitHub : en-têtes, token non journalisé, opérations de base."""
import json
import logging

import pytest

from docagent import secrets
from docagent.github_client import GitHubClient, GitHubError, HttpResponse


class _RecordingClient(GitHubClient):
    """Client qui capture les appels HTTP au lieu de les émettre."""

    def __init__(self, token, responses=None):
        super().__init__(token, api_base="https://api.github.com")
        self.calls = []
        self._responses = responses or {}

    def _http(self, method, url, *, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        key = (method, url)
        resp = self._responses.get(key)
        if resp is None:
            return HttpResponse(200, {}, json.dumps({"ok": True}).encode())
        return resp


def test_authorization_header_present():
    client = _RecordingClient("ghp_secrettoken")
    client.get_pull_request("acme/widget", 1)
    headers = client.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer ghp_secrettoken"
    assert headers["X-GitHub-Api-Version"]


def test_download_tarball_uses_correct_path():
    client = _RecordingClient(
        "t", responses={("GET", "https://api.github.com/repos/acme/widget/tarball/deadbeef"):
                        HttpResponse(200, {}, b"TARBYTES")})
    data = client.download_tarball("acme/widget", "deadbeef")
    assert data == b"TARBYTES"


def test_add_reaction_posts_eyes():
    client = _RecordingClient("t")
    client.add_reaction("acme/widget", 555, "eyes")
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/issues/comments/555/reactions")
    assert json.loads(call["body"])["content"] == "eyes"


def test_post_issue_comment_body():
    client = _RecordingClient("t")
    client.post_issue_comment("acme/widget", 42, "hello")
    call = client.calls[0]
    assert call["url"].endswith("/issues/42/comments")
    assert json.loads(call["body"])["body"] == "hello"


def test_token_never_appears_in_logs(caplog):
    client = _RecordingClient("ghp_supersecretvalue123456789")
    with caplog.at_level(logging.DEBUG):
        client.get_pull_request("acme/widget", 1)
    assert "ghp_supersecretvalue123456789" not in caplog.text


def test_github_error_flags_transient():
    assert GitHubError(503, "x").transient is True
    assert GitHubError(404, "x").transient is False


# --- secrets -----------------------------------------------------------------
def test_extract_token_plain():
    assert secrets._extract_token("ghp_plain", "token") == "ghp_plain"


def test_extract_token_json():
    raw = json.dumps({"token": "ghp_fromjson"})
    assert secrets._extract_token(raw, "token") == "ghp_fromjson"


def test_extract_token_json_custom_key():
    raw = json.dumps({"github_token": "ghp_x"})
    assert secrets._extract_token(raw, "nonexistent") == "ghp_x"


def test_get_github_token_requires_arn():
    secrets._reset_cache_for_tests()
    with pytest.raises(ValueError):
        secrets.get_github_token("", region="eu-central-1")
