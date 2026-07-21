# Operational Excellence — Audit

**Score:** 57/100  **Maturity:** 3 (Defined)  **Coverage:** 95%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Assesses the ability to run, monitor, and continuously improve the workload: observability (logs/metrics/tracing), deployment/release safety, automation of operations, incident response, and operational feedback loops.

Does **not** cover: long-term code changeability (→ Maintainability, pillar 12), failure tolerance / RTO-RPO / multi-AZ (→ Reliability, pillar 03), or Terraform structure/conventions as such (→ Terraform, pillar 08). Findings here are cross-referenced by id where they overlap those pillars, not double-scored.

## Strengths
- End-to-end `correlation_id` (= GitHub `X-GitHub-Delivery`) threaded through webhook → SQS → worker → runtime, explicitly documented as the tracing mechanism in the runbook — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:1-23`, `documentation/scripts/lambdas/webhook-receiver/handler.py:220-264`, `documentation/README.md:192-194`_
- EMF (Embedded Metric Format) metrics emitted from the runtime with duration, outcome and `correlation_id`, auto-extracted by CloudWatch without extra IAM — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/metrics.py:1-49`_
- Secret masking helper applied before logging (GitHub PATs, `Authorization`/`X-Hub-Signature-256` headers) — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:27-49`_
- Centralized CloudWatch Log Groups for all three components with bounded retention — _evidence: `documentation/terraform/ingestion/main.tf:158-166`, `documentation/terraform/runtime/logs.tf:3-10`_
- Aggregated CloudWatch dashboard covering Lambda invocations/errors, SQS queue vs DLQ depth, run duration and outcome — _evidence: `documentation/terraform/observability/main.tf:75-163`_
- Health check pattern explicit and documented: `BedrockAgentCoreApp` `/ping` liveness, heavy work deliberately run off the request thread so it never blocks `/ping` — _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:24-32,80,93`_
- Written runbook covering the most likely operational tasks: DLQ triage/redrive, run tracing, secret rotation, allowlist/quota tuning, dedup troubleshooting — _evidence: `documentation/README.md:186-204`_
- 100% infra-as-code: 7 chained Terraform modules (`bootstrap→ecr→security→roles→runtime→ingestion→observability`), no undocumented resources found — _evidence: `documentation/terraform/*/main.tf` (module map), context pack §3_
- Runtime container auto-instrumented with OpenTelemetry (`aws-opentelemetry-distro`, `opentelemetry-instrument` entrypoint) — _evidence: `documentation/scripts/agents/agent-technical-doc/Dockerfile:16-17`, `requirements.txt` (`strands-agents[otel]`, `aws-opentelemetry-distro`)_

## Weaknesses / Findings

### [High] OPS-F1 — No CI/CD pipeline; fully manual deployment
- **Evidence:** No `.github/workflows/` anywhere in the repo (checked at repo root and under `documentation/`); `documentation/README.md:78-95` documents a manual `terraform init && apply` loop run from a local machine, in strict module order; `documentation/README.md:159` explicitly flags `**Phase 4 — industrialisation CI : ⏳ à faire**`.
- **Impact:** Every deploy depends on an individual operator running the right commands in the right order from a correctly configured local machine; no automated build/test/plan/apply gate; nothing prevents an unreviewed or untested change reaching the `runtime` image or Terraform state.
- **Recommendation:** Add a minimal GitHub Actions pipeline: on PR, run `terraform fmt -check`, `terraform validate` per module, and `pytest` for `docagent`/Lambdas; on merge to `main`/`develop`, require manual approval before `terraform apply` per module (or per environment once one exists — see OPS-F3).
- **Alternative solution:** Use GitHub Actions with OIDC federation to an AWS deploy role instead of long-lived AWS keys. Pros: closes the "manual laptop deploy" gap cheaply, reuses the GitHub-centric workflow the project already has (its trigger surface is GitHub PRs). Cons: initial setup effort, requires a scoped deploy IAM role (touches Security pillar), and Terraform's chained `terraform_remote_state` across 7 modules needs sequencing logic in the pipeline. Effort: M. Cross-pillar: Security (deploy credentials), Terraform (plan/validate gating), Maintainability (release process).

