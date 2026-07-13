"""Authentification GitHub — GitHub App (préféré) ou PAT (repli).

Une **GitHub App** est préférée à un PAT : permissions fines par installation,
token à durée de vie courte (~1 h), révocable, blast radius réduit, non lié à un
utilisateur. Flux d'obtention du token d'installation :

  1. Construire un **JWT RS256** signé par la clé privée de l'App
     (``iss = app_id``, ``exp`` < 10 min).
  2. Résoudre l'``installation_id`` pour le dépôt (ou le lire depuis le secret).
  3. Échanger le JWT contre un **token d'installation**
     (``POST /app/installations/{id}/access_tokens``).

Le secret Secrets Manager contient soit :
  - GitHub App : ``{"app_id", "private_key", "installation_id"?}`` ;
  - PAT (repli) : ``{"token": "ghp_..."}``.

``PyJWT``/``cryptography`` et ``urllib`` sont utilisés de façon différée et
**injectable** (paramètres ``http`` / ``jwt_builder``) pour rester testable sans
crypto ni réseau. Le token d'installation étant court, il n'est pas mis en cache
ici : il est réémis à chaque run (2 appels API bon marché).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_USER_AGENT = "agent-technical-doc/1.0"
_API_VERSION = "2022-11-28"
_JWT_TTL_SECONDS = 540  # < 10 min (plafond GitHub pour un JWT d'App)


class GitHubAuthError(RuntimeError):
    """Échec d'authentification GitHub (App mal configurée ou secret invalide)."""


def _default_http(method: str, url: str, *, headers: dict, body: bytes | None = None) -> dict:
    """Transport HTTP par défaut (urllib), remplaçable en test."""
    req = urllib.request.Request(url=url, method=method, data=body)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (URL contrôlée)
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GitHubAuthError(f"GitHub API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubAuthError(f"GitHub injoignable: {exc.reason}") from exc
    return json.loads(raw.decode("utf-8")) if raw else {}


def _build_app_jwt(app_id: str, private_key_pem: str, *, now: float | None = None) -> str:
    """Construit un JWT RS256 signé par la clé privée de l'App (PyJWT différé)."""
    import jwt  # PyJWT (import différé — nécessite cryptography pour RS256)

    issued = int(now if now is not None else time.time())
    payload = {"iat": issued - 60, "exp": issued + _JWT_TTL_SECONDS, "iss": str(app_id)}
    token = jwt.encode(payload, private_key_pem, algorithm="RS256")
    # PyJWT >= 2 renvoie str ; les versions < 2 renvoyaient des bytes.
    return token.decode("utf-8") if isinstance(token, (bytes, bytearray)) else token


def _auth_headers(bearer: str, *, json_body: bool = False) -> dict:
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": _API_VERSION,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _extract_pat(secret: dict) -> str:
    for key in ("token", "github_token", "value"):
        if secret.get(key):
            return str(secret[key]).strip()
    return ""


def resolve_token(
    secret: dict,
    repo_full_name: str,
    *,
    api_base: str = "https://api.github.com",
    http=None,
    jwt_builder=None,
    now: float | None = None,
) -> str:
    """Retourne un token GitHub utilisable en en-tête ``Authorization: Bearer``.

    Priorité à la **GitHub App** si ``app_id`` + ``private_key`` sont présents ;
    sinon repli sur le **PAT** (``token``). ``http`` et ``jwt_builder`` sont
    injectables pour les tests. Lève :class:`GitHubAuthError` si le secret est
    incomplet ou si l'App n'est pas installée sur le dépôt.
    """
    if not isinstance(secret, dict):
        raise GitHubAuthError("Secret GitHub illisible (format inattendu)")

    app_id = secret.get("app_id")
    private_key = secret.get("private_key")

    # Repli PAT si aucune App n'est configurée.
    if not (app_id and private_key):
        pat = _extract_pat(secret)
        if pat:
            logger.info("Auth GitHub : PAT (repli)")
            return pat
        raise GitHubAuthError(
            "Secret GitHub incomplet : fournir {app_id, private_key} (App) "
            "ou {token} (PAT)"
        )

    http = http or _default_http
    jwt_builder = jwt_builder or _build_app_jwt
    api_base = api_base.rstrip("/")

    app_jwt = jwt_builder(app_id, private_key, now=now)

    # Installation : lue depuis le secret si fournie, sinon résolue par dépôt.
    installation_id = secret.get("installation_id")
    if not installation_id:
        installation = http(
            "GET",
            f"{api_base}/repos/{repo_full_name}/installation",
            headers=_auth_headers(app_jwt),
        )
        installation_id = (installation or {}).get("id")
        if not installation_id:
            raise GitHubAuthError(
                f"Aucune installation de la GitHub App pour {repo_full_name}"
            )

    # Échange JWT → token d'installation (court, ~1 h).
    result = http(
        "POST",
        f"{api_base}/app/installations/{installation_id}/access_tokens",
        headers=_auth_headers(app_jwt, json_body=True),
        body=b"{}",
    )
    token = (result or {}).get("token")
    if not token:
        raise GitHubAuthError("Réponse sans 'token' à l'échange JWT → installation")
    logger.info("Auth GitHub : token d'installation App (installation=%s)", installation_id)
    return token
