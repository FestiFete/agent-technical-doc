# Operational Excellence — Audit

**Score:** 61/100  **Maturity:** 3 (Defined)  **Coverage:** 95%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Assesses the ability to run, monitor, and continuously improve the workload: observability (logs/metrics/tracing), deployment/release safety, automation of operations, incident response, and operational feedback loops.

Does **not** cover: long-term code changeability (→ Maintainability, pillar 12), failure tolerance / RTO-RPO / multi-AZ (→ Reliability, pillar 03), or Terraform structure/conventions as such (→ Terraform, pillar 08). Findings here are cross-referenced by id where they overlap those pillars, not double-scored.

## Delta since the prior run (audit/20260721-133806/01-operational-excellence.md, score 57/100)

Independently re-verified every criterion against the current committed state (`f89ea51`, working tree clean except this audit's own output dir). Net movement: **+3 points**, driven by a mix of genuine improvement and confirmation that several gaps remain exactly as before.

**Improved:**
- A substantial 4-phase E2E test harness now exists (`documentation/scripts/agents/agent-technical-doc/e2e/{local_run,harness,smoke_check}.py`, `e2e/README.md`) that was not captured in the prior run: an offline harness-consistency test (`tests/test_harness.py`), a gated live end-to-end test against a deployed stack (`tests/test_e2e_webhook.py`, `pytestmark = pytest.mark.e2e`), and a `smoke_check.py` PASS/FAIL/TIMEOUT verifier. This is real integration-test capability beyond the unit-test suite the prior run scored, and it is precisely the kind of test that (had it been run in CI) could have caught the "managed AWS infrastructure needs permissions the app code doesn't call directly" failure class described in the context pack. It nudges OPS-11 up but does **not** flip it to `Met`: the harness is not automated (Phase 4 "CI industrialisation" is explicitly `⏳ à faire`, `e2e/README.md:331-352`) and nothing gates a `terraform apply`/image push on it passing.
- Two live-verified IAM/config production bugs (SQS `GetQueueAttributes` for the managed event-source-mapping poller; `bedrock-agentcore:InvokeAgentRuntime` needing both the bare runtime ARN and its `/runtime-endpoint/DEFAULT` child ARN) are now fixed and committed, with the failure mode explicitly documented in code comments (`documentation/terraform/ingestion/main.tf:139-146,151-164`). This is evidence the operational feedback loop *does* work end-to-end when exercised manually (bug found live → root-caused → fixed → committed with rationale) — but it is also first-hand proof that no automated gate exists to catch this class of regression before it reaches a deployed environment, directly reinforcing OPS-02/OPS-11's `Missing`/`Partial` verdicts rather than offsetting them.
- Account-wide detective controls added (`documentation/terraform/observability/cloudtrail.tf`): CloudTrail multi-region trail + two metric-filter/alarm pairs (IAM changes, Secrets Manager access spikes), GuardDuty detector. These are primarily Security-pillar findings, but the two new alarms are additional SLI-tied signals for OPS-05/07.

**Unchanged (re-confirmed, not assumed):**
- No CI/CD pipeline: `find . -iname "*.yml" -o -iname "*.yaml"` and a search for `.github` at repo root return nothing anywhere in the repository (confirmed fresh this run, not copied from the prior report). `documentation/scripts/agents/agent-technical-doc/e2e/README.md:331-352` still labels "Phase 4 — Industrialisation CI" as **not implemented**.
- No SNS topic exists anywhere (`grep -rl aws_sns_topic documentation/terraform` → no matches) and `alarm_actions` still defaults to `[]` (`documentation/terraform/observability/variables.tf:21-25`) — now with **two additional alarms** (`iam_changes`, `secrets_access`, `cloudtrail.tf:173-186,205-218`) also wired to the same empty default, so the "alarms fire into the void" gap has grown in surface area, not shrunk.
- No distributed tracing (`tracing_config`/X-Ray) on either ingestion Lambda — re-checked `documentation/terraform/ingestion/main.tf` in full, no `tracing_config`/`xray`/`active_tracing` string anywhere in the file.
- No environment parity: `environment = "POC"` is still the only value (`documentation/terraform/shared.tfvars:16`), and backend `key`/`bucket` are still hardcoded per module (`documentation/terraform/{ecr,ingestion,roles,observability,runtime,security}/providers.tf`), not parameterized.
- Tagging strategy and CloudWatch dashboard are unchanged (`*/providers.tf` `default_tags` blocks re-verified present in 6/7 modules with `security` intentionally excluded for a documented IAM reason; `documentation/terraform/observability/main.tf:75-163` dashboard widget set is byte-for-byte the same 6-widget layout as the prior run — no new widget was added for the new WAF/CloudTrail components).
- Rollback: ECR digest-pinning pattern (`documentation/terraform/runtime/main.tf:10-13`) is unchanged; still no written rollback procedure in the runbook.

**Net:** the E2E-harness addition and the fixed IAM bugs are real, incremental maturity gains, but the two most consequential prior findings (no CI/CD, alarms with no notification path) are not only still open but the alarm-notification gap has objectively widened (more alarms pointing at the same empty list). Score moves modestly from 57 to 61, not materially higher.

## Strengths
- End-to-end `correlation_id` (= GitHub `X-GitHub-Delivery`) threaded through webhook → SQS → worker → runtime, documented as the tracing mechanism in the runbook — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:1-23`, `documentation/scripts/lambdas/webhook-receiver/handler.py:220-264`, `documentation/README.md:192-194`_
- New: a 4-phase, increasingly-realistic test ladder (unit → local-run-with-real-dependencies → sandbox smoke → gated live E2E) that specifically targets the class of bug the two IAM incidents exposed — _evidence: `documentation/scripts/agents/agent-technical-doc/e2e/README.md:1-360`, `documentation/scripts/agents/agent-technical-doc/tests/test_e2e_webhook.py:25,46`, `documentation/scripts/agents/agent-technical-doc/tests/test_harness.py`_
- The two production IAM bugs were root-caused and fixed with the failure mechanism documented directly in the Terraform comments, aiding future operators — _evidence: `documentation/terraform/ingestion/main.tf:139-146,151-164`_
- EMF metrics (duration, outcome, correlation_id) auto-extracted by CloudWatch, no extra IAM needed — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/metrics.py:1-49`_
- Secret masking helper applied before logging (GitHub PATs, HMAC/Authorization headers) — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:27-49`_
- Centralized, bounded-retention CloudWatch Log Groups for all pipeline components, now including a dedicated WAF log group and a CloudTrail-fed log group — _evidence: `documentation/terraform/ingestion/main.tf:174-`, `documentation/terraform/runtime/logs.tf:3-10`, `documentation/terraform/ingestion/waf.tf:47-51`, `documentation/terraform/observability/cloudtrail.tf:103-107`_
- Health check pattern explicit and documented: `/ping` liveness deliberately decoupled from the async work loop — _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:24-32,80,93`_
- Written runbook covering DLQ triage, run tracing, secret rotation, allowlist/quota tuning, dedup troubleshooting — _evidence: `documentation/README.md:186-204`_
- 100% infra-as-code across 7 chained Terraform modules; no undocumented console resources found — _evidence: `documentation/terraform/*/main.tf`_
- Runtime container auto-instrumented with OpenTelemetry — _evidence: `documentation/scripts/agents/agent-technical-doc/Dockerfile:16-17`_

## Weaknesses / Findings

### [High] OPS-F1 — No CI/CD pipeline; fully manual deployment
- **Evidence:** No `.github/workflows/` or any `*.yml`/`*.yaml` file anywhere in the repository (re-confirmed fresh this run via `find . -iname "*.yml" -o -iname "*.yaml"` and a search for `.github` — zero results); `documentation/scripts/agents/agent-technical-doc/e2e/README.md:331-352` explicitly labels CI industrialisation "non implémentée"; `documentation/README.md:159` still flags Phase 4 as `⏳ à faire`.
- **Impact:** Every deploy still depends on an operator running `terraform apply` module-by-module from a local machine in the right order. The two IAM regressions described in the context pack (SQS poller permission, dual-ARN AgentCore invoke) are direct, live-verified proof of this gap's real-world cost: both were "least-privilege tightening" changes that looked correct in isolation, passed no automated check (there is none), and silently broke production until discovered via manual log inspection.
- **Recommendation:** Add a minimal GitHub Actions pipeline: on PR, `terraform fmt -check` + `terraform validate` per module + `pytest` (unit suite); on merge, a gated `terraform plan`/`apply` step. Layer in the existing `pytest -m e2e` harness as a nightly/on-demand job against a long-lived sandbox once the backend is parameterized (OPS-10).
- **Alternative solution:** GitHub Actions + OIDC-federated deploy role. Pros: no long-lived AWS keys, reuses the project's GitHub-centric trigger surface, the E2E harness (`e2e/harness.py`, `e2e/smoke_check.py`) is already built to run non-interactively and just needs a scheduler. Cons: sequencing 7 chained `terraform_remote_state` modules in a pipeline is real setup work; a scoped deploy IAM role must be created (Security pillar). Effort: M. Cross-pillar: Security (deploy credentials), Terraform (plan/validate gating), Maintainability (release process).

### [High] OPS-F2 — Alarms still have no notification target; gap has widened, not narrowed
- **Evidence:** `documentation/terraform/observability/variables.tf:21-25` — `alarm_actions` still `default = []`; no `aws_sns_topic` resource anywhere (`grep -rl aws_sns_topic documentation/terraform` → no matches). Since the prior audit, **two more alarms** were added and wired to the same empty default: `documentation/terraform/observability/cloudtrail.tf:173-186` (`iam_changes`) and `:205-218` (`secrets_access`), on top of the pre-existing `dlq_not_empty`/`worker_errors`/`webhook_errors` (`documentation/terraform/observability/main.tf:24-69`) and `runtime_errors_alarm` (`documentation/terraform/runtime/logs.tf:79-`).
- **Impact:** All five (now potentially more) CloudWatch alarms — including the two new security-relevant ones (unauthorized IAM change, Secrets Manager access spike) — fire into the void by default. This is a materially worse blast radius than at the prior audit: detective controls were just added specifically to catch account compromise/misconfiguration, but nobody is notified when they trip.
- **Recommendation:** Provision a minimal SNS topic + email/Slack subscription in the `observability` module and default `alarm_actions` to it; this is a small, self-contained change (no dependency on CI/CD or backend work).
- **Alternative solution:** SNS topic + subscription, ARN passed as the default `alarm_actions`. Pros: closes the gap for near-zero cost/effort, no new AWS service to learn. Cons: still requires a human on-call process to act on the notification, which is outside Terraform's control. Effort: S. Cross-pillar: Reliability (incident response readiness), Security (detective-control follow-through).

### [Medium] OPS-F3 — No environment parity; single hardcoded "POC" environment
- **Evidence:** `documentation/terraform/shared.tfvars:16` — `environment = "POC"` remains the only defined value; backend `key` is hardcoded per module and not parameterized, e.g. `documentation/terraform/ingestion/providers.tf:22` (`key = "ingestion/terraform.tfstate"`), same pattern re-confirmed in `ecr`, `roles`, `observability`, `runtime`, `security` providers.tf files.
- **Impact:** No dev/stage/prod split; nothing prevents a config or IaC change from landing directly on the only environment that exists. `e2e/README.md:339-340` itself names backend parameterization as a blocking prerequisite for CI industrialisation (Phase 4), so this finding directly blocks OPS-F1's remediation, not just environment hygiene in isolation.
- **Recommendation:** Parameterize backend keys via `-backend-config` per environment (already anticipated in the project's own comments) and stand up at least a staging environment before broader rollout.
- **Alternative solution:** None better than executing the multi-env Terraform workspace/backend-config split the project already anticipates. Effort: M. Cross-pillar: Terraform (backend structure).

### [Medium] OPS-F4 — Automated tests are not a release gate, despite real integration-test capability now existing
- **Evidence:** Beyond the 17-file unit-test suite (`documentation/scripts/agents/agent-technical-doc/tests/`, `documentation/scripts/lambdas/tests/`), a genuine E2E harness now exists (`e2e/harness.py`, `e2e/smoke_check.py`, `tests/test_e2e_webhook.py` marked `pytest.mark.e2e`) that specifically exercises the deployed webhook→SQS→worker→runtime chain — but it is entirely manual/on-demand (`e2e/README.md:307-311`: "le lancer avec `E2E_*` non défini le skippe proprement (utile en CI hors ligne)" — i.e. designed for future CI but not wired to any pipeline today), and no CI exists to run any tier of tests before a deploy (see OPS-F1).
- **Impact:** A regression — including exactly the "managed AWS infrastructure IAM requirement" class that caused the two live production incidents — can still reach a deployed environment as long as an operator skips or forgets to manually run the unit suite, let alone the on-demand E2E harness.
- **Recommendation:** Wire the unit suite into CI as a blocking PR check first (cheap, no infra dependency); schedule the `pytest -m e2e` harness as a nightly/on-demand job against a long-lived sandbox once OPS-F3's backend parameterization lands.
- **Alternative solution:** Covered by OPS-F1/OPS-F3's alternatives; no separate solution needed. Effort: S for the unit-test gate (once CI exists), M for scheduling the E2E harness. Cross-pillar: none beyond OPS-F1/OPS-F3.

### [Medium] OPS-F6 — No distributed tracing across the Lambda hops; correlation id only
- **Evidence:** Re-confirmed no `tracing_config`/`xray`/`active_tracing` anywhere in `documentation/terraform/ingestion/main.tf` (full-file grep, no matches); OpenTelemetry auto-instrumentation remains scoped to the runtime container only (`documentation/scripts/agents/agent-technical-doc/Dockerfile:16-17`).
- **Impact:** Cross-component causal/latency analysis still depends on manually grepping a shared `correlation_id` across log groups rather than a queryable trace with span timing — unchanged from the prior run, still acceptable for a low-volume POC but a real limitation as volume grows.
- **Recommendation:** Enable AWS X-Ray active tracing on both Lambda functions (`tracing_config { mode = "Active" }`).
- **Alternative solution:** X-Ray (managed, near-zero setup) vs. extending OTel to the Lambdas via an ADOT layer (more consistent with the runtime's existing OTel stack, heavier to set up). Recommend X-Ray for effort reasons. Effort: S. Cross-pillar: none.

### [Low] OPS-F5 — API Gateway stage still has no access logging configured
- **Evidence:** `documentation/terraform/ingestion/main.tf` — the `aws_apigatewayv2_stage.default` resource still has no `access_log_settings` block (re-checked this run).
- **Impact:** HTTP-level request logs (source IP, path, status, latency) at the API Gateway layer are not captured independently of Lambda-level logging; edge-level troubleshooting (e.g. requests rejected by the new WAF/CloudFront layer before reaching the Lambda) is harder to correlate.
- **Recommendation:** Add `access_log_settings` pointing at a dedicated CloudWatch Log Group with a JSON format including `requestId`, `sourceIp`, `status`, `integrationLatency`.
- **Alternative solution:** None better — standard mechanism. Effort: S.

### [Low] OPS-F7 — No post-incident / feedback loop mechanism defined
- **Evidence:** No SLI/SLO, error budget, retro, or post-mortem process found in `documentation/README.md`, `documentation/ARCHITECTURE.md`, `documentation/AUDIT.md`, or the runbook (`README.md:186-204`) — re-searched, nothing found. Notably, the two live-verified production IAM incidents (context pack §3) are documented only as inline Terraform comments (`ingestion/main.tf:139-146,151-164`), not as any structured incident record.
- **Impact:** No structured mechanism exists to turn the DLQ/alarm runbook steps, or incidents like the two live-verified IAM bugs, into tracked process improvements beyond the ad hoc code comment left behind.
- **Recommendation:** For a POC this remains a reasonable gap, but given two real production incidents have now occurred, a lightweight incident log (trigger, root cause, fix, follow-up action — e.g. "add regression test for managed-infra IAM permissions") would meaningfully close the loop the context pack itself flags as currently missing.
- **Alternative solution:** None — appropriate to defer at POC stage, but recommend prioritizing ahead of broader rollout given the incident history has now materialized.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| OPS-01 | Infrastructure & operations defined as code (no manual console drift). | Met | `documentation/terraform/*/main.tf` (7 modules incl. new `ingestion/waf.tf`, `observability/cloudtrail.tf`); secret *values* set out-of-band via `secretsmanager put-secret-value`, documented as expected (`documentation/README.md:105-116`, `e2e/README.md:203-207`), not undocumented drift |
| OPS-02 | CI/CD pipeline exists with automated build/test/deploy stages. | Missing | No `.github/workflows/`, no `*.yml`/`*.yaml` anywhere in repo (fresh `find`); `e2e/README.md:331-352` "Phase 4 — non implémentée" — OPS-F1 |
| OPS-03 | Deployments are small, reversible; rollback strategy defined. | Partial | ECR digest pinning enables manual rollback (`documentation/terraform/runtime/main.tf:10-13`); still no written rollback procedure in the runbook; deploys remain multi-module chained applies, not small increments |
| OPS-04 | Structured, centralized logging (correlation ids, no secrets in logs). | Met | `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:1-49`, `documentation/scripts/lambdas/webhook-receiver/handler.py:220-264`, log groups incl. new `ingestion/waf.tf:47-51`, `observability/cloudtrail.tf:103-107`; gap: no API GW access logs (OPS-F5) |
| OPS-05 | Metrics on the golden signals (latency, traffic, errors, saturation). | Partial | Latency/traffic/errors covered (`observability/main.tf:86-160`, `docagent/metrics.py`) plus new IAM-change/Secrets-access volume metrics (`observability/cloudtrail.tf:160-171,192-203`); saturation (Lambda concurrency, queue backlog rate) still not alarmed |
| OPS-06 | Distributed tracing / request correlation where relevant. | Partial | Correlation id across all components + OTel in runtime container only; no `tracing_config` on ingestion Lambdas (`documentation/terraform/ingestion/main.tf`, full-file grep) — OPS-F6 |
| OPS-07 | Actionable alarms tied to SLIs; on-call/notification path defined. | Partial | 5 alarms tied to real SLIs, all sharing `alarm_actions = []` default with no SNS topic in-repo — gap widened by 2 new alarms since prior run (`observability/variables.tf:21-25`, `observability/cloudtrail.tf:173-186,205-218`) — OPS-F2 |
| OPS-08 | Runbooks / operational docs for common tasks & incidents. | Met | `documentation/README.md:186-204` (DLQ triage, tracing, secret rotation, allowlist/quota); expanded by `e2e/README.md` sandbox deploy/smoke/teardown runbook (§Phase 2, `e2e/README.md:164-276`) |
| OPS-09 | Health checks & readiness/liveness for services. | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:24-32,80,93` (`/ping`, non-blocking) |
| OPS-10 | Config management & environment parity (dev/stage/prod). | Missing | Single `environment = "POC"` (`documentation/terraform/shared.tfvars:16`); hardcoded per-module backend keys re-confirmed across all 6 non-bootstrap modules — OPS-F3 |
| OPS-11 | Automated tests as a release gate (unit/integration). | Partial | Unit suite (17 files) + new gated E2E harness (`e2e/harness.py`, `tests/test_e2e_webhook.py`) exist, but nothing enforces either pre-deploy (no CI) — OPS-F4 |
| OPS-12 | Post-incident/feedback mechanism (retros, error budgets). | Missing | No SLI/SLO/retro/post-mortem process found; two real incidents (context pack §3) recorded only as code comments, not a structured log — OPS-F7 |
| OPS-13 | Tagging strategy enabling operational ownership. | Met | `default_tags { Project, Env, Module }` present in 6/7 provider files (e.g. `documentation/terraform/ingestion/providers.tf:29-47`); intentionally absent in `security` module with documented reason (`documentation/terraform/security/providers.tf:22`) |
| OPS-14 | Dashboards for operational visibility. | Met | `documentation/terraform/observability/main.tf:75-163` (6-widget dashboard, unchanged since prior run); gap noted — no widget added for the new WAF/CloudTrail components |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Create an SNS topic + subscription and wire it as the default `alarm_actions` for all 5 alarms — OPS-F2 | S |
| P1 | Stand up a minimal CI pipeline (fmt/validate/pytest unit suite on PR, gated apply on merge) — OPS-F1, OPS-F4 | M |
| P2 | Parameterize Terraform backend per environment (`-backend-config`) and stand up a staging environment — this also unblocks CI Phase 4 per the project's own notes — OPS-F3 | M |
| P2 | Schedule the existing `pytest -m e2e` harness as a nightly/on-demand CI job once a sandbox/backend exists — OPS-F4 | M |
| P2 | Enable X-Ray active tracing on the webhook/worker Lambdas — OPS-F6 | S |
| P3 | Add `access_log_settings` to the API Gateway `$default` stage — OPS-F5 | S |
| P3 | Document an explicit rollback procedure in the runbook (revert ECR digest / prior Terraform state) — OPS-03 | S |
| P4 | Start a lightweight incident log covering the two already-occurred production IAM incidents plus future ones — OPS-F7 | S |

## Notes & assumptions
- Static analysis only; `live_aws=OFF` per this run's instructions — no AWS API calls made, no confirmation that alarms/dashboards/CloudTrail/GuardDuty actually exist as deployed vs. as defined in Terraform (state not inspected). The context pack notes a separate, out-of-band live debugging session occurred earlier the same day but its findings are treated as narrative context, not evidence for this report — every verdict above is grounded in a fresh `path:line` citation from the current committed tree.
- Did not re-verify every one of the 19 Python test files' content line-by-line; confirmed existence, the new E2E harness's actual mechanics (read `e2e/README.md` in full, confirmed `pytest.mark.e2e` gating in `tests/test_e2e_webhook.py`), and the README's documented test-running procedure.
- Treated the prior run's 57/100 score and every individual verdict as an unverified claim per instructions; independently re-derived all 14 criteria from current evidence rather than carrying any forward. The +3 delta reflects real but modest net change, not a re-interpretation of unchanged facts.
- WAF/CloudFront (`ingestion/waf.tf`) and CloudTrail/GuardDuty (`observability/cloudtrail.tf`) are primarily Security-pillar (02) territory; only their operational-excellence-relevant angles (new log groups, new alarms feeding the same notification gap, no new dashboard widgets) are scored here to avoid double-counting.
