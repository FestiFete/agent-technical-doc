"""Lambda worker-dispatcher — consomme SQS et invoque le runtime AgentCore.

Chaque message SQS (produit par la Lambda webhook) contient le minimum :
``{repo_full_name, pr_number, comment_id, correlation_id}``. Le worker appelle
``InvokeAgentRuntime`` (runtime scopé par ARN dans l'IAM) en propageant le
``correlation_id`` comme ``runtimeSessionId`` (traçabilité de bout en bout).

Classification des erreurs :
- transitoire (throttling, 5xx) → l'exception remonte : SQS réessaie puis DLQ.
- permanente (payload invalide) → message consommé sans rejeu (log + drop) pour
  éviter une boucle de rejeu inutile.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "")
REGION = os.environ.get("AWS_REGION", "eu-central-1")

_TRANSIENT_ERRORS = (
    "ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException",
    "InternalServerException", "ServiceUnavailableException", "ModelTimeoutException",
)


class PermanentError(Exception):
    """Erreur non rejouable (le message est consommé sans retry)."""


def _agentcore_client():
    import boto3
    return boto3.client("bedrock-agentcore", region_name=REGION)


def _session_id(correlation_id: str, fallback: str) -> str:
    # AgentCore impose un sessionId >= 33 caractères : on complète si besoin.
    sid = (correlation_id or fallback).replace("-", "")
    return (sid + "0" * 33)[:64] if len(sid) < 33 else sid[:64]


def _invoke_runtime(message: dict) -> None:
    if not RUNTIME_ARN:
        raise PermanentError("RUNTIME_ARN non configuré")
    if not message.get("repo_full_name") or not message.get("pr_number"):
        raise PermanentError(f"message invalide: {message}")

    from botocore.exceptions import ClientError

    correlation_id = message.get("correlation_id", "")
    payload = {
        "repo_full_name": message["repo_full_name"],
        "pr_number": message["pr_number"],
        "comment_id": message.get("comment_id"),
        "correlation_id": correlation_id,
    }
    try:
        _agentcore_client().invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            runtimeSessionId=_session_id(correlation_id, str(message["pr_number"])),
            payload=json.dumps(payload).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        logger.info("Runtime invoqué (repo=%s pr=%s corr=%s)",
                    message["repo_full_name"], message["pr_number"], correlation_id)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _TRANSIENT_ERRORS:
            logger.warning("Erreur transitoire (%s) — rejeu SQS", code)
            raise  # remonte → retry SQS puis DLQ
        logger.error("Erreur permanente (%s) — pas de rejeu", code)
        raise PermanentError(str(exc)) from exc


def lambda_handler(event, context):
    """Traite un batch de messages SQS. Les erreurs permanentes sont absorbées."""
    processed, failed = 0, 0
    for record in event.get("Records", []):
        try:
            message = json.loads(record.get("body", "{}"))
        except ValueError:
            logger.error("Corps SQS non JSON — ignoré")
            continue
        try:
            _invoke_runtime(message)
            processed += 1
        except PermanentError as exc:
            logger.error("Message abandonné (permanent): %s", exc)
            # consommé sans rejeu (pas de re-raise)
        # les erreurs transitoires remontent et échouent le batch (retry SQS)
    return {"processed": processed, "failed": failed}