### [High] OPS-F2 — Alarms exist but no notification target is wired by default
- **Evidence:** `documentation/terraform/observability/variables.tf:21-25` — `alarm_actions` is `list(string)`, description "ARNs SNS notifiés par les alarmes (**vide = pas de notification**)", `default = []`; no `aws_sns_topic` resource exists anywhere in the repo (`grep -rl aws_sns_topic documentation/terraform` → no matches); neither `shared.tfvars` nor `ingestion/terraform.tfvars` sets `alarm_actions`.
- **Impact:** The alarms themselves are well-designed and tied to real SLIs (DLQ depth, Lambda error counts, runtime error rate — `documentation/terraform/observability/main.tf:24-70`, `documentation/terraform/runtime/logs.tf:79-94`), but as shipped they fire into the void: nobody is notified unless an operator manually supplies an SNS ARN at `apply` time, which is undocumented in the runbook.
- **Recommendation:** Provision an SNS topic (+ at least an email/Slack subscription) in the `observability` module and default `alarm_actions` to it, or explicitly document in the runbook that `alarm_actions` must be set before relying on these alarms operationally.
- **Alternative solution:** Minimal SNS topic + email subscription created in Terraform, topic ARN passed as `alarm_actions` by default. Pros: closes a silent-alarm gap with an S-effort change, no new AWS service. Cons: still requires a real on-call rotation/process outside Terraform to act on the notification. Effort: S. Cross-pillar: Reliability (incident response readiness).

### [Medium] OPS-F3 — No environment parity; single hardcoded "POC" environment
- **Evidence:** `documentation/terraform/shared.tfvars:18` — `environment = "POC"` is the only environment value defined anywhere; `shared.tfvars:4-6` explicitly notes backend `key`/`bucket` in each `providers.tf` "ne peuvent pas utiliser de variables" (cannot use variables), e.g. `documentation/terraform/ingestion/providers.tf:15-20` hardcodes `key = "ingestion/terraform.tfstate"`.
- **Impact:** There is no dev/stage/prod split and no mechanism to safely test infra or app changes in an isolated environment before they hit the only state that exists — the backend key is not parameterized per environment, so standing up a second environment requires manually editing every module's `providers.tf`.
- **Recommendation:** Parameterize backend keys (e.g. via `-backend-config` per environment as the comment itself suggests) and introduce at least a "staging" environment for the ingestion path before treating this as beyond-POC.
- **Alternative solution:** None better than proper multi-env Terraform workspaces/backend-config — the project already anticipates this in its own comments, it's a matter of executing it. Effort: M. Cross-pillar: Terraform (backend structure).

### [Medium] OPS-F4 — Automated tests are not a release gate
- **Evidence:** Substantial pytest suite exists (`documentation/scripts/agents/agent-technical-doc/tests/` — 15 files; `documentation/scripts/lambdas/tests/` — 2 files), and `documentation/README.md:134-144` documents how to run them, but nothing in the repo enforces them before a deploy (no CI — see OPS-F1) and the runbook does not state "tests must pass before `terraform apply`".
- **Impact:** A broken build/regression can be deployed as long as the operator forgets or skips the manual test step.
- **Recommendation:** Wire the existing test suite into the CI pipeline proposed in OPS-F1 as a blocking check.
- **Alternative solution:** Covered by OPS-F1's alternative; no separate solution needed. Effort: S (once CI exists). Cross-pillar: none beyond OPS-F1.

