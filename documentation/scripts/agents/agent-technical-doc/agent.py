"""agent-technical-doc — Agent de documentation technique (AWS Bedrock AgentCore).

Déclenché (via la chaîne d'ingestion webhook → SQS → worker → InvokeAgentRuntime)
par un ``@mention`` dans un commentaire de Pull Request GitHub. Il :

  1. récupère le token GitHub depuis Secrets Manager ;
  2. clone la ref head de la PR en **lecture seule** (shallow, jamais d'exécution
     du code du dépôt) ;
  3. sélectionne et lit un ensemble **borné** de fichiers (manifestes, README,
     points d'entrée, dossiers clés) ;
  4. analyse (LLM) la finalité, la stack, les patterns et l'architecture ;
  5. génère la documentation Markdown + les schémas ``.drawio`` (C4 + Séquence +
     ER si détecté) sous ``docs/agent/`` ;
  6. commite l'ensemble en **un seul commit** sur la branche head de la PR ;
  7. poste un **commentaire terminal** (succès ou échec).

Runtime : PUBLIC, auth IAM (invoqué par la Lambda worker). **Sans état** : ni
AgentCore Memory, ni Knowledge Base.

--- Note de spike (invocation AgentCore) ----------------------------------------
``InvokeAgentRuntime`` est une API requête/réponse supportant le streaming. La
Lambda worker maintient la connexion streaming pendant toute la durée du run
(read_timeout élevé, aligné sur ``max_lifetime_in_seconds`` du runtime). L'agent
est **responsable de la restitution** (commit + commentaire) : même si la
connexion worker expire, l'agent poste toujours un commentaire terminal, et
l'idempotence ``repo#pr#sha`` empêche tout doublon lors d'un éventuel rejeu SQS.
À confirmer sur la doc AWS : disponibilité d'un mode asynchrone natif qui
permettrait un worker « fire-and-forget » (voir specs/design.md §7).
"""
from __future__ import annotations

import logging
import os
import uuid

from bedrock_agentcore import BedrockAgentCoreApp

from docagent import correlation
from docagent.orchestrator import run_documentation
from docagent.payload import PayloadError, parse_request, status_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("agent-technical-doc")

app = BedrockAgentCoreApp(debug=True)


@app.entrypoint
def invoke(payload, context):
    """Point d'entrée AgentCore. Renvoie toujours une réponse de statut structurée."""
    session_id = (
        getattr(context, "session_id", None)
        or (payload or {}).get("sessionId")
        or uuid.uuid4().hex[:12]
    )
    try:
        request = parse_request(payload, context)
    except PayloadError as exc:
        logger.error("Payload invalide: %s", correlation.mask_secrets(str(exc)))
        return status_response(
            status="invalid_request",
            session_id=session_id,
            correlation_id=(payload or {}).get("correlation_id", ""),
            error=str(exc),
        )

    log = logging.LoggerAdapter(logger, {"correlation_id": request.correlation_id})
    log.info(
        "Run documentation repo=%s pr=%s sha=%s corr=%s",
        request.repo_full_name, request.pr_number, request.head_sha[:12],
        request.correlation_id,
    )

    try:
        return run_documentation(request, session_id=session_id, logger=log)
    except Exception as exc:  # noqa: BLE001 — on garantit une réponse terminale
        log.error("Echec du run: %s", correlation.mask_secrets(str(exc)), exc_info=True)
        return status_response(
            status="failed",
            session_id=session_id,
            correlation_id=request.correlation_id,
            error=correlation.mask_secrets(str(exc)),
        )


if __name__ == "__main__":
    app.run()
