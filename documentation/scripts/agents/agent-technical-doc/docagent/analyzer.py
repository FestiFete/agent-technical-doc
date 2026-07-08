"""Analyseur LLM (Bedrock via Strands).

L'analyseur reçoit un **contexte de dépôt** (arborescence sélectionnée + contenus
bornés + indices neutres) et renvoie une **analyse structurée** (dict JSON). Il
n'a AUCUN pouvoir d'écriture : le rendu, la validation des schémas, le commit et
le commentaire sont effectués par du code déterministe (garde-fous en dur). C'est
un choix de sécurité — le LLM ne peut pas être manipulé pour écrire hors
périmètre puisqu'il ne fait que produire du texte d'analyse.

``boto3``/``strands`` sont importés de façon différée : le module reste importable
sans ces dépendances (les tests injectent un analyseur factice).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

# Schéma de sortie attendu, injecté dans le prompt pour cadrer la réponse.
OUTPUT_CONTRACT = """
Réponds UNIQUEMENT par un objet JSON valide (sans texte autour), au format :
{
  "name": "nom du projet",
  "purpose": "finalité",
  "audience": "publics visés",
  "architecture_style": "monolithe|microservices|serverless|...",
  "stack": [{"name": "Node.js", "kind": "runtime|framework|db|tool", "role": "..."}],
  "components": [{"name": "API", "responsibility": "..."}],
  "data_flows": "description des flux",
  "external_deps": ["service externe 1", "..."],
  "use_cases": ["cas d'usage 1", "..."],
  "notes": "limites / points non déterminés",
  "summary": "2-4 phrases de synthèse pour le commentaire de PR",
  "missing": "informations non déterminables depuis le dépôt",
  "diagrams": [
    {"path": "diagrams/c4-context.drawio",
     "spec": {"type": "c4", "title": "Contexte",
              "nodes": [{"id": "u", "label": "Utilisateur", "kind": "person"}],
              "edges": [{"from": "u", "to": "sys", "label": "utilise"}]}}
  ]
}
Produis c4-context, c4-container, c4-component, sequence-main-flows, et
data-model-er UNIQUEMENT si un modèle de données est détecté.
"""


def _load_system_prompt() -> str:
    default_path = Path(__file__).resolve().parent.parent / "instructions.md"
    prompt_path = Path(os.environ.get("SYSTEM_PROMPT_PATH", str(default_path)))
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError:
        return "Tu es agent-technical-doc. Analyse le dépôt et renvoie un JSON structuré."


def _render_context(repo_context: dict) -> str:
    """Sérialise le contexte de dépôt pour le prompt (borné en amont)."""
    parts = [
        f"# Dépôt : {repo_context.get('repo_full_name')}",
        f"# Branche : {repo_context.get('head_ref')}",
        f"# Indices de stack (neutres) : {json.dumps(repo_context.get('stack_hints', {}), ensure_ascii=False)}",
        f"# Modèle de données probable : {repo_context.get('data_model_likely')}",
        "",
        "## Arborescence sélectionnée",
        "\n".join(f"- {p}" for p in repo_context.get("tree", [])),
        "",
        "## Contenus (bornés)",
    ]
    for path, content in (repo_context.get("files") or {}).items():
        parts.append(f"\n### {path}\n```\n{content}\n```")
    return "\n".join(parts)


def _extract_json(text: str) -> dict:
    """Extrait le premier objet JSON d'une réponse LLM (robuste aux fences)."""
    text = text.strip()
    if "```" in text:
        # retire un éventuel bloc ```json ... ```
        segments = text.split("```")
        for seg in segments:
            seg = seg.strip()
            if seg.startswith("json"):
                seg = seg[len("json"):].strip()
            if seg.startswith("{"):
                text = seg
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Aucun JSON trouvé dans la réponse du modèle")
    return json.loads(text[start:end + 1])


class BedrockAnalyzer:
    """Analyseur par défaut basé sur Strands + Bedrock (imports différés)."""

    def __init__(self, *, model_id: str | None = None, region: str | None = None):
        self.model_id = model_id or config.MODEL_ID
        self.region = region or config.BEDROCK_REGION

    def _build_agent(self):
        from botocore.config import Config as BotocoreConfig
        from strands import Agent
        from strands.models import BedrockModel

        os.environ.setdefault("AWS_DEFAULT_REGION", self.region)
        boto_config = BotocoreConfig(
            read_timeout=int(os.environ.get("BEDROCK_READ_TIMEOUT", "900")),
            connect_timeout=int(os.environ.get("BEDROCK_CONNECT_TIMEOUT", "60")),
            retries={"max_attempts": int(os.environ.get("BEDROCK_MAX_RETRIES", "2")),
                     "mode": "adaptive"},
        )
        model = BedrockModel(model_id=self.model_id, streaming=True,
                             temperature=0.2, boto_client_config=boto_config)
        return Agent(model=model, system_prompt=_load_system_prompt() + "\n" + OUTPUT_CONTRACT)

    def analyze(self, repo_context: dict) -> dict:
        agent = self._build_agent()
        prompt = _render_context(repo_context)
        result = agent(prompt)
        if hasattr(result, "message") and isinstance(result.message, dict):
            text = result.message.get("content", [{}])[0].get("text", "")
        else:
            text = str(result)
        return _extract_json(text)
