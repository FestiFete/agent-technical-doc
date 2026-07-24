# Architecture — Audit

**Score:** 93/100  **Maturity:** 5 (Optimized)  **Coverage:** 95%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Ce pilier évalue la **conception logique** du système : adéquation du style
architectural au problème, frontières et responsabilités des composants,
explicitation des flux de données et de leur propriété, patterns d'intégration
(sync/async, file/API), stratégie de cohérence/idempotence, placement de l'état,
transversaux (auth/log/config), qualité de la documentation d'architecture,
absence de sur-ingénierie, domaines de défaillance (rayon d'explosion), cohérence
des choix technologiques et extensibilité.

Ne sont **pas** notés ici (traités par leurs piliers dédiés, cf. references
croisées) : les mécaniques de résilience runtime et la perte silencieuse des
échecs permanents (Reliability 03, ex. REL-F2), la structure/verrou de state
Terraform (Terraform 08, TF-F1 Critical), la granularité fine des modules code
(Modularity 09), les mécanismes de découplage (Decoupling 10) et la scalabilité
effective (Scalability 11). Audit **statique** (code/IaC uniquement).

## Strengths
- **Style event-driven serverless adapté et justifié** : webhook GitHub → API GW
  (HTTP API) → Lambda webhook → SQS(+DLQ) → Lambda worker → `InvokeAgentRuntime`
  → agent. Découplage producteur/consommateur, lissage et isolation des échecs par
  file. Rationnel documenté — _evidence: `documentation/ARCHITECTURE.md:9`,
  `.kiro/specs/agent-technical-doc/design.md:5`_.
- **Frontières de composants nettes, responsabilité unique** : la Lambda webhook
  ne fait que valider/filtrer/autoriser/dédupliquer/enfiler et **ne détient pas le
  token GitHub** — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:1`_ ;
  le worker se limite à SQS → invoke avec classification d'erreurs — _evidence:
  `documentation/scripts/lambdas/worker-dispatcher/handler.py:1`_ ; l'agent orchestre
  via injection de dépendances — _evidence:
  `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:39`_.
- **Invocation asynchrone délibérée** : l'entrypoint lance le run en tâche de fond
  (`add_async_task`/`complete_async_task`) et rend la main immédiatement ; le
  worker se libère en ~1 s (pas de plafond synchrone 15 min) — _evidence:
  `documentation/scripts/agents/agent-technical-doc/agent.py:100`_.
- **Invariant anti prompt-injection appliqué par le code** : cible de commit figée
  `docs/agent/**`, sha/branche injectés et jamais dérivés du contenu lu ; LLM = pur
  analyseur sans pouvoir d'écriture — _evidence:
  `documentation/scripts/agents/agent-technical-doc/docagent/paths.py:1`,
  `.kiro/specs/agent-technical-doc/design.md:78`_.
- **Idempotence à deux niveaux cohérente** : `repo#pr#comment_id` (niveau livraison,
  webhook) et `repo#pr#sha` (niveau commit, agent), PutItem conditionnel, relâche
  sur échec — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:210`,
  `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py:20`_.
- **Sans état délibéré** : agent sans AgentCore Memory ni Knowledge Base ; état
  externalisé (DynamoDB + Secrets Manager) ; Lambdas stateless — _evidence:
  `documentation/scripts/agents/agent-technical-doc/agent.py:30`,
  `.kiro/specs/agent-technical-doc/design.md:22`_.
- **Transversaux consistants** : `correlation_id` propagé webhook→worker→runtime,
  config centralisée, masquage systématique des secrets, métriques EMF — _evidence:
  `documentation/scripts/agents/agent-technical-doc/docagent/config.py:1`,
  `documentation/scripts/lambdas/worker-dispatcher/handler.py:19`_.
- **Extensibilité conçue** : `GITHUB_API_BASE` (GitHub Enterprise sans changer le
  code), escalade de modèle pilotée par code déterministe, `DOC_OUTPUT_DIR`
  paramétrable, découverte par `agents.json` — _evidence:
  `documentation/scripts/agents/agent-technical-doc/docagent/config.py:88`,
  `docagent/config.py:100`_.

## Weaknesses / Findings

### [Medium] ARC-F1 — Mono-région sans DR : rayon d'explosion non borné au-delà de la région
- **Evidence:** `documentation/ARCHITECTURE.md:31` (compte unique / `eu-central-1`),
  contexte pack `_context/inventory.md` (« Mono-région, pas de DR »).
- **Impact:** Les domaines de défaillance à l'intérieur du chemin nominal sont bien
  isolés (SQS/DLQ, 3 rôles IAM séparés, sessions runtime isolées), mais une panne
  régionale AWS ou une corruption de la table DynamoDB partagée met tout le service
  hors ligne sans plan de reprise. Le compte et la région uniques constituent un
  rayon d'explosion global non intentionnellement borné.
- **Recommendation:** Documenter explicitement la posture DR/RTO/RPO acceptée pour
  le POC, et pour un passage en production prévoir une stratégie de reprise
  (backups DynamoDB PITR, re-déploiement multi-région piloté par Terraform).
- **Alternative solution:**
  - _Résumé_ : posture active/passive multi-région (secondaire à froid) piloté par
    IaC + PITR sur la table d'idempotence.
    ```mermaid
    flowchart LR
      GH[GitHub webhook] --> R53[Route53 / failover]
      R53 --> P[Region primaire<br/>APIGW+Lambdas+SQS+Runtime]
      R53 -.bascule.-> S[Region secondaire<br/>stack Terraform identique]
      P --> DDBp[(DynamoDB PITR + Global Table)]
      S -.-> DDBp
    ```
  - _Pros_ : survit à une panne régionale ; RPO faible via Global Tables.
  - _Cons_ : coût et complexité opérationnelle accrus ; sur-dimensionné pour un POC.
  - _Effort_ : L.
  - _Cross-pillar impact_ : reliability +, cost -, operational-excellence +/-.
- **Cross-ref:** reliability (03), scalability (11).

### [Low] ARC-F2 — Table DynamoDB multi-usage (idempotence + compteurs de quota)
- **Evidence:** `documentation/scripts/lambdas/webhook-receiver/handler.py:230`
  (clé `ratelimit#<repo>#<bucket>`) coexiste avec les clés d'idempotence
  `repo#pr#comment_id` (`handler.py:210`) et `repo#pr#sha`
  (`docagent/idempotency.py:20`) dans la **même** table.
- **Impact:** La table sert deux préoccupations distinctes (déduplication et
  limitation de débit) écrites par deux propriétaires (webhook, agent). Les clés
  sont namespacées et les opérations atomiques/conditionnelles, donc **pas d'état
  partagé ambigu** ni de course — mais c'est une entorse de cohésion au niveau
  données : un throttle ou une évolution de schéma affecte les deux fonctions.
- **Recommendation:** Acceptable en single-table design ; documenter explicitement
  le contrat de partitionnement. À terme, envisager une table dédiée aux compteurs
  de quota si les profils d'accès divergent.
- **Alternative solution:** None — le design single-table namespacé est approprié
  et courant pour DynamoDB ; la séparation n'apporterait qu'un gain marginal.
- **Cross-ref:** decoupling (10), maintainability (12).

### [Low] ARC-F3 — Absence d'ADR formels et léger décalage doc/code
- **Evidence:** `.kiro/specs/agent-technical-doc/design.md:60` indique
  « Strands / Python 3.11 ARM64 » pour le runtime, alors que le code cible
  Python 3.12 (`_context/inventory.md`, stack). Aucun journal d'ADR versionné.
- **Impact:** La documentation d'architecture est riche (mermaid dans
  `ARCHITECTURE.md` + `design.md` + specs) et correspond globalement au code, mais
  l'absence d'ADR trace mal l'historique des décisions et un détail de version est
  désynchronisé.
- **Recommendation:** Corriger la mention de version et introduire un dossier
  `docs/adr/` léger (format MADR) pour les décisions structurantes (async, LLM pur
  analyseur, single-table).
- **Alternative solution:** None — amélioration de documentation, pas de refonte.
- **Cross-ref:** maintainability (12).

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| ARC-01 | Style architectural adapté au problème et justifié | Met | `documentation/ARCHITECTURE.md:9`, `.kiro/specs/agent-technical-doc/design.md:5` |
| ARC-02 | Frontières de composants nettes, responsabilité unique | Met | `documentation/scripts/lambdas/webhook-receiver/handler.py:1`, `docagent/orchestrator.py:39` |
| ARC-03 | Flux de données et propriété explicites ; pas d'état partagé ambigu | Met | `documentation/ARCHITECTURE.md:120`, `docagent/idempotency.py:20`, `webhook-receiver/handler.py:230` |
| ARC-04 | Patterns d'intégration appropriés (sync vs async, file/API) | Met | `agent.py:100`, `worker-dispatcher/handler.py:59` |
| ARC-05 | Stratégie cohérence & idempotence cohérente aux frontières | Met | `webhook-receiver/handler.py:210`, `docagent/orchestrator.py:150` |
| ARC-06 | Statelessness / placement de l'état délibéré | Met | `agent.py:30`, `.kiro/specs/agent-technical-doc/design.md:22` |
| ARC-07 | Transversaux (auth/log/config) consistants | Met | `docagent/config.py:1`, `worker-dispatcher/handler.py:19` |
| ARC-08 | Design documenté (diagrammes/ADR) & correspond au code | Partial | `documentation/ARCHITECTURE.md:9`, `.kiro/specs/agent-technical-doc/design.md:60` (décalage version, pas d'ADR) |
| ARC-09 | Pas de sur-ingénierie / complexité accidentelle | Met | `docagent/orchestrator.py:39` (DI ciblée, modules à responsabilité unique) |
| ARC-10 | Domaines de défaillance & frontières intentionnels (blast radius) | Partial | `documentation/ARCHITECTURE.md:31` (mono-région, no DR), cf. ARC-F1 |
| ARC-11 | Choix technologiques cohérents & justifiés | Met | `.kiro/specs/agent-technical-doc/design.md:15`, `docagent/config.py:1` |
| ARC-12 | Extensibilité : nouvelles capacités sans refonte | Met | `docagent/config.py:88`, `docagent/config.py:100` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Documenter la posture DR/RTO/RPO ; activer PITR DynamoDB ; préparer un re-déploiement multi-région IaC (ARC-F1) | L |
| P3 | Corriger le décalage de version (Python 3.11→3.12) et introduire un journal ADR léger (ARC-F3) | S |
| P3 | Documenter le contrat de partitionnement single-table (idempotence vs quota) (ARC-F2) | S |

## Notes & assumptions
- Audit **statique** : l'adéquation runtime (isolation effective des sessions,
  comportement réel de la file) est jugée sur le code/IaC et la documentation, non
  sur le déployé.
- **Dé-duplication** : la perte silencieuse des `PermanentError` sans
  `ReportBatchItemFailures` (REL-F2) et l'absence de verrou de state Terraform
  (TF-F1, Critical) sont des défauts réels mais **scorés dans Reliability (03) et
  Terraform (08)** respectivement ; ils ne sont pas re-comptés ici. Le cap global
  de maturité (2/5) induit par TF-F1 est une décision d'orchestration, il
  n'affecte pas le score intrinsèque de conception de ce pilier.
- Contrainte org (CloudTrail/KMS/GuardDuty gérés au niveau org) : sans impact sur
  la conception architecturale ; non pénalisée.
- Coverage élevée (~95 %) : les 4 composants du chemin nominal et les 18 modules
  `docagent` ont été lus ou échantillonnés ; seuls quelques modules périphériques
  (drawio, doc_builder détaillés) n'ont pas été ouverts intégralement.
