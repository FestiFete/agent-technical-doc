# Shared Context Pack — agent-technical-doc

Static audit (live_aws = OFF). All evidence must be code/IaC `path:line` or doc URL.
Sub-agents may read deeper into files relevant to their pillar. Paths are relative
to the repo root `/Users/g.mirambeau/Development/AWS/agent-technical-doc`.

## Project

**agent-technical-doc** — agent de documentation technique headless sur AWS Bedrock
AgentCore. Un commentaire `@agent-technical-doc` sur une PR GitHub déclenche : webhook
→ API Gateway (HTTP API, fronté par CloudFront + WAFv2) → Lambda webhook-receiver →
SQS (+DLQ) → Lambda worker-dispatcher → `InvokeAgentRuntime` → agent (clone RO du repo →
analyse LLM Bedrock → commit `docs/agent/**` + commentaire de PR). Le LLM est un pur
analyseur (aucun pouvoir d'écriture ; la cible de commit est figée par le code).
Déployé et validé E2E en conditions réelles (compte 375039967495, eu-central-1) — mais
**cet audit est statique** (code/IaC uniquement, aucun appel AWS live).

## ⚠️ Contrainte organisationnelle majeure (à intégrer par TOUS les sous-agents)

Le rôle SSO utilisé pour déployer (`AWSReservedSSO_NewSysOps`) porte des **Deny explicites
au niveau de l'organisation** sur des services de sécurité centralisés :

- **CloudTrail** : Deny explicite sur tout le namespace (`cloudtrail:CreateTrail` ET
  `cloudtrail:DescribeTrails` échouent avec `AccessDeniedException ... explicit deny in an
  identity-based policy`). → CloudTrail est géré **au niveau org** (un trail org-wide couvre
  déjà ce compte). Le module fournit l'IaC du trail mais il est **désactivé ici** :
  `terraform/observability/terraform.tfvars:8` `enable_cloudtrail = false`.
- **KMS** : Deny sur `kms:CreateKey` (documenté de longue date) → pas de CMK, clés gérées AWS.
- **GuardDuty** : très probablement géré au niveau org de la même façon (détecteur unique
  par compte/région). Actuellement laissé activé dans le tfvars (ligne commentée prête à
  basculer `enable_guardduty = false` si le même Deny survient).

**Implication pour la notation :** le fait que CloudTrail/GuardDuty soient désactivés
**dans ce compte** n'est PAS une faiblesse du projet. Le projet fournit l'IaC (togglable,
défaut activé) et s'adapte correctement au garde-fou org (services centralisés). Les
contrôles détectifs doivent être jugés `Partial` (présents au niveau org — hypothèse
documentée, non vérifiable en statique car le rôle ne peut même pas les lire), **pas
`Missing`**, et **aucun nouveau finding ne doit pénaliser cette désactivation**. Le trail
CloudTrail account-local n'étant pas déployable ici, c'est une limite d'environnement, pas
un défaut de conception. Mentionner cette contrainte dans le `coverage`/`notes`.

## Emplacements clés

```
documentation/
  README.md, ARCHITECTURE.md, AUDIT.md            # docs projet (mermaid, inventaire, audit)
  scripts/agents/agents.json                       # config agent (enabled, env, MODEL_ID, escalade)
  scripts/agents/agent-technical-doc/
    agent.py                                        # entrypoint BedrockAgentCoreApp (async)
    instructions.md                                 # prompt système (anti prompt-injection)
    Dockerfile                                      # image ARM64
    requirements.txt / requirements-dev.txt
    docagent/                                       # 18 modules logique métier (testable, DI)
      orchestrator, github_auth, secrets, github_client, repo_reader, selection, analyzer,
      drawio, doc_builder, committer, comments, idempotency, metrics, paths, payload,
      retry, correlation, config
    e2e/                                            # local_run.py, smoke_check.py, harness.py, README
    tests/                                          # 18 fichiers de tests (agent)
  scripts/lambdas/
    webhook-receiver/handler.py                     # HMAC (+ X-Origin-Verify) + filtre + authz + dedup + quota + enqueue
    worker-dispatcher/handler.py                    # SQS -> InvokeAgentRuntime (classif. transitoire/permanent)
    tests/                                          # test_webhook_receiver.py, test_worker_dispatcher.py
  terraform/                                        # 7 modules (voir map) + shared.tfvars
.kiro/specs/agent-technical-doc/                    # design.md, requirements.md, tasks.md
audit/                                              # audits précédents (20260723-*, 20260724-082551)
```

## Volumétrie (mesurée)

- Python hors tests : ~3 114 LOC ; tests : ~1 729 LOC ; Terraform : ~2 243 LOC.
- Tests : **107 agent (2 skip intentionnels) + 23 lambdas = 130**, tous verts, sans réseau
  (injection de dépendances, imports boto3/strands/pyjwt différés). Pas de couverture mesurée.

## Langages & stack

- **Python 3.12** (Lambdas + agent runtime).
- **Terraform** (`required_version >= 1.6.0`, provider aws `~> 6.0`), backend S3, `.terraform.lock.hcl` présent dans les 7 modules.
- Runtime : AWS Bedrock AgentCore (conteneur ARM64), Strands + Bedrock (Claude Haiku 4.5 défaut / Sonnet 4.6 escalade).
- Dépendances : `bedrock-agentcore`, `strands-agents[otel]`, `boto3`, `pyjwt[crypto]`, `aws-opentelemetry-distro`, `pytest` (dev).

## Carte des modules Terraform (7)

| Module | Rôle | Dépendances (remote_state) |
|--------|------|----------------------------|
| bootstrap | bucket S3 de state (backend **local**) | — |
| ecr | repository d'images | — |
| security | Secrets Manager (github-token, webhook-hmac) + DynamoDB idempotence | — |
| roles | rôles IAM (`limited-*`, moindre privilège) | ecr, security |
| runtime | build/push image ARM64 + AgentCore Runtime + logs | ecr, roles, security |
| ingestion | API GW + CloudFront + WAFv2 + λ webhook + SQS/DLQ + λ worker + IAM | security, runtime |
| observability | dashboard + alarmes + topic SNS + (CloudTrail/GuardDuty togglables) | ingestion |

## Ground truth IaC vérifié (grep/read, faisant autorité — remplace toute mémoire)

- **WAF PRÉSENT** — `terraform/ingestion/waf.tf` : CloudFront + WAFv2 WebACL (Core Rule Set,
  Known Bad Inputs, rate-based, body-size) devant l'HTTP API + secret partagé `X-Origin-Verify`
  vérifié par la Lambda webhook **avant** HMAC.
- **REL-F1 REMÉDIÉ** — `terraform/observability/main.tf` : `aws_sns_topic.alarms` (count via
  `var.create_alarm_topic`, défaut `true`, ligne 34), abonnement email optionnel (ligne 39),
  `local.alarm_targets = concat(var.alarm_actions, aws_sns_topic.alarms[*].arn)` (ligne 21),
  alarme `main_queue_stalled` sur `ApproximateAgeOfOldestMessage` de la file principale
  (ligne 104, seuil `var.queue_max_age_seconds` défaut 900), widget dashboard « âge », output
  `alarm_topic_arn`. Les 5 alarmes utilisent désormais `local.alarm_targets` (notification réelle).
- **REL-F2 TOUJOURS OUVERT** — **aucun** `function_response_types = ["ReportBatchItemFailures"]`
  sur l'event source mapping (`terraform/ingestion/main.tf:238`, grep vide) ; le worker attrape
  les `PermanentError` par record sans re-raise (`worker-dispatcher/handler.py`) → les échecs
  permanents sont silencieusement supprimés (jamais en DLQ, aucune métrique). Finding High réel.
- **VERROU DE STATE ABSENT (TF-F1)** — les blocs `backend "s3"` (ex. `observability/providers.tf`)
  n'ont **ni `use_lockfile = true` ni `dynamodb_table`** (grep : le seul `aws_dynamodb_table` est
  la table d'idempotence applicative dans `security/main.tf:57`, pas un verrou de state). State S3
  partagé **sans verrouillage** → risque de corruption sur apply concurrent. Charte TF : « unlocked
  shared state = Critical ». **Finding Critical → cap maturité globale à 2/5.**
- **CloudTrail DÉSACTIVÉ ici** (org-managed, cf. contrainte ci-dessus) — IaC présente
  (`terraform/observability/cloudtrail.tf`) mais `enable_cloudtrail = false`
  (`terraform/observability/terraform.tfvars:8`). GuardDuty encore activé (défaut).
- **Pas de budgets / cost anomaly** — aucun `aws_budgets_budget` (grep vide) → finding coût.
- **CMK KMS retirée** — `security/main.tf` : clés gérées AWS (Deny org `kms:CreateKey`).
- **Aucun pipeline CI/CD** — pas de `.github/workflows`, pas de CodeBuild/CodePipeline. Déploiement
  Terraform manuel multi-module ; secrets posés à la main. Pas de gate de qualité automatisé.

## Sécurité (faits saillants, code)

- HMAC webhook (`hmac.compare_digest`) + secret `X-Origin-Verify` (WAF→origin) — `webhook-receiver/handler.py`.
- GitHub App (JWT RS256 → token installation ~1h) + repli PAT — `docagent/github_auth.py`.
- Secrets en Secrets Manager, jamais journalisés (`docagent/correlation.py` mask_secrets).
- Moindre privilège : 3 rôles `limited-*` scopés par ARN (webhook / worker / runtime).
- Anti prompt-injection : cible de commit figée `docs/agent/**` (`docagent/paths.py`) ;
  extraction tarball anti-traversal/symlink (`docagent/repo_reader.py`).
- Endpoint API Gateway public mais fronté WAF ; throttling 10 rps / burst 20 ; quota anti-DoS
  par dépôt (`webhook-receiver/handler.py` `_rate_limited`).

## Fiabilité / perf / coût (faits, code)

- Invocation **async** (`agent.py` add_async_task/complete_async_task ; worker non bloquant 60 s).
- Idempotence double niveau (`repo#pr#comment_id` webhook, `repo#pr#sha` agent), PutItem
  conditionnel, **relâche sur échec** (`docagent/idempotency.py`).
- Retries backoff sur transitoire (`docagent/retry.py`, sans jitter) ; écritures non rejouées.
- SQS + DLQ (maxReceiveCount 2), visibility 120 s ; ARM64 partout.
- Modèle Haiku 4.5 défaut / escalade Sonnet 4.6 (>25 fichiers ou >400 Ko) — `analyzer.py`, `agents.json`.
- Caps de lecture 40 fichiers / 80 Ko / 1,2 Mo (`docagent/config.py`). Rétention logs 14 j. DynamoDB on-demand + TTL.
- Mono-région, pas de DR. Tarball chargé en mémoire ; lectures de fichiers séquentielles.

## Observabilité

- Métriques EMF (stdout) ns `AgentTechnicalDoc` : Runs, DurationMs, FilesCommitted (dim. Agent+Outcome) — `docagent/metrics.py`.
- Dashboard `technical-doc-POC-overview` + alarmes (DLQ, erreurs webhook/worker/runtime, stall file, + IAM/Secrets si CloudTrail activé).
- `correlation_id` propagé webhook→worker→runtime.

## Outillage disponible (scanners)

`terraform` ✅, `aws` ✅. **Absents** : tflint, checkov, tfsec, trivy, ruff.
→ S'appuyer sur l'analyse de code + `terraform validate -backend=false`. Ne rien installer.

## Couverture / limites

- **Statique uniquement** : les contrôles vérifiables seulement au runtime (chiffrement effectif,
  alarmes actives, existence réelle du trail org) sont jugés sur l'IaC, pas sur le déployé.
- Le rôle de déploiement ne peut pas lire CloudTrail/GuardDuty (Deny org) → l'existence du trail
  org-wide est une **hypothèse documentée**, non vérifiable ici.
