"""Lambda webhook-receiver — porte d'entrée sécurisée des webhooks GitHub.

Responsabilités (aucune ne nécessite le token GitHub — moindre privilège) :
  1. Valider la signature HMAC ``X-Hub-Signature-256`` (rejet si absente/invalide).
  2. Filtrer : événement ``issue_comment`` créé, sur une PR, contenant le
     ``@mention`` de l'agent.
  3. Autoriser : dépôt dans l'allowlist ET ``author_association`` autorisée.
  4. Dédupliquer (PutItem conditionnel DynamoDB sur ``repo#pr#comment_id``).
  5. Limiter le débit par dépôt (garde-fou anti-DoS : quota par fenêtre glissante).
  6. Enfiler un message SQS ``{repo_full_name, pr_number, comment_id, correlation_id}``.

Les détails de la PR (head sha/ref, statut fork) sont résolus plus tard par
l'agent (qui détient le token). Les fonctions ``verify_signature`` et
``evaluate_comment`` sont pures (testables sans réseau).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_SECRET_CACHE: dict[str, str] = {}


# --- Configuration -----------------------------------------------------------
def _env_list(name: str, default: str = "") -> list[str]:
    return [p.strip() for p in os.environ.get(name, default).split(",") if p.strip()]


@dataclass
class Config:
    hmac_secret_arn: str = field(default_factory=lambda: os.environ.get("WEBHOOK_HMAC_SECRET_ARN", ""))
    mention_handle: str = field(default_factory=lambda: os.environ.get("MENTION_HANDLE", "@agent-technical-doc"))
    allowed_repos: list[str] = field(default_factory=lambda: _env_list("ALLOWED_REPOSITORIES"))
    allowed_assocs: list[str] = field(
        default_factory=lambda: _env_list("ALLOWED_AUTHOR_ASSOCIATIONS", "OWNER,MEMBER,COLLABORATOR"))
    queue_url: str = field(default_factory=lambda: os.environ.get("QUEUE_URL", ""))
    idempotency_table: str = field(default_factory=lambda: os.environ.get("IDEMPOTENCY_TABLE", ""))
    ttl_days: int = field(default_factory=lambda: int(os.environ.get("IDEMPOTENCY_TTL_DAYS", "30")))
    # Garde-fou anti-DoS : nb max de runs déclenchés par dépôt et par fenêtre.
    # 0 désactive la limite.
    max_runs_per_repo: int = field(default_factory=lambda: int(os.environ.get("MAX_RUNS_PER_REPO", "20")))
    rate_window_seconds: int = field(default_factory=lambda: int(os.environ.get("RATE_WINDOW_SECONDS", "3600")))
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "eu-central-1"))


# --- Fonctions pures ---------------------------------------------------------
def verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Vérifie la signature HMAC-SHA256 GitHub en temps constant."""
    if not signature_header or not secret:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@dataclass
class Decision:
    process: bool
    reason: str
    repo_full_name: str = ""
    pr_number: int = 0
    comment_id: int = 0
    author_association: str = ""


def evaluate_comment(payload: dict, cfg: Config, *, event_type: str, action: str) -> Decision:
    """Décide si l'événement doit déclencher l'agent (contrôles bon marché).

    Ne lit jamais le token GitHub. Retourne une :class:`Decision`.
    """
    if event_type != "issue_comment":
        return Decision(False, f"événement ignoré: {event_type}")
    if action != "created":
        return Decision(False, f"action ignorée: {action}")

    issue = payload.get("issue") or {}
    if "pull_request" not in issue:
        return Decision(False, "commentaire hors Pull Request")

    comment = payload.get("comment") or {}
    body = str(comment.get("body", ""))
    if cfg.mention_handle.lower() not in body.lower():
        return Decision(False, "mention absente")

    repo_full_name = str((payload.get("repository") or {}).get("full_name", ""))
    if cfg.allowed_repos and repo_full_name not in cfg.allowed_repos:
        return Decision(False, f"dépôt non autorisé: {repo_full_name}")
    if not cfg.allowed_repos:
        return Decision(False, "allowlist de dépôts vide (fail-safe)")

    assoc = str(comment.get("author_association", "")).upper()
    if assoc not in [a.upper() for a in cfg.allowed_assocs]:
        return Decision(False, f"auteur non autorisé: {assoc}")

    return Decision(
        True, "ok",
        repo_full_name=repo_full_name,
        pr_number=int(issue.get("number", 0)),
        comment_id=int(comment.get("id", 0)),
        author_association=assoc,
    )


def parse_api_event(event: dict) -> tuple[bytes, dict]:
    """Extrait le corps brut (bytes) et les en-têtes (minuscules) d'un event API GW."""
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(body)
    else:
        raw = body.encode("utf-8")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    return raw, headers


def _response(status: int, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"message": message})}


# --- Accès AWS (boto3 différé) ----------------------------------------------
def _get_secret(arn: str, region: str) -> str:
    if arn in _SECRET_CACHE:
        return _SECRET_CACHE[arn]
    import boto3
    val = boto3.client("secretsmanager", region_name=region).get_secret_value(SecretId=arn)
    secret = (val.get("SecretString") or "").strip()
    _SECRET_CACHE[arn] = secret
    return secret


