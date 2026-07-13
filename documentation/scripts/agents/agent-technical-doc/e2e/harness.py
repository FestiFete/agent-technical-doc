#!/usr/bin/env python3
"""Phase 3 — Outils du harnais E2E : événement webhook synthétique signé.

Déclenche la chaîne AWS **déployée** (API Gateway → webhook → SQS → worker →
runtime) sans dépendre de la livraison webhook de GitHub : on construit un
événement ``issue_comment`` conforme, on le **signe en HMAC-SHA256** (même schéma
que la Lambda webhook) et on le ``POST`` sur l'API Gateway.

Les constructeurs (payload + signature) sont **purs** et testables hors ligne ;
``post_webhook`` est le seul point d'I/O réseau.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid


def build_issue_comment_event(
    *,
    repo_full_name: str,
    pr_number: int,
    comment_id: int,
    body: str,
    author_association: str = "MEMBER",
) -> dict:
    """Construit un payload ``issue_comment`` (action ``created``) sur une PR.

    Structure alignée sur ce qu'attend ``webhook.evaluate_comment`` : présence de
    ``issue.pull_request``, ``comment.body`` (avec la mention), ``repository.full_name``.
    """
    return {
        "action": "created",
        "issue": {
            "number": pr_number,
            "pull_request": {
                "url": f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
            },
        },
        "comment": {
            "id": comment_id,
            "body": body,
            "author_association": author_association,
        },
        "repository": {"full_name": repo_full_name},
    }


def sign_payload(secret: str, body: bytes) -> str:
    """Signature GitHub ``X-Hub-Signature-256`` (HMAC-SHA256 hex préfixé)."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_webhook(
    api_url: str,
    *,
    secret: str,
    event: dict,
    delivery_id: str | None = None,
    event_type: str = "issue_comment",
    timeout: int = 30,
) -> tuple[int, str, str]:
    """POST l'événement signé sur l'API Gateway. Retourne ``(status, body, delivery_id)``."""
    body = json.dumps(event).encode("utf-8")
    delivery_id = delivery_id or uuid.uuid4().hex
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": event_type,
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": sign_payload(secret, body),
        "User-Agent": "agent-technical-doc-e2e/1.0",
    }
    req = urllib.request.Request(api_url, method="POST", data=body)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status, resp.read().decode("utf-8", "replace"), delivery_id
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), delivery_id
