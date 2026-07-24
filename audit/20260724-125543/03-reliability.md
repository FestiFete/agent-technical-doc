# Reliability (Fiabilité) — Audit

**Score:** 73/100  **Maturity:** 3 (Defined)  **Coverage:** 90%  **Confidence:** high
**Applicable:** yes

## Charter & scope

Ce pilier évalue la capacité du système à fonctionner correctement et à se rétablir
face aux défaillances : absence de SPOF, redondance, RTO/RPO et sauvegardes,
idempotence des opérations « at-least-once », retries/timeouts, isolation des échecs
asynchrones (DLQ), dégradation gracieuse, gestion des quotas, gestion de changement
sûre, durabilité de l'état, tests de défaillance et confinement du rayon d'impact des
dépendances. Ancrage : AWS Well-Architected — Reliability Pillar.

Hors périmètre (traités ailleurs, cross-référencés) :
- **Verrou de state Terraform absent (TF-F1, Critical)** → pilier **Terraform**. Impact
  fiabilité réel (corruption de state sur apply concurrent) mais scoré une seule fois.
- Contrôles détectifs / observabilité de sécurité (CloudTrail/GuardDuty) → pilier **Security**.

Contrainte d'environnement : audit **statique** (aucun appel AWS live). Le Deny org sur
CloudTrail/KMS/GuardDuty (services centralisés) n'est **pas** pénalisé ici.

## Strengths

- **Architecture 100% serverless managée multi-AZ par défaut** (Lambda, SQS, DynamoDB,
  API GW HTTP, CloudFront, AgentCore) — aucun compute auto-géré, pas de SPOF intra-région.
  _evidence: `terraform/ingestion/main.tf:1`, `terraform/security/main.tf:52`_
- **Idempotence double niveau avec relâche sur échec** : dédup webhook (`repo#pr#comment_id`)
  + agent (`repo#pr#sha`), `PutItem` conditionnel `attribute_not_exists(pk)`, `release()`
  sur échec pour autoriser un re-run. _evidence: `docagent/idempotency.py:24`, `docagent/idempotency.py:52`, `docagent/orchestrator.py:255`_
- **Découplage + isolation des échecs par SQS+DLQ** (maxReceiveCount, visibilité >= timeout
  worker) et **limite de concurrence worker**. _evidence: `terraform/ingestion/main.tf:16`, `terraform/ingestion/main.tf:240`_
- **REL-F1 remédié** : topic SNS d'alarmes créé par défaut, 5 alarmes câblées sur
  `local.alarm_targets` dont l'alarme `main_queue_stalled` sur `ApproximateAgeOfOldestMessage`
  de la file principale (détecte le stall silencieux). _evidence: `terraform/observability/main.tf:34`, `terraform/observability/main.tf:21`, `terraform/observability/main.tf:104`_
- **Gestion des quotas / throttling** : classification des erreurs transitoires (Throttling,
  ServiceQuotaExceeded, 5xx) avec retry, throttling API GW (10 rps / burst 20), rate-limit
  par dépôt, caps de lecture bornés. _evidence: `worker-dispatcher/handler.py:26`, `terraform/ingestion/main.tf:307`, `docagent/retry.py:16`_
- **PITR DynamoDB activé + chiffrement au repos** (clé gérée AWS) sur la table d'idempotence.
  _evidence: `terraform/security/main.tf:74`_
- **Retry idempotent réservé aux lectures GET** ; les écritures GitHub ne sont jamais
  rejouées (évite les doublons), l'échec relâche l'idempotence. _evidence: `docagent/github_client.py:106`_
- **Timeout explicite (60 s) sur tous les appels HTTP GitHub**. _evidence: `docagent/github_client.py:63`_

## Weaknesses / Findings

### [HIGH] REL-F2 — Les erreurs permanentes du worker sont silencieusement perdues

