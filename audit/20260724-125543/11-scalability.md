# Scalabilité — Audit

**Score:** 88/100  **Maturity:** 4 (Managed)  **Coverage:** 100%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Ce pilier évalue la capacité du système à absorber une montée en charge : mise à
l'échelle horizontale (scale-out), absence d'état sur le chemin de traitement,
partitionnement et capacité on-demand de la couche de données, absence de goulot
mono-threadé / singleton sur le chemin chaud, mécanismes de back-pressure /
buffering sous pic, protection des dépendances aval (limites de concurrence),
compréhension des quotas et de la marge (headroom), et absence de croissance
mémoire non bornée qui bloquerait la mise à l'échelle.

Hors scope (traités ailleurs) : résilience/rejeu des échecs (Reliability — REL-F2
`ReportBatchItemFailures`), latence/perf unitaire (Performance Efficiency),
coût des invocations (Cost), verrou de state Terraform (Terraform TF-F1).

Audit **statique** (aucun appel AWS live). Contrainte org (Deny CloudTrail/KMS/
GuardDuty) sans effet sur ce pilier.

## Strengths
- Compute **sans état** de bout en bout : Lambdas webhook/worker sans état local,
  agent explicitement « Sans état : ni AgentCore Memory, ni Knowledge Base » —
  _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:44`_
- Élasticité on-demand native : Lambda auto-scale, event source mapping SQS→worker
  avec `scaling_config`, AgentCore Runtime managé — _evidence: `documentation/terraform/ingestion/main.tf:270`_
- Couche de données on-demand : DynamoDB `PAY_PER_REQUEST` (pas de capacité
  provisionnée à dimensionner), purge TTL — _evidence: `documentation/terraform/security/main.tf:63`_
- Découplage + buffering par SQS (file principale + DLQ) lissant les pics et
  isolant les échecs — _evidence: `documentation/terraform/ingestion/main.tf:14`_
- Back-pressure multi-niveaux : throttling API GW (10 rps / burst 20), quota
  anti-DoS par dépôt et fenêtre glissante, plafond de concurrence worker —
  _evidence: `documentation/terraform/ingestion/main.tf:341`, `documentation/scripts/lambdas/webhook-receiver/handler.py:214`_
- Protection des dépendances aval : concurrence worker plafonnée (défaut 5) qui
  borne les `InvokeAgentRuntime` concurrents vers Bedrock/AgentCore/GitHub —
  _evidence: `documentation/terraform/ingestion/variables.tf:73`_
- Invocation asynchrone : le slot de concurrence worker est libéré en ~1 s
  (l'agent bascule `/ping` en `HealthyBusy`), améliorant le débit du chemin chaud —
  _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:100`_
