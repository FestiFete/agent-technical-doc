# Shared Context Pack — agent-technical-doc

Static audit (live_aws = OFF). All evidence must be code/IaC `path:line` or doc URL.
Sub-agents may read deeper into files relevant to their pillar.

## Project

**agent-technical-doc** — agent de documentation technique headless sur AWS Bedrock
AgentCore. Un commentaire `@agent-technical-doc` sur une PR GitHub déclenche : webhook
→ API Gateway → Lambda → SQS → Lambda worker → InvokeAgentRuntime → agent (clone RO →
analyse LLM Bedrock → commit `docs/agent/**` + commentaire). Le LLM est un pur
analyseur (aucun pouvoir d'écriture). Déployé et validé E2E en conditions réelles
(compte 375039967495, eu-central-1) — mais cet audit est **statique** (code/IaC).

## Emplacements clés (target = `documentation/`)

```
documentation/
  README.md, ARCHITECTURE.md, AUDIT.md            # docs projet
  scripts/agents/agents.json                       # config agent (enabled, env, MODEL_ID)
  scripts/agents/agent-technical-doc/
    agent.py                                        # entrypoint BedrockAgentCoreApp (async)
    instructions.md                                 # prompt système (anti prompt-injection)
    Dockerfile                                      # image ARM64
    requirements.txt / requirements-dev.txt
    docagent/                                       # 17 modules logique métier (testable, DI)
      orchestrator.py, github_auth.py, secrets.py, github_client.py, repo_reader.py,
      selection.py, analyzer.py, drawio.py, doc_builder.py, committer.py, comments.py,
      idempotency.py, metrics.py, paths.py, payload.py, retry.py, config.py
    e2e/                                            # local_run.py, smoke_check.py, harness.py
    tests/                                          # 16 fichiers de tests (agent)
  scripts/lambdas/
    webhook-receiver/handler.py                     # HMAC + filtre + authz + dedup + quota + enqueue
    worker-dispatcher/handler.py                    # SQS -> InvokeAgentRuntime
    tests/                                          # test_webhook_receiver.py, test_worker_dispatcher.py
  terraform/                                        # 7 modules (voir map)
.kiro/specs/agent-technical-doc/                    # design.md, requirements.md, tasks.md
```

## Langages & stack

- **Python 3.12** (Lambdas + agent runtime). `docagent` : injection de dépendances,
  imports boto3/strands/pyjwt **différés** (testable sans réseau).
- **Terraform** (>= 1.6, provider aws `~> 6.0`), backend S3.
- Runtime : AWS Bedrock AgentCore (conteneur ARM64), Strands + Bedrock (Claude).
- Dépendances Python : `bedrock-agentcore`, `strands-agents[otel]`, `boto3`,
  `pyjwt[crypto]`, `aws-opentelemetry-distro`, `pytest` (dev).

## Carte des modules Terraform (7)

| Module | Rôle | Dépendances (remote_state) |
|--------|------|----------------------------|
| bootstrap | bucket S3 de state (backend **local**) | — |
| ecr | repository d'images | — |
| security | Secrets Manager (github-token, webhook-hmac) + DynamoDB idempotence | — |
| roles | rôles IAM (runtime execution, `limited-*`) | ecr, security |
| runtime | build/push image ARM64 + AgentCore Runtime + logs | ecr, roles, security |
| ingestion | API GW + λ webhook + SQS/DLQ + λ worker + IAM | security, runtime |
| observability | dashboard + alarmes | ingestion |

Faits IaC vérifiés :
- Backend **S3** dans 6 modules ; bucket **codé en dur** `amzn-agent-technical-doc-statetf-375039967495-eu-central-1` (providers.tf:~11-20) — account id dans le nom.
- **Aucun `dynamodb_table` ni `use_lockfile`** dans les backends → **verrouillage de state non évident** (à vérifier par TF sub-agent).
- `.terraform.lock.hcl` **présent dans les 7 modules**.
- `required_version >= 1.6.0`, aws `~> 6.0` (pinné).
- `default_tags` présents (ecr/security/runtime/ingestion providers.tf).
- Rôles IAM préfixés `limited-` (guardrail org) ; policies inline scopées par ARN.

## Sécurité (faits saillants, code)

- **HMAC** webhook (`hmac.compare_digest`) — `scripts/lambdas/webhook-receiver/handler.py`.
- **GitHub App** (JWT RS256 → token installation ~1h) + repli PAT — `docagent/github_auth.py`.
- **Secrets** en Secrets Manager, jamais journalisés (`docagent/correlation.py` mask_secrets).
- **CMK KMS retirée en POC** (DENY `kms:CreateKey`) → clés gérées AWS. Evidence :
  `terraform/security/main.tf` (commentaires "kms_key_id retiré").
- **Pas de WAF** devant l'API Gateway.
- Moindre privilège : λ webhook (GetSecret hmac, PutItem/UpdateItem, SendMessage) ;
  λ worker (SQS + InvokeAgentRuntime scopé ARN) ; runtime (InvokeModel, GetSecret token,
  DynamoDB, ECR, logs, EMF).
- Anti prompt-injection : cible de commit figée `docs/agent/**` (`docagent/paths.py`
  normalize_output_path) ; extraction tarball anti-traversal/symlink (`docagent/repo_reader.py`).
- Endpoint API Gateway **public**, throttling 10 rps / burst 20 ; quota anti-DoS par
  dépôt (`webhook-receiver/handler.py` `_rate_limited`).

## Fiabilité / perf / coût (faits, code)

- **Async** : entrypoint `add_async_task`/`complete_async_task` (`agent.py`), worker
  non bloquant (timeout 60 s).
- **Idempotence** double niveau : `repo#pr#comment_id` (webhook), `repo#pr#sha` (agent),
  `PutItem` conditionnel ; **relâche sur échec** (`docagent/idempotency.py` release).
- **Retries backoff** sur transitoire (`docagent/retry.py`) : Bedrock + lectures GitHub GET ;
  écritures non rejouées. Worker : classif. transitoire→retry SQS / permanent→drop.
- **SQS + DLQ** (maxReceiveCount 2), visibility 120 s.
- **ARM64** partout (Lambdas + image runtime).
- **Modèle** : Haiku 4.5 par défaut, escalade Sonnet 4.6 (>25 fichiers ou >400 Ko) —
  `docagent/analyzer.py` select_model, `agents.json`.
- **Caps de lecture** : 40 fichiers / 80 Ko / 1,2 Mo (`docagent/config.py`).
- **Rétention logs** : 14 j. DynamoDB **on-demand** + TTL.
- **Mono-région**, pas de DR. Runtime : idle 900 s, max_lifetime 3600 s.
- Tarball chargé **en mémoire** ; lectures de fichiers **séquentielles** (`_build_repo_context`).

## Observabilité

- Métriques **EMF** (stdout) ns `AgentTechnicalDoc` : Runs, DurationMs, FilesCommitted
  (dim. Agent+Outcome) — `docagent/metrics.py`.
- Dashboard `technical-doc-POC-overview` + alarmes (DLQ, erreurs webhook/worker/runtime)
  — `terraform/observability/`.
- `correlation_id` propagé sur les 3 composants (webhook→worker→runtime).

## CI/CD

- **Aucun pipeline** : pas de `.github/workflows`, pas de CodeBuild/Pipeline. Déploiement
  Terraform manuel, multi-module ordonné. Secrets posés à la main (`put-secret-value`).

## Tests

- **127 tests** : 107 agent (16 fichiers, dont test_agent, test_retry, test_github_auth,
  test_orchestrator, test_harness…) + 20 lambdas. Sans réseau (injection de dépendances).
  2 skips intentionnels (RS256 sans crypto, E2E sans stack). Harnais E2E (dry-run +
  événement synthétique signé). **Pas de couverture mesurée**, pas de gate CI.

## Outillage disponible (pour scanners)

`terraform` ✅, `aws` ✅. **Absents** : tflint, checkov, tfsec, trivy, ruff.
→ S'appuyer sur l'analyse de code + `terraform validate` (`-backend=false`). Ne rien installer.

## Couverture / limites

- **Statique uniquement** (pas d'appels AWS live). Les contrôles vérifiables uniquement
  au runtime (état réel des ressources, chiffrement effectif, alarmes actives) sont
  jugés sur l'IaC, pas sur le déployé.
- Le projet a été déployé/validé E2E durant le développement, mais cet audit ne
  s'appuie que sur le code/IaC.


## CORRECTION / REFRESH (post-dispatch ground-truth, authoritative)

The initial inventory (built from session memory) was **stale**. Verified against the
current committed IaC (`find *.tf` + targeted grep):

- **WAF PRESENT** — `terraform/ingestion/waf.tf` exists: CloudFront distribution +
  WAFv2 WebACL (Core Rule Set, Known Bad Inputs, rate-based, body-size) fronting the
  HTTP API, with an `X-Origin-Verify` shared secret checked by the webhook Lambda
  **before** HMAC. → The earlier "no WAF / public API" Critical is **REMEDIATED**.
- **CloudTrail PRESENT** — `terraform/observability/cloudtrail.tf` exists (multi-region
  trail + S3 with lifecycle expiration). → Detective controls are **Partial**, not
  absent. (Note: the Security sub-agent scored SEC-10 "Missing"/SEC-F2 without seeing
  this file — reconcile in aggregation: CloudTrail present; GuardDuty/Config/Security
  Hub still not evidenced.)
- **Still ABSENT (verified, no matches):** `aws_sns_topic` (so `alarm_actions` default
  `[]` → alarms have no notification target), `aws_budgets_budget` / cost anomaly,
  `ReportBatchItemFailures` on the SQS event source mapping, and any main-queue
  `ApproximateAgeOfOldestMessage` alarm. → Reliability REL-F1/REL-F2 and Cost COST-F1
  gaps are evidence-grounded.
- CMK: `security/main.tf` still uses AWS-managed keys (CMK removed for POC).

Sub-agents for pillars 07–12 should treat WAF + CloudTrail as PRESENT.