- **Evidence:** `scripts/lambdas/worker-dispatcher/handler.py:106` (bloc `except PermanentError`
  qui log sans `raise`) ; `terraform/ingestion/main.tf:232` (event source mapping **sans**
  `function_response_types = ["ReportBatchItemFailures"]`).
- **Impact:** Un message dont le run échoue de façon permanente (payload invalide, `RUNTIME_ARN`
  absent, `AccessDenied` sur `InvokeAgentRuntime`, erreur Bedrock non transitoire) est **consommé
  et supprimé** de la file sans jamais atteindre la DLQ ni émettre de métrique. Perte silencieuse :
  ni l'alarme `dlq_not_empty`, ni `worker_errors` (le handler renvoie 200), ni `main_queue_stalled`
  (le message est bien retiré) ne se déclenchent. Aucune observabilité de la classe d'échecs la
  plus fréquente pour ce type de pipeline. La demande de documentation est perdue sans trace.
- **Recommendation:** Ne plus absorber les `PermanentError` sans signal. Deux corrections
  complémentaires : (1) émettre une métrique EMF dédiée (`PermanentFailures`) + log structuré ;
  (2) router explicitement les échecs permanents vers la DLQ.
- **Alternative solution:**
  - **Résumé:** Activer `function_response_types = ["ReportBatchItemFailures"]` sur l'event
    source mapping et faire renvoyer au handler les `itemIdentifier` des records permanents
    dans `batchItemFailures`, **ou** publier explicitement le record en DLQ via `SendMessage`
    avant de le consommer. Ajouter une métrique de comptage.
  - **Pros:** Les échecs permanents deviennent visibles (DLQ + alarme existante `dlq_not_empty`
    se déclenche) ; aucune perte silencieuse ; rejeu manuel possible depuis la DLQ ; changement
    localisé (1 ligne Terraform + logique de retour du handler).
  - **Cons:** Avec `ReportBatchItemFailures` et `maxReceiveCount=2`, un permanent sera d'abord
    rejoué une fois (léger surcoût + un log de bruit) avant DLQ — acceptable, ou router
    directement en DLQ pour éviter le rejeu ; nécessite le droit IAM `sqs:SendMessage` sur la
    DLQ si option d'envoi direct.
  - **Effort:** S
  - **Cross-pillar impact:** operational-excellence + (observabilité des échecs), security ~
    (droit SQS supplémentaire si envoi direct DLQ).

### [MEDIUM] REL-F3 — Backoff exponentiel sans jitter

- **Evidence:** `docagent/retry.py:80` (`delay = min(max_delay, base_delay * (2 ** (attempt - 1)))`,
  aucun facteur aléatoire).
- **Impact:** En cas de throttling Bedrock/GitHub touchant plusieurs runs concurrents, les
  tentatives se resynchronisent (thundering herd) et amplifient la contention au lieu de la
  lisser. Effet limité ici par la faible concurrence (worker `maximum_concurrency`), mais
  contraire à la recommandation AWS « backoff **and jitter** ».
- **Recommendation:** Ajouter un jitter (full ou equal jitter) au calcul du délai.
- **Alternative solution:** _None — l'ajout d'un jitter est l'approche standard et suffisante ;
  aucune alternative de conception n'est requise (effort S)._

### [MEDIUM] REL-F4 — Aucun RTO/RPO défini, mono-région sans DR

- **Evidence:** `terraform/observability/providers.tf:14` (region unique) ; aucun `provider`
  secondaire ni réplication cross-région dans les 7 modules ; aucun document RTO/RPO
  (`documentation/AUDIT.md`/`ARCHITECTURE.md` ne les définissent pas).
- **Impact:** En cas d'incident régional (`eu-central-1`), le service est indisponible sans
  procédure de reprise chiffrée en objectifs. Impact atténué car l'état durable critique est
  minimal (table d'idempotence reconstructible en fail-open ; la documentation produite vit
  dans GitHub, externe et durable), mais l'absence d'objectifs explicites reste une lacune.