- Sessions externalisées : idempotence dans DynamoDB (`repo#pr#*`), aucun état de
  session en mémoire — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:279`_
- Clés de partition à forte cardinalité : `repo#pr#comment_id` (idempotence) et
  `ratelimit#repo#bucket` (quota) — pas de clé unique concentrant tout le trafic —
  _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:191`_

## Weaknesses / Findings

### [Medium] SCAL-F1 — Quotas Bedrock/AgentCore = plafond de débit non modélisé
- **Evidence:** `documentation/terraform/ingestion/variables.tf:71` (`worker_max_concurrency` défaut 5) ; `documentation/scripts/agents/agents.json:6` (modèles Bedrock Haiku/Sonnet) ; aucun document de capacité (grep : pas de `capacity`/`quota`/`load test`).
- **Impact:** Le débit soutenu est plafonné par (a) la concurrence worker (5, délibérée) et surtout (b) le TPS / quota de tokens des modèles Bedrock invoqués par l'agent, et la limite de concurrence des sessions AgentCore Runtime. Ces plafonds aval ne sont pas explicitement modélisés ni la marge (headroom) documentée. En croissance, un pic de PR au-delà de la capacité Bedrock se traduirait par des `ThrottlingException` — correctement classées transitoires et rejouées (`worker-dispatcher/handler.py:22`), mais sans visibilité proactive sur le seuil.
- **Recommendation:** Documenter le modèle de capacité (runs/h soutenables) en fonction de la concurrence worker, du quota TPS Bedrock demandé et de la limite de sessions AgentCore ; ajouter une alarme sur l'âge de la file (déjà présente, `observability/main.tf:104`) comme signal précoce de saturation aval, et demander une hausse de quota Bedrock si la croissance l'exige.
- **Alternative solution:** *Queue-based load leveling assumé* — conserver SQS comme tampon et ajuster `worker_max_concurrency` au TPS Bedrock réellement accordé plutôt qu'à une valeur fixe.
  - Pros : absorbe les pics sans perte (rétention 4 j) ; découplage débit d'arrivée / débit de traitement ; tuning déclaratif.
  - Cons : latence de bout en bout accrue sous pic ; nécessite de connaître le quota Bedrock effectif ; ne relève pas le plafond, il le gère.
  - Effort : S.
  - Cross-pillar impact : reliability + (pas de perte sous surge), performance-efficiency +/- (débit vs latence), cost neutre.

### [Low] SCAL-F2 — Tarball chargé intégralement en mémoire avant lecture bornée
- **Evidence:** `documentation/scripts/agents/agent-technical-doc/docagent/repo_reader.py:44` (`extract_tarball_safely(tar_bytes: bytes, ...)`) — l'archive `.tar.gz` complète est tenue en RAM (`io.BytesIO(tar_bytes)`) puis extraite ; les plafonds `ReadCaps` (`config.py:74`) ne bornent que la **lecture** post-extraction, pas la taille de l'archive téléchargée.
- **Impact:** Pour un dépôt très volumineux, l'empreinte mémoire du conteneur AgentCore croît avec la taille de l'archive (compressée + extraite sur disque), indépendamment des caps de contexte LLM. Risque théorique d'OOM sur un dépôt exceptionnellement gros. Atténué en pratique : les caps de lecture (40 fichiers sélectionnés / 80 Ko / 1,2 Mo) bornent le contexte, et le conteneur ARM64 dispose de mémoire allouée ; mais aucun plafond explicite sur la taille de l'archive.
- **Recommendation:** Borner la taille du tarball téléchargé (garde-fou `RepoTooLargeError` avant extraction) ou streamer l'extraction membre par membre en s'arrêtant dès que `max_files`/`max_total_bytes` sont atteints, plutôt que d'extraire toute l'archive.
- **Alternative solution:** *Extraction paresseuse en flux* — parcourir `tar.getmembers()` et n'extraire/lire que jusqu'aux plafonds.
  - Pros : mémoire et I/O bornées quelle que soit la taille du dépôt ; conserve les protections anti-traversal existantes.
  - Cons : logique d'extraction un peu plus complexe ; l'archive compressée reste en mémoire tant qu'on n'utilise pas un download streamé.
  - Effort : M.
  - Cross-pillar impact : reliability + (robustesse gros dépôts), performance-efficiency + (moins de RAM/I/O), sécurité neutre.

### [Low] SCAL-F3 — Pas de test de charge ni de modèle de capacité
- **Evidence:** Aucun test de charge dans le repo (grep : pas de `locust`/`k6`/`load`) ; l'E2E valide le fonctionnel en conditions réelles mais pas la tenue en charge (`documentation/scripts/agents/agent-technical-doc/e2e/`).
- **Impact:** Les seuils de saturation (concurrence, TPS Bedrock, file SQS) ne sont pas empiriquement établis ; la marge réelle avant dégradation est inconnue.
- **Recommendation:** Ajouter un scénario de charge léger (rafale de N webhooks signés) pour valider le comportement de back-pressure et calibrer `worker_max_concurrency` et le quota Bedrock. Priorité faible pour un POC.
- **Alternative solution:** None — pour un POC piloté par événements à faible volume, un test de charge formel n'est pas indispensable ; la métrique d'âge de file en production suffit à détecter la saturation.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SCAL-01 | Compute sans état permettant le scale-out | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:44`, `documentation/scripts/lambdas/worker-dispatcher/handler.py:75` |
| SCAL-02 | Auto-scaling / élasticité on-demand | Met | `documentation/terraform/ingestion/main.tf:270` |
| SCAL-03 | Couche de données scalable (partitionnement, capacité on-demand) | Met | `documentation/terraform/security/main.tf:63` |
| SCAL-04 | Pas de goulot mono-threadé/singleton sur le chemin chaud | Met | `documentation/scripts/lambdas/worker-dispatcher/handler.py:88`, `documentation/scripts/agents/agent-technical-doc/agent.py:100` |
| SCAL-05 | Back-pressure / rate limiting / buffering sous pic | Met | `documentation/terraform/ingestion/main.tf:14`, `documentation/scripts/lambdas/webhook-receiver/handler.py:214`, `documentation/terraform/ingestion/main.tf:341` |
| SCAL-06 | Clés de partition évitant les hot spots | Met | `documentation/scripts/lambdas/webhook-receiver/handler.py:191`, `:279` |
| SCAL-07 | Sessions sans état (externalisées) | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:44`, `documentation/scripts/lambdas/webhook-receiver/handler.py:279` |
| SCAL-08 | Limites de concurrence & protection aval | Met | `documentation/terraform/ingestion/main.tf:270`, `documentation/terraform/ingestion/variables.tf:71` |
| SCAL-09 | Quotas/limites de scaling compris ; marge | Partial | `documentation/terraform/ingestion/variables.tf:71`, `documentation/scripts/agents/agents.json:6` |
| SCAL-10 | Testé en charge / modèle de capacité | Missing | `documentation/scripts/agents/agent-technical-doc/e2e/` (aucun test de charge) |
| SCAL-11 | Pas de croissance mémoire non bornée bloquant le scaling | Partial | `documentation/scripts/agents/agent-technical-doc/docagent/repo_reader.py:44`, `documentation/scripts/agents/agent-technical-doc/docagent/config.py:74` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Documenter le modèle de capacité (runs/h) et aligner `worker_max_concurrency` sur le quota TPS Bedrock accordé (SCAL-F1) | S |
| P2 | Borner la taille du tarball / extraction en flux avec arrêt aux plafonds (SCAL-F2) | M |
| P3 | Ajouter un scénario de charge léger (rafale de webhooks) pour calibrer les seuils (SCAL-F3) | M |

## Notes & assumptions
- Architecture événementielle et sans état : les fondamentaux du scale-out sont
  solides (SCAL-01/02/03/05/07/08 Met). Le plafond de concurrence worker (5) est
  un choix délibéré de protection aval **et** un plafond de débit ajustable ; il
  n'est pas un goulot mono-threadé et ne garantit pas d'échec à la croissance
  attendue d'un POC — d'où **aucun finding High/Critical**.
- Aucun goulot dur garantissant l'échec n'a été identifié : le vrai plafond
  soutenu est le quota TPS Bedrock (aval, ajustable par demande de hausse),
  correctement traité comme erreur transitoire rejouable côté worker.
- Coverage 100 % (les 11 critères sont évaluables en statique). Confidence
  `medium` : l'absence de test de charge empêche de confirmer empiriquement les
  seuils de saturation et la marge réelle (SCAL-09/10).
- Contrainte org (Deny CloudTrail/KMS/GuardDuty) sans impact sur ce pilier.