### [Medium] OPS-F6 — No distributed tracing across the Lambda hops; correlation id only
- **Evidence:** No `tracing_config` block on either `aws_lambda_function` resource in `documentation/terraform/ingestion/main.tf:171-217` (checked via grep for `tracing_config`/`active_tracing`/`xray` — no matches in that file); OpenTelemetry auto-instrumentation is present only in the runtime container (`documentation/scripts/agents/agent-technical-doc/Dockerfile:16-17`), not in the ingestion Lambdas.
- **Impact:** Cross-component causal/latency analysis (webhook → SQS → worker → runtime) depends on manually grepping a shared `correlation_id` across three separate log groups rather than a queryable trace with span timing; acceptable for a low-volume POC but doesn't scale operationally.
- **Recommendation:** Enable AWS X-Ray active tracing on both Lambda functions (`tracing_config { mode = "Active" }`), which is a one-line-per-function Terraform change and integrates with the existing correlation id via X-Ray's trace header.
- **Alternative solution:** X-Ray active tracing (managed, near-zero setup) vs. extending OTel to the Lambdas via an ADOT layer (more consistent with the runtime's existing OTel stack but heavier to set up on Lambda). Recommend X-Ray for effort reasons. Effort: S. Cross-pillar: none.

### [Low] OPS-F5 — API Gateway stage has no access logging configured
- **Evidence:** `documentation/terraform/ingestion/main.tf:252-261` — `aws_apigatewayv2_stage.default` has no `access_log_settings` block.
- **Impact:** HTTP-level request logs (source IP, path, status, latency) at the API Gateway layer are not captured independently of what the Lambda itself logs; makes edge-level troubleshooting (e.g. malformed requests rejected before reaching the Lambda) harder.
- **Recommendation:** Add an `access_log_settings` block pointing at a dedicated CloudWatch Log Group with a JSON log format including `requestId`, `sourceIp`, `status`, `integrationLatency`.
- **Alternative solution:** None better — this is the standard mechanism. Effort: S.

### [Low] OPS-F7 — No post-incident / feedback loop mechanism defined
- **Evidence:** No mention of SLI/SLO, error budget, retro, or post-mortem process in `documentation/README.md`, `documentation/ARCHITECTURE.md`, or the runbook section (`README.md:186-204`) — searched and not found.
- **Impact:** No structured mechanism to turn DLQ incidents or alarm firings into process improvements beyond ad hoc runbook execution.
- **Recommendation:** For a POC this is a reasonable gap; before broader rollout, define even a lightweight incident log (what triggered, what was done, follow-up action) tied to the DLQ/alarm runbook steps that already exist.
- **Alternative solution:** None — appropriate to defer at POC stage; flag as a pre-prod checklist item.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| OPS-01 | Infrastructure & operations defined as code (no manual console drift). | Met | `documentation/terraform/*/main.tf` (7 modules); secret *values* set out-of-band via `aws secretsmanager put-secret-value` but this is documented/expected (`README.md:105-116`), not undocumented drift |
| OPS-02 | CI/CD pipeline exists with automated build/test/deploy stages. | Missing | No `.github/workflows/`; `documentation/README.md:78-95,159` (manual deploy, "Phase 4 CI: à faire") |
| OPS-03 | Deployments are small, reversible; rollback strategy defined. | Partial | ECR digest pinning + retention of last N tagged images (`documentation/terraform/ecr/main.tf:22-51`, `documentation/terraform/runtime/main.tf:11-15`) enables manual rollback via re-apply, but no documented rollback procedure in the runbook (`README.md:186-204`) and deploys are multi-module chained applies, not small increments |
| OPS-04 | Structured, centralized logging (correlation ids, no secrets in logs). | Met | `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:1-49`, `documentation/scripts/lambdas/webhook-receiver/handler.py:220-264`, `documentation/terraform/ingestion/main.tf:158-166`, `documentation/terraform/runtime/logs.tf:3-10`; gap: no API Gateway access logs (OPS-F5) |
| OPS-05 | Metrics on the golden signals (latency, traffic, errors, saturation). | Partial | Latency/traffic/errors well covered (`documentation/terraform/observability/main.tf:86-160`, `documentation/scripts/agents/agent-technical-doc/docagent/metrics.py`); saturation only weakly represented (queue depth dashboarded but not alarmed, no Lambda concurrency saturation metric/alarm) |
| OPS-06 | Distributed tracing / request correlation where relevant. | Partial | Correlation id across all 3 components (`correlation.py`, `README.md:192-194`) + OTel auto-instrumentation in runtime container (`Dockerfile:16-17`), but no X-Ray/OTel tracing on the ingestion Lambdas (`documentation/terraform/ingestion/main.tf:171-217` — no `tracing_config`) |
| OPS-07 | Actionable alarms tied to SLIs; on-call/notification path defined. | Partial | Alarms tied to real SLIs (`documentation/terraform/observability/main.tf:24-70`, `documentation/terraform/runtime/logs.tf:79-94`), but `alarm_actions` defaults to `[]` and no SNS topic exists in-repo (`documentation/terraform/observability/variables.tf:21-25`) — see OPS-F2 |
| OPS-08 | Runbooks / operational docs for common tasks & incidents. | Met | `documentation/README.md:186-204` (DLQ triage, run tracing, secret rotation, allowlist/quota tuning, dedup troubleshooting) |
| OPS-09 | Health checks & readiness/liveness for services. | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:24-32,80,93` (`/ping` HealthyBusy pattern, explicitly non-blocking) |
| OPS-10 | Config management & environment parity (dev/stage/prod). | Missing | Single `environment = "POC"` (`documentation/terraform/shared.tfvars:18`); backend keys hardcoded per module, not parameterized for multi-env (`shared.tfvars:4-6`, `documentation/terraform/ingestion/providers.tf:15-20`) — see OPS-F3 |
| OPS-11 | Automated tests as a release gate (unit/integration). | Partial | 15+ test files exist and are documented (`documentation/README.md:134-144`, `documentation/scripts/agents/agent-technical-doc/tests/`, `documentation/scripts/lambdas/tests/`), but nothing enforces them pre-deploy (no CI) — see OPS-F4 |
| OPS-12 | Post-incident/feedback mechanism (retros, error budgets). | Missing | No SLI/SLO/retro/post-mortem process found in README/ARCHITECTURE/runbook — see OPS-F7 |
| OPS-13 | Tagging strategy enabling operational ownership. | Met | `default_tags { Project, Env, Module }` in most providers (e.g. `documentation/terraform/ingestion/providers.tf:25-31`); intentionally absent in `security` module with a documented reason (`documentation/terraform/security/providers.tf:22-24` — role lacks `kms:TagResource`) |
| OPS-14 | Dashboards for operational visibility. | Met | `documentation/terraform/observability/main.tf:75-163` (6-widget CloudWatch dashboard: invocations, errors, queue/DLQ depth, EMF duration, runtime errors, outcome counts) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Stand up a minimal CI pipeline (fmt/validate/pytest on PR, gated apply on merge) — closes OPS-F1 and OPS-F4 together | M |
| P1 | Create an SNS topic + subscription and wire it as the default `alarm_actions` (or document the requirement loudly) — OPS-F2 | S |
| P2 | Enable X-Ray active tracing on the webhook/worker Lambdas — OPS-F6 | S |
| P2 | Parameterize Terraform backend per environment and stand up a staging environment — OPS-F3 | M |
| P3 | Add `access_log_settings` to the API Gateway `$default` stage — OPS-F5 | S |
| P3 | Document an explicit rollback procedure in the runbook (revert to prior ECR digest / prior Terraform state) — OPS-03 | S |
| P4 | Define a lightweight post-incident log tied to existing DLQ/alarm runbook steps before broader rollout — OPS-F7 | S |

## Notes & assumptions
- Static analysis only; `live_aws=OFF`, no AWS API calls made, no confirmation that alarms/dashboards actually exist as deployed vs. as defined in Terraform (state not inspected).
- `terraform validate` was not run (context pack limitation, not re-run here); only `terraform fmt -check` results from the context pack were reused (cosmetic-only diff in `ingestion/main.tf`, not scored here as it is a Terraform-pillar (08) concern).
- Assessed the current on-disk working tree, including the uncommitted IAM tightening in `documentation/terraform/ingestion/main.tf` (worker policy narrowed to `ReceiveMessage`/`DeleteMessage`) per the context pack instruction — this specific change is Security-pillar territory and not re-scored here.
- Did not re-verify every one of the 15+ Python test files' content line-by-line; confirmed their existence and README's documented test-running procedure as sufficient evidence for OPS-11's "tests exist" half.
- Prior pillar-run score for this same pillar (20260720-000000, 82/100) was treated as an unverified claim per instructions, not carried forward; this run's independent re-scoring (57/100) differs materially, primarily because that prior run's treatment of OPS-02/OPS-07/OPS-10 was not re-derivable from the evidence found here.
