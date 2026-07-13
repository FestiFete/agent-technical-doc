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

--- Invocation asynchrone (AgentCore) --------------------------------------------
Le run (clone → analyse → commit → commentaire) est long. L'entrypoint le lance
donc en **tâche de fond** (``add_async_task``/``complete_async_task``) et rend la
main **immédiatement** au worker (statut ``accepted``). La session reste vivante
via le statut ``/ping`` ``HealthyBusy`` géré par le SDK, jusqu'à ``complete_async_task``
(plafond : durée max de tâche asynchrone AgentCore). Bénéfices : le worker ne
bloque plus (coût quasi nul, pas de plafond 15 min synchrone, slot de concurrence
libéré en ~1 s). L'agent reste **responsable de la restitution** (commit +
commentaire terminal), et l'idempotence ``repo#pr#sha`` empêche tout doublon lors
d'un éventuel rejeu SQS.

⚠️ Le handler ``@app.entrypoint`` ne doit pas bloquer : le travail lourd tourne
dans un thread séparé pour ne pas bloquer le health check ``/ping``.
"""
from __future__ import annotations

import logging
import os
import threading
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
    """Point d'entrée AgentCore. Valide le payload puis lance le run en tâche de
    fond, et renvoie immédiatement un accusé (statut ``accepted``)."""
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

    def _run_background(task_id) -> None:
        """Exécute le run complet. run_documentation gère déjà son commentaire
        terminal et ses exceptions ; ce wrapper garantit la libération de la
        tâche asynchrone (retour du statut /ping à Healthy)."""
        try:
            run_documentation(request, session_id=session_id, logger=log)
        except Exception as exc:  # noqa: BLE001 — filet de sécurité
            log.error("Echec du run (tâche de fond): %s",
                      correlation.mask_secrets(str(exc)), exc_info=True)
        finally:
            try:
                app.complete_async_task(task_id)
            except Exception:  # noqa: BLE001 — ne jamais casser sur la fin de tâche
                log.debug("complete_async_task a échoué", exc_info=True)

    try:
        # add_async_task bascule /ping en HealthyBusy → la session survit au-delà
        # du timeout d'inactivité pendant tout le run.
        task_id = app.add_async_task("documentation_run")
        log.info(
            "Run documentation lancé en arrière-plan repo=%s pr=%s corr=%s",
            request.repo_full_name, request.pr_number, request.correlation_id,
        )
        threading.Thread(
            target=_run_background, args=(task_id,),
            name="documentation-run", daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 — échec au lancement uniquement
        log.error("Impossible de lancer le run: %s",
                  correlation.mask_secrets(str(exc)), exc_info=True)
        return status_response(
            status="failed",
            session_id=session_id,
            correlation_id=request.correlation_id,
            error=correlation.mask_secrets(str(exc)),
        )

    return status_response(
        status="accepted",
        session_id=session_id,
        correlation_id=request.correlation_id,
        message="Run de documentation démarré.",
    )


if __name__ == "__main__":
    app.run()