def _claim_idempotency(table: str, key: str, correlation_id: str, ttl_days: int, region: str) -> bool:
    """PutItem conditionnel. Retourne False si la clé existe déjà (doublon)."""
    import boto3
    from botocore.exceptions import ClientError

    ddb = boto3.client("dynamodb", region_name=region)
    ttl = int(time.time()) + ttl_days * 86400
    try:
        ddb.put_item(
            TableName=table,
            Item={
                "pk": {"S": key},
                "status": {"S": "queued"},
                "correlation_id": {"S": correlation_id},
                "created_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "ttl": {"N": str(ttl)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _enqueue(queue_url: str, message: dict, region: str) -> None:
    import boto3
    boto3.client("sqs", region_name=region).send_message(
        QueueUrl=queue_url, MessageBody=json.dumps(message)
    )


# --- Garde-fou anti-DoS : quota de runs par dépôt et par fenêtre glissante ---
def _window_bucket(now: float, window_seconds: int) -> int:
    """Numéro de fenêtre temporelle (fonction pure)."""
    return int(now) // window_seconds


def _rate_key(repo_full_name: str, bucket: int) -> str:
    """Clé de compteur DynamoDB (namespace distinct des clés d'idempotence)."""
    return f"ratelimit#{repo_full_name}#{bucket}"


def _increment_repo_counter(table: str, key: str, ttl: int, region: str) -> int:
    """Incrémente atomiquement le compteur et retourne sa nouvelle valeur."""
    import boto3
    ddb = boto3.client("dynamodb", region_name=region)
    resp = ddb.update_item(
        TableName=table,
        Key={"pk": {"S": key}},
        UpdateExpression="SET #t = if_not_exists(#t, :ttl) ADD #c :one",
        ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
        ExpressionAttributeValues={":one": {"N": "1"}, ":ttl": {"N": str(ttl)}},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["count"]["N"])


def _rate_limited(table: str, repo_full_name: str, max_runs: int,
                  window_seconds: int, region: str, *, now: float | None = None) -> bool:
    """True si le quota de runs du dépôt est dépassé (à rejeter).

    Compteur atomique par dépôt et par fenêtre, purgé par TTL. Désactivé si
    ``max_runs <= 0``. Appelé après la déduplication : seules les demandes
    réellement nouvelles consomment du quota.
    """
    if not max_runs or max_runs <= 0:
        return False
    now = time.time() if now is None else now
    bucket = _window_bucket(now, window_seconds)
    ttl = (bucket + 1) * window_seconds + 60
    count = _increment_repo_counter(table, _rate_key(repo_full_name, bucket), ttl, region)
    return count > max_runs


# --- Handler -----------------------------------------------------------------
def lambda_handler(event, context):
    cfg = Config()
    raw, headers = parse_api_event(event)
    correlation_id = headers.get("x-github-delivery", "")

    # 1. Signature HMAC (obligatoire).
    secret = _get_secret(cfg.hmac_secret_arn, cfg.region)
    if not verify_signature(raw, headers.get("x-hub-signature-256", ""), secret):
        logger.warning("Signature webhook invalide (delivery=%s)", correlation_id)
        return _response(401, "signature invalide")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _response(400, "payload JSON invalide")

    # 2/3. Filtrage + autorisation.
    decision = evaluate_comment(
        payload, cfg,
        event_type=headers.get("x-github-event", ""),
        action=str(payload.get("action", "")),
    )
    if not decision.process:
        logger.info("Ignoré (%s) delivery=%s", decision.reason, correlation_id)
        return _response(204, f"ignoré: {decision.reason}")

    # 4. Idempotence (repo#pr#comment_id) — dédup des re-livraisons.
    key = f"{decision.repo_full_name}#{decision.pr_number}#{decision.comment_id}"
    if not _claim_idempotency(cfg.idempotency_table, key, correlation_id, cfg.ttl_days, cfg.region):
        logger.info("Doublon ignoré: %s", key)
        return _response(200, "doublon ignoré")

    # 4b. Garde-fou anti-DoS : quota de runs par dépôt et par fenêtre.
    if _rate_limited(cfg.idempotency_table, decision.repo_full_name,
                     cfg.max_runs_per_repo, cfg.rate_window_seconds, cfg.region):
        logger.warning("Quota de runs dépassé pour %s (max=%d / %ds) delivery=%s",
                       decision.repo_full_name, cfg.max_runs_per_repo,
                       cfg.rate_window_seconds, correlation_id)
        return _response(429, "quota de runs dépassé pour ce dépôt")

    # 5. Enqueue.
    _enqueue(cfg.queue_url, {
        "repo_full_name": decision.repo_full_name,
        "pr_number": decision.pr_number,
        "comment_id": decision.comment_id,
        "correlation_id": correlation_id,
    }, cfg.region)
    logger.info("Enfilé: %s (delivery=%s)", key, correlation_id)
    return _response(202, "accepté")
