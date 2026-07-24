# Operational Excellence — Audit

**Score:** 71/100  **Maturity:** 3 (Defined)  **Coverage:** 95%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Assesses the ability to run, monitor and continuously improve the workload:
operations-as-code, deployment/release safety, observability (logs/metrics/alarms/
dashboards), request correlation, runbooks, config management and operational
feedback. Grounded in the AWS Well-Architected Operational Excellence pillar
([wellarchitected/latest/userguide/waf.html](https://docs.aws.amazon.com/wellarchitected/latest/userguide/waf.html)).

Does **not** cover: long-term code changeability (→ Maintainability 12), failure
tolerance / RTO-RPO / multi-AZ (→ Reliability 03), or Terraform structural
conventions (→ Terraform 08). Idempotence/retry/DLQ mechanics are scored in
Reliability; here they are only cited as they support reversible operations.

This is a **static** audit (no live AWS). Runtime-only facts (alarms actually
firing, SNS wiring, dashboards rendered) are judged from IaC, not the deployed
account.

## Strengths
- Whole infrastructure defined as Terraform (7 modules); `terraform fmt -check -recursive` passes clean — _evidence: `documentation/terraform/` (bootstrap/ecr/security/roles/runtime/ingestion/observability), fmt exit 0_
- End-to-end request correlation: `correlation_id` (= `X-GitHub-Delivery`) propagated webhook → SQS → worker (`runtimeSessionId`) → runtime — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:15`, `documentation/scripts/lambdas/worker-dispatcher/handler.py:44`_
- Secret masking before logging (defense in depth) — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:36` (`mask_secrets`)_
- Centralized CloudWatch logging with explicit retention for all three components + AgentCore log delivery pipeline — _evidence: `documentation/terraform/ingestion/main.tf:174`, `documentation/terraform/runtime/logs.tf:3`_
- EMF business metrics (Runs / DurationMs / FilesCommitted, dims Agent+Outcome) with no extra IAM — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/metrics.py:19`_
- Operational dashboard aggregating Lambda/SQS/EMF/runtime signals — _evidence: `documentation/terraform/observability/main.tf:79` (`aws_cloudwatch_dashboard.main`)_
- Explicit runbook (DLQ redrive, run tracing, credential rotation, quota, fork/dup) — _evidence: `documentation/README.md` "Runbook (exploitation)"_
- Consistent ownership tagging via `default_tags` (Project/Env/Module) — _evidence: `documentation/terraform/ingestion/providers.tf:29`_

## Weaknesses / Findings

### [High] OPS-F1 — No CI/CD pipeline; deployment and test-gating are manual
- **Evidence:** no `.github/workflows`, no buildspec/pipeline found in the repo; manual multi-module apply loop in `documentation/README.md` ("Déploiement (ordre)"); E2E "Phase 4 — industrialisation CI : ⏳ à faire" in `documentation/README.md` Tests section.
- **Impact:** deploys depend on operator discipline and ordered manual `terraform apply`; the 127 tests never run as an enforced gate, so regressions can reach the runtime image / Lambdas undetected. Higher change-failure risk and slower, less repeatable releases.
- **Recommendation:** add a pipeline that runs `pytest` (agent + lambdas) and `terraform fmt/validate` on PR, then gates image build/push and per-module apply.
- **Alternative solution:** GitHub Actions (native to the GitHub-centric workflow, OIDC to AWS, no infra to run) vs AWS CodePipeline + CodeBuild (stays in-account, integrates with ECR/Bedrock). Pros of Actions: zero AWS ops surface, cheap, fast to stand up. Cons: cross-account OIDC trust to manage. Effort: M. Cross-pillar impact: reliability +, maintainability +, security +/- (CI credentials to scope).

### [Medium] OPS-F2 — Alarms defined but no notification/on-call path by default
- **Evidence:** `documentation/terraform/observability/variables.tf` `alarm_actions` default `[]` ("vide = pas de notification"); alarms reference `var.alarm_actions` (`documentation/terraform/observability/main.tf:38`, `:56`, `:73`).
- **Impact:** DLQ / Lambda-error / runtime-error / IAM-change / secrets-spike alarms can transition to ALARM without notifying anyone; incidents are detected only by someone opening the dashboard.
- **Recommendation:** provision an SNS topic (email/chatops/PagerDuty) and pass its ARN as `alarm_actions` in `shared.tfvars`, at least for DLQ and error alarms.
- **Alternative solution:** SNS → email/Slack (simple, cheap) vs SNS → AWS Chatbot/Incident Manager (on-call rotation, escalation). Pros of Incident Manager: real on-call. Cons: more setup/cost. Effort: S. Cross-pillar impact: reliability +.

### [Medium] OPS-F3 — No explicit rollback / version strategy for runtime deploys
- **Evidence:** runtime image built/pushed and AgentCore runtime replaced in place (`documentation/README.md` "runtime construit et pousse l'image Docker … puis crée le runtime"); no image tag pinning/blue-green/canary or documented rollback procedure in the runbook.
- **Impact:** a bad image or Terraform change is corrected only by re-applying a previous version manually; no fast, defined rollback. Blast radius is bounded per-module (mitigating factor).
- **Recommendation:** pin/immutable-tag images, keep the previous tag, and document a one-command rollback (redeploy prior tag) in the runbook.
- **Alternative solution:** immutable image tags + manual pin rollback (simple) vs AgentCore/Lambda versioned aliases with weighted shift (safer, more moving parts). Effort: M. Cross-pillar impact: reliability +.

### [Low] OPS-F4 — No operational feedback loop (retros / error budgets / SLIs-SLOs)
- **Evidence:** no SLO/SLI/error-budget/retro/post-incident material found in `documentation/` or `.kiro/specs/agent-technical-doc/` (grep: no matches).
- **Impact:** alarms are threshold-based (e.g. errors > 3) but not tied to service-level objectives; no structured learning-from-failure process.
- **Recommendation:** define a minimal SLI (run success rate, p90 DurationMs) + target, and a lightweight post-incident note template.
- **Alternative solution:** None strictly required at POC scale — document objectives when moving toward production; current threshold alarms are acceptable for a POC.

### [Low] OPS-F5 — Single environment; no dev/stage/prod parity
- **Evidence:** one `environment` value ("POC") wired through modules (`documentation/terraform/observability/variables.tf` `environment`; `documentation/scripts/agents/agents.json` env block); no separate stage/prod stacks; state bucket hardcoded with account id (`documentation/terraform/ingestion/providers.tf:19`).
- **Impact:** no pre-prod to validate changes; parity relies on config being env-driven (which it is), but there is nowhere to exercise it.
- **Recommendation:** parametrize the backend (`-backend-config`) and introduce a workspace/tfvars-per-env layout when promoting beyond POC.
- **Alternative solution:** None mandatory at POC; config is already externalized (`docagent/config.py` reads all knobs from env), which is the important foundation.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| OPS-01 | Infra & ops as code (no console drift) | Met | `documentation/terraform/` 7 modules; `terraform fmt -check -recursive` exit 0; secret *values* legitimately set out-of-band (`README.md` post-deploy) |
| OPS-02 | CI/CD with automated build/test/deploy | Missing | no workflows/buildspec; manual apply loop `README.md`; E2E CI "à faire" |
| OPS-03 | Small, reversible deploys; rollback defined | Partial | per-module TF + idempotence release + DLQ redrive (`README.md` Runbook), but no image versioning/rollback (OPS-F3) |
| OPS-04 | Structured, centralized logging (correlation, no secrets) | Met | `docagent/correlation.py:15,36`; `terraform/ingestion/main.tf:174`; `terraform/runtime/logs.tf:3` |
| OPS-05 | Golden-signal metrics (latency/traffic/errors/saturation) | Met | EMF DurationMs/Runs (`metrics.py:19`); Lambda Errors + SQS depth (`observability/main.tf`) |
| OPS-06 | Distributed tracing / request correlation | Met | `correlation_id` propagated across 3 components (`correlation.py:15`, `worker-dispatcher/handler.py:44`) |
| OPS-07 | Actionable alarms tied to SLIs; notification path | Partial | alarms exist (`observability/main.tf`, `runtime/logs.tf`, `cloudtrail.tf`) but `alarm_actions` default `[]` (OPS-F2) |
| OPS-08 | Runbooks / operational docs | Met | `README.md` "Runbook (exploitation)" (DLQ, tracing, rotation, quota) |
| OPS-09 | Health / readiness / liveness | Met | AgentCore `/ping` HealthyBusy; handler kept non-blocking (`agent.py:56`, docstring) |
| OPS-10 | Config mgmt & env parity (dev/stage/prod) | Partial | config env-driven (`docagent/config.py`, `agents.json`) but single POC env (OPS-F5) |
| OPS-11 | Automated tests as release gate | Partial | 127 tests, no network (`README.md` Tests) but not enforced in CI (see OPS-F1) |
| OPS-12 | Post-incident/feedback (retros, error budgets) | Missing | no SLO/retro/error-budget material found (OPS-F4) |
| OPS-13 | Tagging for operational ownership | Met | `default_tags {Project,Env,Module}` in 6 modules (`ingestion/providers.tf:29`); runtime resources tagged Agent |
| OPS-14 | Dashboards for operational visibility | Met | `aws_cloudwatch_dashboard.main` (`observability/main.tf:79`) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add CI running pytest + `terraform fmt/validate` as a PR gate, then build/push + apply (OPS-F1) | M |
| P1 | Wire `alarm_actions` to an SNS topic (email/chatops) for DLQ + error alarms (OPS-F2) | S |
| P2 | Immutable image tags + documented one-step rollback in the runbook (OPS-F3) | M |
| P3 | Define minimal SLIs/SLOs (run success rate, p90 duration) + post-incident template (OPS-F4) | S |
| P3 | Parametrize backend + tfvars-per-env for future stage/prod parity (OPS-F5) | M |

## Notes & assumptions
- All 14 criteria were assessable from code/IaC (coverage 95%; the 5% reflects
  runtime-only facts — actual alarm firing, SNS delivery, dashboard rendering —
  not verifiable in a static audit).
- Idempotence/retry/DLQ are cited as supporting reversible operations but scored
  in Reliability (03) to avoid double counting.
- OPS-09 credited on the AgentCore SDK `/ping` liveness contract the code
  deliberately preserves (non-blocking entrypoint); Lambdas are event-driven so
  classic health probes are N/A there.
- A `waf.tf` exists in `ingestion/` (contradicts the "no WAF" note in the shared
  pack); WAF posture is a Security concern, out of scope here.
- Confidence medium: static-only, single deployed account claimed but not
  inspected live.
