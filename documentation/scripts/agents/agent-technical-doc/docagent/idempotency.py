"""Revendication d'idempotence forte côté agent (table DynamoDB partagée).

Clé ``repo#pr#sha`` : garantit qu'un même commit n'est documenté qu'une fois,
même en cas de rejeu SQS du worker ou d'invocations concurrentes. ``boto3`` est
importé de façon différée (module testable sans la dépendance).
"""
from __future__ import annotations

import logging
import os
import time

from . import config

logger = logging.getLogger(__name__)


def _table_name() -> str:
    return os.environ.get("IDEMPOTENCY_TABLE", "")


def claim(key: str, correlation_id: str, *, ttl_days: int = 30) -> bool:
    """PutItem conditionnel. Retourne True si la clé est revendiquée (à traiter),
    False si elle existe déjà (doublon). Fail-open si la table n'est pas
    configurée (POC : on préfère produire la doc plutôt que bloquer)."""
    table = _table_name()
    if not table:
        logger.warning("IDEMPOTENCY_TABLE non configurée — idempotence désactivée")
        return True

    import boto3
    from botocore.exceptions import ClientError

    ddb = boto3.client("dynamodb", region_name=config.BEDROCK_REGION)
    ttl = int(time.time()) + ttl_days * 86400
    try:
        ddb.put_item(
            TableName=table,
            Item={
                "pk": {"S": key},
                "status": {"S": "in_progress"},
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


def release(key: str) -> None:
    """Supprime la revendication d'idempotence (best-effort, ne lève jamais).

    Appelée sur **échec** d'un run : sans cela, la clé ``in_progress`` resterait
    posée jusqu'au TTL (30 j) et bloquerait tout nouveau run sur le même commit
    (``skipped_duplicate``). La supprimer permet à une nouvelle ``@mention`` sur le
    même ``sha`` de relancer la génération. Le succès, lui, **conserve** la clé
    (la déduplication reste active)."""
    table = _table_name()
    if not table:
        return
    try:
        import boto3
        boto3.client("dynamodb", region_name=config.BEDROCK_REGION).delete_item(
            TableName=table,
            Key={"pk": {"S": key}},
        )
        logger.info("Revendication d'idempotence relâchée après échec (%s)", key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("release idempotency échec (%s): %s", key, exc)
