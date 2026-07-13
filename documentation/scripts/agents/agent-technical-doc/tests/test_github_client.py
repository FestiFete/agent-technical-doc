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


class _FlakyClient(GitHubClient):
    """Client dont ``_http`` échoue ``fail_times`` fois (transitoire) avant succès."""

    def __init__(self, *, fail_status, fail_times):
        super().__init__("t", api_base="https://api.github.com",
                         max_retries=3, sleep=lambda _d: None)
        self.fail_status = fail_status
        self.fail_times = fail_times
        self.attempts = 0

    def _http(self, method, url, *, headers, body):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise GitHubError(self.fail_status, "transient")
        return HttpResponse(200, {}, json.dumps({"ok": True}).encode())


def test_get_retried_on_transient_then_succeeds():
    client = _FlakyClient(fail_status=503, fail_times=2)
    out = client.get_pull_request("acme/widget", 1)  # GET
    assert out == {"ok": True}
    assert client.attempts == 3  # 2 échecs transitoires + 1 succès


def test_get_not_retried_on_permanent():
    client = _FlakyClient(fail_status=404, fail_times=1)
    with pytest.raises(GitHubError):
        client.get_pull_request("acme/widget", 1)
    assert client.attempts == 1  # 404 non transitoire → pas de rejeu


def test_write_not_retried_even_if_transient():
    # Les écritures (POST) ne sont jamais rejouées (risque de doublon).
    client = _FlakyClient(fail_status=503, fail_times=1)
    with pytest.raises(GitHubError):
        client.post_issue_comment("acme/widget", 42, "hello")
    assert client.attempts == 1


# --- secrets -----------------------------------------------------------------
def test_parse_secret_plain_pat():
    assert secrets._parse_secret_string("ghp_plain") == {"token": "ghp_plain"}


def test_parse_secret_json_pat():
    raw = json.dumps({"token": "ghp_fromjson"})
    assert secrets._parse_secret_string(raw) == {"token": "ghp_fromjson"}


def test_parse_secret_json_app():
    raw = json.dumps({"app_id": "1", "private_key": "PEM", "installation_id": 7})
    assert secrets._parse_secret_string(raw) == {"app_id": "1", "private_key": "PEM",
                                                 "installation_id": 7}


def test_parse_secret_empty_raises():
    with pytest.raises(ValueError):
        secrets._parse_secret_string("   ")


def test_get_secret_dict_requires_arn():
    secrets._reset_cache_for_tests()
    with pytest.raises(ValueError):
        secrets.get_secret_dict("", region="eu-central-1")
