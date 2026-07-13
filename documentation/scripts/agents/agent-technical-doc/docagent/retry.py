"""Retry avec backoff exponentiel sur erreurs **transitoires** (résilience du run).

En invocation asynchrone, le worker rend la main immédiatement : le retry SQS ne
couvre plus le run lui-même. On rejoue donc en interne les opérations
**idempotentes** sujettes à des erreurs passagères (throttling Bedrock, 5xx
GitHub) avant de déclarer l'échec (qui relâche l'idempotence pour autoriser un
re-run manuel).

Fonctions pures : ``sleep`` est injectable → testable sans temporisation réelle.
"""
from __future__ import annotations

import time
from typing import Callable

# Noms d'exceptions considérés comme transitoires (Bedrock / botocore / réseau).
_TRANSIENT_NAMES = frozenset({
    "ThrottlingException",
    "ThrottlingError",
    "TooManyRequestsException",
    "ServiceQuotaExceededException",
    "InternalServerException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "ModelNotReadyException",
    "RequestLimitExceeded",
    "ConnectionError",
    "ReadTimeoutError",
    "ConnectTimeoutError",
})


def is_transient_error(exc: BaseException) -> bool:
    """Vrai si l'exception traduit une condition passagère (rejouable).

    Détection sans import (évite les cycles) :
      - attribut ``transient`` vrai (ex. :class:`github_client.GitHubError`) ;
      - nom de classe dans la liste des erreurs transitoires connues ;
      - ``ClientError`` botocore dont le code d'erreur est transitoire.
    """
    if getattr(exc, "transient", False):
        return True
    if type(exc).__name__ in _TRANSIENT_NAMES:
        return True
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = (resp.get("Error") or {}).get("Code", "")
        if code in _TRANSIENT_NAMES:
            return True
    return False


def retry_call(
    fn: Callable[[], object],
    *,
    is_transient: Callable[[BaseException], bool] = is_transient_error,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
    logger=None,
):
    """Exécute ``fn`` en la rejouant sur erreur transitoire (backoff exponentiel).

    Relance immédiatement l'exception si elle n'est pas transitoire, ou après la
    dernière tentative. ``attempts`` = nombre total d'essais (>= 1).
    """
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — on décide via is_transient
            if attempt >= attempts or not is_transient(exc):
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if logger is not None:
                logger.warning(
                    "Erreur transitoire (%s), tentative %d/%d — nouvel essai dans %.1fs",
                    type(exc).__name__, attempt, attempts, delay,
                )
            sleep(delay)
