# Context Pack — agent-technical-doc

Target: `/Users/g.mirambeau/Development/AWS/agent-technical-doc` (repo root). Mode: static-only (`live_aws=OFF`). Branch: `develop` (1 commit ahead of `origin/develop`), with one **uncommitted** working-tree change (see below).

## 1. Tree overview

Monorepo-lite, single product ("agent-technical-doc"), designed to be extractable to its own repo. Root contains near-empty legacy stub dirs (`./terraform/`, `./scripts/` — DS_Store only, no real files) alongside the real project under `documentation/`:

```
documentation/
├── ARCHITECTURE.md, README.md, AUDIT.md (prior self-audit doc), .gitignore
├── scripts/
│   ├── agents/
│   │   ├── agents.json                       # discovery + env config, single agent entry
│   │   └── agent-technical-doc/
│   │       ├── agent.py                      # BedrockAgentCoreApp entrypoint (async)
│   │       ├── instructions.md                # hardened system prompt (anti prompt-injection)
│   │       ├── Dockerfile                     # python:3.11-slim, arm64, opentelemetry-instrument
│   │       ├── requirements.txt / requirements-dev.txt
│   │       ├── docagent/                      # 15 modules: analyzer, comments, committer, config,
│   │       │                                    correlation, doc_builder, drawio, github_auth,
│   │       │                                    github_client, idempotency, metrics, orchestrator,
│   │       │                                    paths, payload, repo_reader, retry, secrets, selection
│   │       ├── e2e/                            # local_run.py, smoke_check.py, harness.py, README.md
│   │       └── tests/                          # 15 test files (pytest, no-network unit/integration)
│   └── lambdas/
│       ├── webhook-receiver/handler.py + requirements.txt
│       ├── worker-dispatcher/handler.py + requirements.txt
│       └── tests/ (2 files)
└── terraform/
    ├── shared.tfvars
    ├── bootstrap/ (S3 state bucket, local backend)
    ├── ecr/ (S3 backend)
    ├── security/ (S3 backend)
    ├── roles/ (S3 backend)
    ├── runtime/ (S3 backend)
    ├── ingestion/ (S3 backend)
    └── observability/ (S3 backend)
```

`.kiro/specs/agent-technical-doc/` holds `requirements.md`, `design.md`, `tasks.md` (spec-driven dev artifacts, not code).

## 2. Languages & frameworks

- **Python 3.11/3.12** — agent runtime (3.11-slim base image) + Lambdas (python3.12 runtime declared in Terraform — note version mismatch to check).
- App deps: `bedrock-agentcore`, `strands-agents[otel]`, `boto3`/`botocore`, `pyjwt[crypto]` (GitHub App RS256 auth), `aws-opentelemetry-distro`. Dev: `pytest`.
- Lambdas: no third-party deps (boto3 provided by Lambda runtime).
- **Terraform** ≥ 1.6 required per README; providers: `hashicorp/aws ~> 6.0`, `awscc` (runtime module only), `archive`, `terraform` (remote state).

## 3. IaC — Terraform module map

7 modules, each with its own **S3 backend** (bucket `amzn-agent-technical-doc-statetf-375039967495-eu-central-1`, region `eu-central-1`), chained via `terraform_remote_state` data sources. Deploy order (per README): `bootstrap → ecr → security → roles → runtime → ingestion → observability`.

| Module | Key resources | Backend | Cross-refs |
|---|---|---|---|
| `bootstrap` | S3 state bucket + versioning + SSE + public-access-block | local (chicken/egg) | — |
| `ecr` | ECR repo + lifecycle policy | S3 | — |
| `security` | Secrets Manager (`github_token`, `webhook_hmac`), DynamoDB `idempotency` table | S3 | — |
| `roles` | IAM role `runtime_execution` + inline policy | S3 | reads `ecr`, `security` remote state |
| `runtime` | `awscc_bedrockagentcore_runtime`, ECR image validation (`null_resource`+`terraform_data`), CW log group, `awscc_logs_delivery*` (app/usage logs), error metric filter + alarm | S3 | reads `ecr`, `roles`, `security` |
| `ingestion` | SQS `main`+`dlq` (SSE-SQS), IAM roles `webhook`/`worker` (inline policies), CW log groups, Lambda `webhook`+`worker`, event source mapping (SQS→worker), API Gateway HTTP API + integration + route + `$default` stage (throttle 20 burst/10 rps) + Lambda permission | S3 | reads `security`, `runtime` |
| `observability` | CW alarms (`dlq_not_empty`, `worker_errors`, `webhook_errors`), CW dashboard | S3 | reads `ingestion` |

`.terraform.lock.hcl` present per module. No `tfvars` committed except `shared.tfvars` and `ingestion/terraform.tfvars` (allowlist config — contents not dumped here; treat as config, not secret, but not fully inventoried).