- **Recommendation:** Documenter RTO/RPO même modestes pour un POC (ex. RTO best-effort,
  RPO ≈ 0 car aucun état métier propre). Décider explicitement mono-région = acceptable pour
  ce POC.
- **Alternative solution:**
  - **Résumé:** Formaliser une posture « mono-région assumée » (redéploiement Terraform dans une
    région de secours comme plan de reprise) plutôt que d'introduire une réplication active.
  - **Pros:** Coût nul, cohérent avec la nature POC et l'état durable quasi nul ; reprise = un
    `terraform apply` dans une autre région + repose des secrets.
  - **Cons:** RTO dépendant d'une action manuelle ; suppose que la corruption du state TF est
    corrigée (cf. TF-F1) pour que le redéploiement soit fiable.
  - **Effort:** S (documentation) — L si réplication active exigée.
  - **Cross-pillar impact:** cost + (pas de coût DR), operational-excellence + (runbook).

### [MEDIUM] REL-F5 — Gestion de changement non sécurisée (pas de canary/blue-green)

- **Evidence:** Aucun `.github/workflows`, aucun CodeBuild/CodePipeline (grep vide, cf. context
  pack) ; `aws_lambda_function.worker`/`webhook` déployées sans alias/version pondérée
  (`terraform/ingestion/main.tf:200`, `:222`) ; déploiement Terraform manuel multi-module.
- **Impact:** Un déploiement défectueux (Lambda ou image AgentCore) bascule 100% du trafic
  d'un coup, sans canary ni rollback automatisé. Combiné à **TF-F1** (state S3 sans verrou,
  Critical, pilier Terraform), un apply concurrent/interrompu peut corrompre le state.
- **Recommendation:** Introduire des alias Lambda + déploiement pondéré (CodeDeploy) pour les
  fonctions, et un verrou de state (cf. TF-F1). A minima, documenter une procédure de rollback.
