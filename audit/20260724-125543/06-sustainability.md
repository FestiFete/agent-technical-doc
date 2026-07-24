# Sustainability (Durabilité) — Audit

**Score :** 98/100  **Maturité :** 5 (Optimized)  **Couverture :** 95%  **Confiance :** high
**Applicable :** oui

## Charter & périmètre

Ce pilier évalue l'empreinte environnementale du workload : minimisation de l'énergie
consommée pour un service rendu donné (calcul efficace, absence de gaspillage à vide,
matériel adapté), minimisation des données stockées/dupliquées, et adéquation
demande/ressources. Il s'appuie sur le pilier Sustainability du AWS Well-Architected
Framework ([AWS WA Sustainability Pillar](https://docs.aws.amazon.com/sustainability/latest/userguide/resources.html)).

Ne sont **pas** couverts ici (jugés dans leurs pilliers respectifs, cross-référencés
plutôt que doublement notés) : le dimensionnement/coût pur (pilier 05 Cost Optimization),
la fiabilité des chemins d'échec (pilier 03 Reliability, ex. REL-F2), et l'absence de
verrou de state Terraform (pilier 08 — finding Critical qui cape la maturité **globale**
à 2/5, sans effet sur le score propre de ce pilier).

Analyse **statique** (code/IaC uniquement, `live_aws=OFF`) : l'utilisation réelle
(taux d'idle observé, volumétrie de logs effective) n'est pas mesurable ; elle est
inférée du modèle d'exécution événementiel et des plafonds codés.

## Strengths

- **Architecture 100% serverless, scale-to-zero, sans compute à vide.** Le workload est
  déclenché uniquement par un `@mention` sur PR : webhook → SQS → worker → `InvokeAgentRuntime`.
  Aucun EC2/ECS/instance permanente. Les Lambdas et le runtime AgentCore ne consomment qu'à
  l'invocation — _evidence : `documentation/terraform/ingestion/main.tf:186-235` (Lambdas à la demande),
  event source mapping SQS `documentation/terraform/ingestion/main.tf:238`_.
- **Calcul ARM/Graviton partout.** Les deux Lambdas sont en `architectures = ["arm64"]` et
  l'image du runtime agent est construite pour ARM64 — _evidence :
  `documentation/terraform/ingestion/main.tf:192`, `:222` ; `documentation/scripts/agents/agent-technical-doc/Dockerfile:1` (`FROM --platform=linux/arm64`)_.
- **Services managés exclusivement.** Bedrock AgentCore, Lambda, SQS, DynamoDB (on-demand),
  API Gateway, CloudFront, WAF, Secrets Manager — aucun composant self-managed always-on à
  maintenir/alimenter — _evidence : carte des modules Terraform (`_context/inventory.md`) ;
  `documentation/terraform/security/main.tf:57-70` (DynamoDB `PAY_PER_REQUEST` + TTL)_.
- **Minimisation & cycle de vie des données.** DynamoDB en `PAY_PER_REQUEST` avec TTL activé
  (purge automatique des clés d'idempotence, défaut 30 j) ; rétention SQS bornée (4 j file
  principale, 14 j DLQ) ; logs CloudWatch à 14 j ; images ECR purgées par lifecycle policy.
  Agent sans état (ni Memory ni Knowledge Base) → aucune duplication persistante des données —
  _evidence : `documentation/terraform/security/main.tf:59,67-69` ; `documentation/terraform/ingestion/main.tf:9,16` ;
  `documentation/terraform/ingestion/variables.tf:65-68` ; `documentation/terraform/ecr/main.tf:22-51`_.
- **Traitement borné, pas de recompute gaspilleur.** Plafonds de lecture stricts
  (40 fichiers sélectionnés / 80 Ko par fichier / 1,2 Mo total) qui bornent le contexte LLM,
  et tiering de modèle : Haiku 4.5 par défaut, escalade vers Sonnet 4.6 **uniquement** au-delà
  de 25 fichiers ou 400 Ko — le gros modèle n'est pas invoqué inutilement. Idempotence
  `repo#pr#sha` qui évite de refaire l'analyse d'un même état — _evidence :
  `documentation/scripts/agents/agent-technical-doc/docagent/config.py:64-67,89-95` ;
  `documentation/scripts/agents/agents.json:8-14`_.
- **Événementiel, pas de polling applicatif.** Aucune boucle de polling dans le code : le webhook
  enfile dans SQS, et c'est le poller managé de l'event source mapping Lambda↔SQS (long-poll géré
  par AWS) qui déclenche le worker ; invocation agent **asynchrone**. `batch_size = 1` +
  `maximum_concurrency` — _evidence : `documentation/terraform/ingestion/main.tf:237-246`_.
- **Volume d'observabilité proportionné.** Métriques EMF légères sur stdout, rétention logs 14 j,
  et instrumentation OTEL volontairement réduite (`requests`, `urllib3` désactivés) pour limiter
  l'overhead — _evidence : `documentation/scripts/agents/agent-technical-doc/Dockerfile:12`
  (`OTEL_PYTHON_DISABLED_INSTRUMENTATIONS`) ; `documentation/terraform/ingestion/main.tf:176,181`
  (rétention 14 j) ; `_context/inventory.md` (métriques EMF)_.

## Weaknesses / Findings

### [Info] SUS-F1 — Choix de région non explicitement motivé par la durabilité

- **Evidence :** `documentation/scripts/agents/agents.json:5` (`"BEDROCK_REGION": "eu-central-1"`) ;
  `documentation/scripts/agents/agent-technical-doc/docagent/config.py:79` (défaut `eu-central-1`).
- **Impact :** La région est figée sur `eu-central-1` (Francfort). Aucun élément documenté
  n'indique que la durabilité (intensité carbone du réseau électrique régional) ait pesé dans
  le choix — vraisemblablement piloté par la résidence des données EU et la latence. L'impact
  est mineur : `eu-central-1` est une région européenne, et la marge de manœuvre est de toute
  façon contrainte (souveraineté des données). Il ne s'agit pas d'un gaspillage.
- **Recommendation :** Documenter, dans `ARCHITECTURE.md` ou un ADR, que le choix de région
  répond d'abord à des contraintes de résidence/latence, et — si un jour la contrainte se
  relâche — arbitrer en tenant compte du profil de durabilité AWS de la région
  ([AWS WA Sustainability Pillar](https://docs.aws.amazon.com/sustainability/latest/userguide/resources.html)).
- **Alternative solution :** None — l'approche actuelle est appropriée : la région est
  contrainte par la résidence des données, laisser flexible n'apporterait pas de gain net et
  compromettrait la conformité.

_Aucun finding Critical ou High sur ce pilier : le workload est conçu de façon frugale par
construction (serverless événementiel, ARM64, traitement borné, données minimisées)._

## Criteria grid

| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SUS-01 | Forte utilisation ; scale-to-zero / adéquation à la demande (pas d'idle burn) | Met | `documentation/terraform/ingestion/main.tf:186-246` ; `documentation/terraform/security/main.tf:59` |
| SUS-02 | Calcul énergétiquement efficace (ARM/Graviton, serverless) | Met | `documentation/terraform/ingestion/main.tf:192,222` ; `documentation/scripts/agents/agent-technical-doc/Dockerfile:1` |
| SUS-03 | Services managés plutôt que self-managed always-on | Met | `_context/inventory.md` (carte modules) ; `documentation/terraform/security/main.tf:57-70` |
| SUS-04 | Minimisation des données : rétention/lifecycle, pas de duplication inutile | Met | `documentation/terraform/security/main.tf:59,67-69` ; `documentation/terraform/ingestion/main.tf:9,16` ; `documentation/terraform/ecr/main.tf:22-51` |
| SUS-05 | Algorithmes efficaces / traitement borné (pas de recompute gaspilleur) | Met | `documentation/scripts/agents/agent-technical-doc/docagent/config.py:64-67,89-95` ; `documentation/scripts/agents/agents.json:8-14` |
| SUS-06 | Batching/async plutôt que polling constant | Met | `documentation/terraform/ingestion/main.tf:237-246` |
| SUS-07 | Choix de région tenant compte de la durabilité quand c'est flexible | Partial | `documentation/scripts/agents/agents.json:5` ; `documentation/scripts/agents/agent-technical-doc/docagent/config.py:79` |
| SUS-08 | Tiers de stockage bien dimensionnés ; données froides efficaces | Met | `documentation/terraform/security/main.tf:59,67-69` ; `documentation/terraform/ecr/main.tf:22-51` ; `documentation/terraform/ingestion/main.tf:176,181` |
| SUS-09 | Environnements test/dev non laissés à tourner à vide | Met | `_context/inventory.md` (e2e local `local_run.py`) ; `documentation/terraform/ingestion/main.tf:186-235` (tout à la demande) |
| SUS-10 | Volume d'observabilité/logs proportionné | Met | `documentation/scripts/agents/agent-technical-doc/Dockerfile:12` ; `documentation/terraform/ingestion/main.tf:176,181` |

## Prioritized improvements

| priority | action | effort |
|----------|--------|--------|
| P3 | Documenter (ADR) le rationnel du choix de région et le critère durabilité pour tout futur arbitrage flexible (SUS-F1) | S |
| P3 | Envisager l'ajout d'une balise/attribut de suivi d'empreinte (ex. Customer Carbon Footprint Tool) une fois en production pour objectiver l'utilisation réelle | S |

## Notes & assumptions

- Audit **statique** : le taux d'idle réel, le volume de logs effectif et l'utilisation
  concrète des Lambdas ne sont pas mesurés ; les verdicts s'appuient sur le modèle d'exécution
  événementiel et les plafonds codés, cohérents et vérifiés.
- **Contrainte org** (contexte partagé) : les Deny org sur CloudTrail/KMS/GuardDuty ne sont
  **pas** pénalisés ici — ils sont sans effet sur la durabilité (voire favorables : pas de CMK
  ni de trail account-local à alimenter).
- **Dé-duplication :** le dimensionnement fin et l'absence de budgets relèvent du pilier 05
  (Cost) ; la suppression silencieuse des échecs permanents (REL-F2) et l'absence de verrou de
  state (TF, Critical qui cape la maturité globale) sont notés dans leurs pilliers — non
  recomptés ici. Le score propre de ce pilier reste 98/100 ; le cap global à 2/5 (Critical TF)
  s'applique à la synthèse, pas à cette note.
- Couverture 95% : les 10 critères ont pu être évalués sur pièces ; seule l'utilisation runtime
  réelle échappe à l'analyse statique.