**Uncommitted working-tree change** (`git diff`, not yet committed): `documentation/terraform/ingestion/main.tf` — worker IAM policy `ConsumeQueue` statement had `sqs:GetQueueAttributes` removed, narrowing to `sqs:ReceiveMessage`/`sqs:DeleteMessage` only. Recent commits (already committed) show a pattern of least-privilege tightening: `SEC-01` (scoped DynamoDB query on webhook role), `SEC-02` (SQS `Condition` on `SendMessage`), `SEC-03` (removed a wildcard on a `/runtime-endpoint/*` resource). Pillars should evaluate the **current on-disk state** (working tree), which includes this uncommitted diff.

## 4. Entry points & runtime

- **Trigger**: GitHub PR comment `@agent-technical-doc ...` → API Gateway HTTP API (public HTTPS) → Lambda `webhook` (HMAC verify via `X-Hub-Signature-256`, mention/allowlist/author-association filter, anti-DoS rate quota, idempotency claim) → SQS → Lambda `worker` (async `InvokeAgentRuntime`, ARN-scoped) → Bedrock AgentCore Runtime (isolated session): GitHub App auth (JWT RS256 → short-lived installation token, PAT fallback), shallow clone (read-only), bounded file selection, LLM analysis (Haiku default / Sonnet escalation for large repos), Markdown + `.drawio` (C4 Context/Container/Component, Sequence, ER) rendering, single commit to `docs/agent/**` on the PR's head branch, summary PR comment.
- Container: ARM64, `opentelemetry-instrument python agent.py` entrypoint, `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS=requests,urllib3`.

## 5. CI/CD

**None found.** No `.github/workflows/`, no GitLab CI, no CodeBuild/CodePipeline definitions in-repo. Deployment is manual per README (`terraform init && apply` per module, in order, from local machine). E2E "Phase 4 — industrialisation CI" explicitly marked "⏳ à faire" in `documentation/README.md`.

## 6. Config & secrets handling

- Secrets (names only, never values): `technical-doc-POC-github-token` (GitHub App app_id/installation_id/private_key JSON, or PAT fallback `{"token":...}`), `technical-doc-POC-webhook-hmac` (HMAC signing secret). Both in Secrets Manager, set post-`terraform apply` via `aws secretsmanager put-secret-value` (out of Terraform state).
- Encryption at rest: AWS-managed keys only (`aws/secretsmanager`, SSE-SQS, DynamoDB/CW default). README explicitly flags: **"CMK KMS à rétablir avant une prod à forts enjeux"** — a stated POC compromise, not an oversight.
- Env-var config: `documentation/scripts/agents/agents.json` (model IDs, size/file limits, mention handle, output dir — no secrets); Lambda env vars set from Terraform vars (allowlists, quotas) — no secret values in Lambda env.
- `.gitignore` excludes `.terraform/`, `*.tfstate*`, `terraform/**/build/`, Python caches, `.venv/`.

## 7. Docs

- `documentation/README.md` — deployment/runbook/security summary (French).
- `documentation/ARCHITECTURE.md` — detailed diagrams (not fully read by orchestrator; pillar agents should read directly).
- `documentation/AUDIT.md` — a **prior self-authored audit note** referenced by README (quality/security/perf/scalability/cost/WAF, "reste à faire"). Treat as claims to verify against code, not as ground truth.
- `.kiro/specs/agent-technical-doc/{requirements,design,tasks}.md` — spec-driven design docs; `design.md` reportedly contains a Well-Architected analysis per README.
- Prior orchestrator-run audit exists at `audit/20260720-000000/` (this run's predecessor — global score 77/100, maturity 4/5, no capping; Critical finding `SEC-F1` on public entrypoint w/o WAF+CMK). Pillar agents may reference it for delta context but MUST independently re-verify all findings against current code — do not carry forward unverified claims.

## 8. Tool availability probe

| Tool | Available |
|---|---|
| `terraform` | ✅ (`/opt/homebrew/bin/terraform`) |
| `aws` CLI | ✅ (`/opt/homebrew/bin/aws`) — but `live_aws=OFF` this run, so not used for live calls |
| `tflint` | ❌ not found |
| `checkov` | ❌ not found |
| `tfsec` / `trivy` | ❌ not found |
| Python linters (ruff/flake8/black configured in-repo) | not detected in manifests — none configured |

`AWS_PROFILE` / `AWS_REGION` env vars: unset.

## 9. Cheap scans run once (raw output in `_context/scans/`)

- `terraform fmt -check -recursive -diff` over `documentation/terraform/` → **1 file misformatted**: `ingestion/main.tf` (alignment-only diff on the `RateLimitQuery` and `InvokeRuntimeScoped` IAM statement blocks — cosmetic, not functional). Full diff saved to `_context/scans/terraform-fmt.txt`.
- `terraform validate` was **not** run (would require `init -backend=false` per module across 7 modules with S3 backends/remote-state chaining; skipped for time — note as a coverage limitation, not a finding).

## 10. What sub-agents should NOT re-do

Do not re-walk the full repo tree or re-run `terraform fmt` — reuse the facts above. Pillar agents SHOULD read specific files deeply relevant to their pillar (e.g. Security reads IAM policy JSON bodies in `ingestion/main.tf`/`roles/main.tf`, Lambda handler code for input validation; Reliability reads DLQ/retry/idempotency code in `docagent/retry.py`, `docagent/idempotency.py`).
