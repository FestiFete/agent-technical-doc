"""Récupération du token GitHub depuis AWS Secrets Manager.

``boto3`` est importé de façon différée pour garder le module testable sans la
dépendance. Le secret peut être stocké soit en chaîne brute (le token), soit en
JSON ``{"token": "..."}`` (clé configurable).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_CACHE: dict[str, str] = {}


def _secrets_client(region: str):
    import boto3  # import différé

    return boto3.client("secretsmanager", region_name=region)


def get_github_token(secret_arn: str, *, region: str, token_key: str = "token") -> str:
    """Retourne le token GitHub depuis Secrets Manager (avec cache mémoire).

    Ne journalise jamais la valeur du secret.
    """
    if not secret_arn:
        raise ValueError("GITHUB_TOKEN_SECRET_ARN non configuré")
    if secret_arn in _CACHE:
        return _CACHE[secret_arn]

    resp = _secrets_client(region).get_secret_value(SecretId=secret_arn)
    raw = resp.get("SecretString") or ""
    token = _extract_token(raw, token_key)
    if not token:
        raise ValueError("Secret GitHub vide ou format inattendu")
    _CACHE[secret_arn] = token
    logger.info("Token GitHub récupéré depuis Secrets Manager (longueur=%d)", len(token))
    return token


def _extract_token(raw: str, token_key: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    # JSON {"token": "..."} ou {"<token_key>": "..."} ?
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for key in (token_key, "token", "github_token", "value"):
                    if data.get(key):
                        return str(data[key]).strip()
        except (ValueError, TypeError):
            pass
    return raw


def _reset_cache_for_tests() -> None:
    _CACHE.clear()
