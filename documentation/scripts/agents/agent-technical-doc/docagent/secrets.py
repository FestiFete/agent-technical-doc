"""Récupération du secret d'authentification GitHub depuis AWS Secrets Manager.

``boto3`` est importé de façon différée pour garder le module testable sans la
dépendance. Le secret peut contenir une **GitHub App**
(``{"app_id", "private_key", "installation_id"?}``), un **PAT** en JSON
(``{"token": "..."}``) ou un PAT en chaîne brute. L'interprétation (App vs PAT)
est faite par :mod:`github_auth`.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_DICT_CACHE: dict[str, dict] = {}


def _secrets_client(region: str):
    import boto3  # import différé

    return boto3.client("secretsmanager", region_name=region)


def _parse_secret_string(raw: str) -> dict:
    """Normalise le contenu brut du secret en dict (fonction pure, testable).

    - JSON objet → tel quel (App ou ``{"token": ...}``) ;
    - JSON non-objet ou chaîne brute → ``{"token": "<brut>"}`` (PAT) ;
    - vide → ``ValueError``.
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Secret GitHub vide")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"token": raw}  # PAT en chaîne brute
    if isinstance(data, dict):
        return data
    return {"token": str(data)}


def get_secret_dict(secret_arn: str, *, region: str) -> dict:
    """Retourne le contenu du secret GitHub sous forme de dict (avec cache).

    Ne journalise jamais la valeur (seulement les noms de clés). Utilisé par
    :mod:`github_auth`.
    """
    if not secret_arn:
        raise ValueError("GITHUB_TOKEN_SECRET_ARN non configuré")
    if secret_arn in _DICT_CACHE:
        return _DICT_CACHE[secret_arn]

    resp = _secrets_client(region).get_secret_value(SecretId=secret_arn)
    data = _parse_secret_string(resp.get("SecretString") or "")
    _DICT_CACHE[secret_arn] = data
    logger.info("Secret GitHub chargé depuis Secrets Manager (clés=%s)",
                sorted(data.keys()))
    return data


def _reset_cache_for_tests() -> None:
    _DICT_CACHE.clear()
