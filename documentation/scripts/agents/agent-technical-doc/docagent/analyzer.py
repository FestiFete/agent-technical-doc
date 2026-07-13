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
              "nodes": [{"id": "u", "label": "Utilisateur", "kind": "person"},
                        {"id": "sys", "label": "Système", "kind": "system"}],
              "edges": [{"from": "u", "to": "sys", "label": "utilise"}]}},
    {"path": "diagrams/sequence-main-flows.drawio",
     "spec": {"type": "sequence", "title": "Flux principal",
              "nodes": [{"id": "user", "label": "Utilisateur", "kind": "actor"},
                        {"id": "app", "label": "Application", "kind": "container"},
                        {"id": "api", "label": "API externe", "kind": "system"}],
              "edges": [{"from": "user", "to": "app", "label": "1. action"},
                        {"from": "app", "to": "api", "label": "2. requête"},
                        {"from": "api", "to": "app", "label": "3. réponse"}]}},
    {"path": "diagrams/data-model-er.drawio",
     "spec": {"type": "er", "title": "Modèle de données",
              "nodes": [{"id": "user", "label": "User", "kind": "entity",
                         "attributes": ["id: int", "email: str"]},
                        {"id": "order", "label": "Order", "kind": "entity",
                         "attributes": ["id: int", "user_id: int"]}],
              "edges": [{"from": "order", "to": "user", "label": "appartient à"}]}}
  ]
}
Diagrammes attendus : c4-context, c4-container, c4-component, sequence-main-flows,
et data-model-er (ce dernier UNIQUEMENT si un modèle de données est détecté).

RÈGLE STRICTE — chaque objet de "diagrams" DOIT avoir un "spec.nodes" NON VIDE
(au moins un nœud) et un "spec.type" ∈ {c4, sequence, er} :
- séquence : les **participants** sont les nœuds (kind actor/container/system) et les
  **messages ordonnés** sont les edges (préfixe le label par "1.", "2.", …) ;
- ER : les **entités** sont les nœuds (kind "entity", avec "attributes") et les
  **relations** sont les edges.
Si tu ne peux pas fournir au moins un nœud pertinent pour un diagramme, alors
N'INCLUS PAS cet objet dans "diagrams" et indique-le dans "missing" (ne renvoie
jamais un diagramme avec des nœuds vides)."""


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


def select_model(
    repo_context: dict,
    *,
    primary: str | None = None,
    escalation: str | None = None,
    max_files: int | None = None,
    max_bytes: int | None = None,
) -> tuple[str, str]:
    """Choisit le modèle Bedrock selon la taille/complexité du contexte.

    Optimisation de coût : le modèle primaire (économique, Haiku) suffit pour la
    grande majorité des dépôts, l'output étant un JSON structuré cadré. On escalade
    vers le modèle puissant (Sonnet) uniquement quand le contexte sélectionné est
    volumineux (beaucoup de fichiers ou d'octets), là où une analyse plus fine est
    justifiée.

    Fonction pure (aucun effet de bord, aucune dépendance réseau) → testable.
    Retourne ``(model_id, raison)``. Un seuil à 0 désactive le critère associé.
    """
    primary = primary or config.MODEL_ID
    escalation = escalation or config.MODEL_ID_ESCALATION
    max_files = config.MODEL_ESCALATION_MAX_FILES if max_files is None else max_files
    max_bytes = config.MODEL_ESCALATION_MAX_BYTES if max_bytes is None else max_bytes

    files = repo_context.get("files") or {}
    n_files = len(files)
    total_bytes = sum(len(c) for c in files.values() if isinstance(c, str))

    if max_files and n_files > max_files:
        return escalation, f"escalade: {n_files} fichiers > seuil {max_files}"
    if max_bytes and total_bytes > max_bytes:
        return escalation, f"escalade: {total_bytes} octets > seuil {max_bytes}"
    return primary, f"primaire ({n_files} fichiers, {total_bytes} octets)"


class BedrockAnalyzer:
    """Analyseur par défaut basé sur Strands + Bedrock (imports différés)."""

    def __init__(self, *, model_id: str | None = None, escalation_model_id: str | None = None,
                 region: str | None = None):
        # model_id explicite → override : désactive la sélection automatique.
        self._model_override = model_id
        self.model_id = model_id or config.MODEL_ID
        self.escalation_model_id = escalation_model_id or config.MODEL_ID_ESCALATION
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
        if self._model_override:
            reason = "modèle imposé (override)"
        else:
            self.model_id, reason = select_model(
                repo_context,
                primary=config.MODEL_ID,
                escalation=self.escalation_model_id,
            )
        logger.info("Analyse avec le modèle %s — %s", self.model_id, reason)
        agent = self._build_agent()
        prompt = _render_context(repo_context)
        result = agent(prompt)
        if hasattr(result, "message") and isinstance(result.message, dict):
            text = result.message.get("content", [{}])[0].get("text", "")
        else:
            text = str(result)
        return _extract_json(text)