- **Alternative solution:**
  - **Résumé:** Alias `live` + `aws_lambda_alias` avec `routing_config` (canary 10%) piloté par
    CodeDeploy, ou rollback manuel documenté (redeploy de l'artefact précédent) pour rester léger.
  - **Pros:** Réduit le blast radius d'un mauvais déploiement ; rollback rapide.
  - **Cons:** Complexité CI/CD ajoutée, surdimensionnée pour un POC à faible trafic.
  - **Effort:** M
  - **Cross-pillar impact:** operational-excellence +, terraform + (state lock requis en amont).
  - **Cross-ref:** TF-F1 (Terraform, Critical).

### [LOW] REL-F6 — Pas de timeout explicite sur les appels Bedrock/AgentCore

- **Evidence:** `worker-dispatcher/handler.py:60` (`invoke_agent_runtime` sans `botocore.Config`) ;
  `docagent/analyzer.py` (client Bedrock sans timeouts configurés — aucun `Config`/`read_timeout`
  trouvé, grep vide sur `scripts/**`).
- **Impact:** Les appels s'appuient sur les timeouts botocore par défaut ; ils sont bornés par le
  timeout Lambda (worker) et le run AgentCore, donc le risque d'accumulation est faible, mais un
  timeout explicite rendrait le comportement de reprise déterministe.
- **Recommendation:** Passer un `botocore.Config(connect_timeout, read_timeout, retries)` explicite
  aux clients boto3.
- **Alternative solution:** _None — configuration ponctuelle, aucune alternative de conception._

## Criteria grid

| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| REL-01 | Pas de SPOF critique (multi-AZ/redondance là où justifié) | Met | `terraform/ingestion/main.tf:1`, `terraform/security/main.tf:52` (services managés multi-AZ) |
| REL-02 | RTO/RPO définis + stratégie de sauvegarde | Partial | PITR présent (`terraform/security/main.tf:74`) mais aucun RTO/RPO ni DR — voir REL-F4 |
| REL-03 | Sauvegardes existantes, chiffrées, restauration testable | Met | `terraform/security/main.tf:74` (PITR) + chiffrement au repos par défaut |
| REL-04 | Idempotence des ops rejouées / at-least-once | Met | `docagent/idempotency.py:24`, `docagent/orchestrator.py:255` |
| REL-05 | Retries backoff+jitter ; timeouts sur tous les appels distants | Partial | backoff **sans jitter** (`docagent/retry.py:80`) ; timeout GitHub 60s (`github_client.py:63`) mais Bedrock sans timeout explicite — REL-F3/F6 |
| REL-06 | Dead-letter / isolation des échecs pour l'asynchrone | Partial | DLQ présente (`terraform/ingestion/main.tf:16`) mais échecs permanents jamais routés en DLQ — REL-F2 |
| REL-07 | Dégradation gracieuse & circuit breaking | Partial | fail-open idempotence (`idempotency.py:33`), commentaire terminal + EMF best-effort (`orchestrator.py:210`) ; pas de circuit breaker |
| REL-08 | Health checks pilotant une reprise automatisée | N/A | 100% serverless managé (Lambda/SQS/AgentCore) : santé & reprise assurées par la plateforme, pas de compute auto-géré |
| REL-09 | Quotas/limites compris ; throttling géré | Met | `worker-dispatcher/handler.py:26`, `terraform/ingestion/main.tf:307`, `docagent/retry.py:16` |
| REL-10 | Gestion de changement sûre (canary/blue-green, migrations réversibles) | Missing | pas de CI/CD, pas d'alias/canary Lambda, déploiement manuel — REL-F5 |
| REL-11 | État géré durablement (pas d'état critique sur compute éphémère) | Met | état dans DynamoDB/Secrets Manager/GitHub ; tarball en mémoire = données de travail transitoires (`orchestrator.py`) |
| REL-12 | Modes de défaillance testés (fault injection) | Partial | tests des chemins d'erreur (transitoire/permanent, release) mais pas d'injection de fautes/chaos — `scripts/lambdas/tests/`, `docagent` tests |
| REL-13 | Rayon d'impact des défaillances de dépendances confiné | Met | découplage SQS + concurrence bornée + garde fork + idempotence (`terraform/ingestion/main.tf:240`, `orchestrator.py:180`) |

## Prioritized improvements

| priority | action | effort |
|----------|--------|--------|
| P1 | REL-F2 : activer `ReportBatchItemFailures` (ou envoi DLQ explicite) + métrique `PermanentFailures` sur les échecs permanents du worker | S |
| P2 | REL-F3 : ajouter un jitter au backoff exponentiel (`retry.py`) | S |
| P2 | REL-F5 : documenter un runbook de rollback ; introduire alias/canary Lambda (dépend du verrou de state TF-F1) | M |
| P3 | REL-F4 : documenter RTO/RPO et acter la posture mono-région du POC | S |
| P3 | REL-F6 : `botocore.Config` explicite (connect/read timeouts) sur les clients Bedrock/AgentCore | S |

## Notes & assumptions

- Audit **statique** : les comportements vérifiables uniquement au runtime (déclenchement réel
  des alarmes, restauration PITR effective, chiffrement effectif) sont jugés sur l'IaC/le code.
- **REL-F1 est bien remédié** (topic SNS + alarme `main_queue_stalled` câblés) : plus de finding
  Critical sur ce point. La seule Critical touchant la fiabilité (state TF non verrouillé, TF-F1)
  est **scorée dans le pilier Terraform** et seulement cross-référencée ici (pas de double compte) ;
  elle contribuera au capping global mais pas au score de ce pilier.
- **REL-08 marqué N/A** (justifié) : la reprise sur défaillance de compute est assurée par les
  services managés ; il n'existe aucune ressource auto-gérée nécessitant un health check applicatif.
- Coverage 90% : quasi tous les critères évaluables en statique ; confiance élevée (code et IaC
  lus directement, `path:line` à l'appui).
