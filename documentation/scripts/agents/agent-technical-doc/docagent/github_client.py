"""Client GitHub minimal basé sur la bibliothèque standard (``urllib``).

Aucune dépendance tierce (pas de ``requests``) pour garder l'image légère et le
module testable. Toutes les requêtes HTTP passent par :meth:`GitHubClient._http`,
que les tests peuvent remplacer (monkeypatch) pour éviter tout accès réseau.

Sécurité :
- Le token n'est ajouté qu'en en-tête ``Authorization`` et n'est jamais journalisé.
- Le client cible ``api.github.com`` par défaut (``GITHUB_API_BASE`` configurable
  pour GitHub Enterprise ultérieurement).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .retry import retry_call

logger = logging.getLogger(__name__)

_USER_AGENT = "agent-technical-doc/1.0"
_API_VERSION = "2022-11-28"


class GitHubError(RuntimeError):
    """Erreur d'appel à l'API GitHub, porteuse du code HTTP."""

    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status
        self.transient = status in (429, 500, 502, 503, 504)


@dataclass
class HttpResponse:
    status: int
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None


class GitHubClient:
    def __init__(self, token: str, *, api_base: str = "https://api.github.com",
                 max_retries: int = 3, sleep=None):
        self._token = token
        self.api_base = api_base.rstrip("/")
        # Retry (backoff) réservé aux lectures GET idempotentes — voir _api.
        self._max_retries = max(1, max_retries)
        self._sleep = sleep or time.sleep

    # --- transport bas niveau (remplaçable en test) --------------------------
    def _http(self, method: str, url: str, *, headers: dict, body: bytes | None) -> HttpResponse:
        req = urllib.request.Request(url=url, method=method, data=body)
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (URL contrôlée)
                return HttpResponse(resp.status, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise GitHubError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(503, str(exc.reason)) from exc

    def _headers(self, accept: str = "application/vnd.github+json") -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": _API_VERSION,
        }

    def _api(self, method: str, path: str, *, payload: dict | None = None,
             accept: str = "application/vnd.github+json") -> HttpResponse:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = self._headers(accept)
        if body is not None:
            headers["Content-Type"] = "application/json"

        call = lambda: self._http(method, url, headers=headers, body=body)  # noqa: E731
        # Retry (backoff) uniquement sur les lectures GET, idempotentes. Les
        # écritures (POST/PATCH : blob/tree/commit/ref/commentaire/réaction) ne
        # sont PAS rejouées pour éviter tout doublon ; en cas d'échec, le run
        # échoue et l'idempotence est relâchée (re-run manuel possible).
        if method != "GET":
            return call()
        return retry_call(
            call,
            is_transient=lambda e: isinstance(e, GitHubError) and e.transient,
            attempts=self._max_retries,
            sleep=self._sleep,
            logger=logger,
        )

    # --- opérations de lecture ----------------------------------------------
    def download_tarball(self, repo_full_name: str, ref: str) -> bytes:
        """Télécharge l'archive tar.gz du dépôt à une ref donnée (lecture seule)."""
        resp = self._api(
            "GET", f"/repos/{repo_full_name}/tarball/{ref}",
            accept="application/vnd.github+json",
        )
        return resp.body

    def get_pull_request(self, repo_full_name: str, pr_number: int) -> dict:
        return self._api("GET", f"/repos/{repo_full_name}/pulls/{pr_number}").json()

    # --- restitution ---------------------------------------------------------
    def post_issue_comment(self, repo_full_name: str, issue_number: int, body: str) -> dict:
        return self._api(
            "POST", f"/repos/{repo_full_name}/issues/{issue_number}/comments",
            payload={"body": body},
        ).json()

    def add_reaction(self, repo_full_name: str, comment_id: int, content: str = "eyes") -> dict:
        """Pose une réaction (accusé de réception, ex. 👀) sur un commentaire."""
        return self._api(
            "POST",
            f"/repos/{repo_full_name}/issues/comments/{comment_id}/reactions",
            payload={"content": content},
            accept="application/vnd.github+json",
        ).json()

    # --- Git Data API (commit atomique) — utilisé en Task 6 ------------------
    def get_ref(self, repo_full_name: str, ref: str) -> dict:
        return self._api("GET", f"/repos/{repo_full_name}/git/ref/{ref}").json()

    def get_commit(self, repo_full_name: str, sha: str) -> dict:
        return self._api("GET", f"/repos/{repo_full_name}/git/commits/{sha}").json()

    def create_blob(self, repo_full_name: str, content: str, encoding: str = "utf-8") -> dict:
        return self._api(
            "POST", f"/repos/{repo_full_name}/git/blobs",
            payload={"content": content, "encoding": encoding},
        ).json()

    def create_tree(self, repo_full_name: str, base_tree: str, tree: list[dict]) -> dict:
        return self._api(
            "POST", f"/repos/{repo_full_name}/git/trees",
            payload={"base_tree": base_tree, "tree": tree},
        ).json()

    def create_commit(self, repo_full_name: str, message: str, tree_sha: str,
                      parent_sha: str) -> dict:
        return self._api(
            "POST", f"/repos/{repo_full_name}/git/commits",
            payload={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        ).json()

    def update_ref(self, repo_full_name: str, ref: str, sha: str,
                   force: bool = False) -> dict:
        return self._api(
            "PATCH", f"/repos/{repo_full_name}/git/refs/{ref}",
            payload={"sha": sha, "force": force},
        ).json()
