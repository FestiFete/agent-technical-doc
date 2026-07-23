# Well-Architected & Architecture Audit — agent-technical-doc — 20260723-141235

**Global score:** 75/100  **Global maturity:** 2/5 (Developing) — **capped**
**Capping:** ⚠️ **Triggered.** One unresolved `Critical` finding (`REL-F1`, Reliability) caps global maturity at 2/5, regardless of the 75/100 weighted score (which alone would map to 4/5, Managed).
**Mode:** static  **Profile/Region:** n/a (live_aws OFF)
**Scope:** full 12-pillar re-audit, following the original audit (`audit/20260721-133806/`, 76/100, no capping) and a week of active remediation work — WAF+CloudFront, CloudTrail+GuardDuty, and two production incidents found and fixed via live end-to-end testing.

## Why capping triggered this run and didn't before

The Reliability pillar agent identified that **no alarm anywhere in the stack would have detected** the exact failure mode already seen in production this week: the SQS→worker Lambda poller silently stalling (zero throughput, no errors, no DLQ movement) due to a missing IAM permission. Neither the DLQ alarm nor the worker-Errors alarm fires in that scenario — the worker is simply never invoked. Even if an alarm did fire, none of the five CloudWatch alarms in this stack have a notification target (`alarm_actions` defaults to `[]`, no SNS topic exists anywhere in the repo). Since this is not hypothetical — it is the confirmed root cause of an incident that already happened and was manually diagnosed via direct CloudWatch Logs inspection — the pillar agent rated it `Critical` per the rubric ("likely prod outage"), which is a materially different judgment than "an alarm gap" in the abstract.

## Scores by dimension

| # | Dimension | Score | Maturity | Top severity | Applicable | Δ vs. prior full audit |
|---|-----------|-------|----------|--------------|------------|------|
| 1 | Operational Excellence | 61 | 3 (Defined) | High | yes | +4 |
| 2 | Security | 81 | 4 (Managed) | Info | yes | +5 |
| 3 | **Reliability** | **56** | **2 (Developing, capped)** | **Critical** | yes | -3 (uncapped would be 3) |
| 4 | Performance Efficiency | 75 | 4 (Managed) | Medium | yes | 0 |
| 5 | Cost Optimization | 83 | 4 (Managed) | Medium | yes | +1 |
| 6 | Sustainability | 83 | 4 (Managed) | Low | yes | +3 |
| 7 | Architecture | 83 | 4 (Managed) | Medium | yes | -15 |
| 8 | Terraform | 80 | 4 (Managed) | High | yes | +3 |
| 9 | Modularity | 81 | 4 (Managed) | Medium | yes | 0 |
| 10 | Decoupling | 86 | 4 (Managed) | Medium | yes | -1 |
| 11 | Scalability | 70 | 3 (Defined) | Medium | yes | -3 |
| 12 | Maintainability | 67 | 3 (Defined) | Medium | yes | 0 |

Weights applied: Security ×1.5, Reliability ×1.3, all others ×1.0 (default profile).
`global_score = Σ(pillar_score × weight) / Σ(weight) = 963.3 / 12.8 ≈ 75` → maps to maturity 4 uncapped, **capped to 2** by the Critical-capping rule.

Architecture's drop (98→83) is not regression in the design itself — it's stricter re-verification: `ARCHITECTURE.md` was found not to document the new CloudFront/WAF edge layer, and no alarm covers the incident's failure signature (the same gap driving the Reliability cap).

## Critical & High findings (consolidated)

| id | severity | pillar | title | evidence |
|----|----------|--------|-------|----------|
| REL-F1 | **Critical** | Reliability | No alarm covers a full silent pipeline stall — the exact failure mode already seen in production | [documentation/terraform/observability/main.tf:24-70](documentation/terraform/observability/main.tf#L24-L70) |
| OPS-F1 | High | Operational Excellence | No CI/CD pipeline; fully manual deployment | [documentation/scripts/agents/agent-technical-doc/e2e/README.md:331-352](documentation/scripts/agents/agent-technical-doc/e2e/README.md#L331-L352) |
| OPS-F2 | High | Operational Excellence | Alarm-notification gap has widened (2 new alarms added, still no SNS target) | [documentation/terraform/observability/variables.tf:21-25](documentation/terraform/observability/variables.tf#L21-L25) |
| REL-F2 | High | Reliability | Permanent worker errors are dropped without reaching the DLQ or any metric | [documentation/scripts/lambdas/worker-dispatcher/handler.py:80-96](documentation/scripts/lambdas/worker-dispatcher/handler.py#L80-L96) |
| REL-F3 | High | Reliability | No blast-radius containment or safe-change mechanism for the shared worker IAM role/deployment | [documentation/terraform/ingestion/main.tf:112-169](documentation/terraform/ingestion/main.tf#L112-L169) |
| TF-F1 | High | Terraform | No state locking on any of the 6 S3 backends (blast radius grew: 2 new modules added stateful resources without it) | [documentation/terraform/ingestion/providers.tf:19-24](documentation/terraform/ingestion/providers.tf#L19-L24) |

Cross-referenced duplicates (same underlying gap, not double-counted): the "alarms have no notification path" thread runs through `OPS-F2` (primary), `REL-F1`/`REL-F3` (compounding factor), `SEC-F3` (Medium), and `DEC-F2` (Low) — fixing one SNS topic + subscription closes all of them simultaneously.

## What actually improved this week (verified, not just claimed)

- **SEC-F1 (WAF bypass) fully closed**: origin-verify shared-secret header implemented and unit-tested; downgraded from Low to **Info**.
- **Two production incidents found and fixed via live testing**, both now documented in-code: missing `sqs:GetQueueAttributes` (silently stalled the async pipeline) and the `bedrock-agentcore:InvokeAgentRuntime` dual-ARN requirement (`AccessDeniedException` on every invocation). The pipeline was independently verified end-to-end successful after both fixes.
- **CloudTrail + GuardDuty + IAM/Secrets-access alarms** now exist (Security's `SEC-10` moved from a real gap toward `Partial`, held back only by the still-missing notification path and absent Config/Security Hub).
- **New 4-phase E2E test harness** (unit → local-run-with-real-deps → sandbox smoke → gated live E2E) specifically targets the failure class that caused both incidents (Operational Excellence, +4).
- **`terraform validate` now passes cleanly on all 7 modules**, independently re-run this session (Terraform pillar, +3).

## What the two incidents reveal, structurally

Both incidents share a pattern: an isolated, well-intentioned least-privilege IAM tightening commit removed a permission that looked unused from the *application code's* perspective, but was actually required by *AWS-managed infrastructure* (the Lambda SQS poller; AgentCore's authorization model) operating invisibly under the same execution role. No unit test could plausibly have caught either regression — this is fundamentally an integration/deployment-verification gap. Every pillar agent that touched this (Reliability, Operational Excellence, Architecture, Decoupling, Terraform, Maintainability) converged independently on the same conclusion: the fixes are good, but nothing yet *prevents a third recurrence* of this exact failure class. That is what `REL-F1`'s Critical severity is really pointing at.

## Remediation roadmap

### Quick wins (low effort, high value — closes the capping Critical and most High findings)
- **Add an alarm on the main SQS queue's `ApproximateAgeOfOldestMessage`/depth, and create one SNS topic + subscription wired to `var.alarm_actions`.** This single change resolves `REL-F1` (the capping Critical), `OPS-F2`, and meaningfully improves `SEC-F3`/`DEC-F2` — the highest-leverage fix in this report.
- Enable `ReportBatchItemFailures` on the SQS→worker event source mapping and/or emit a custom metric on permanent-error drops — `REL-F2`.
- Add S3 native locking (`use_lockfile = true`, Terraform ≥1.10 is installed) to all 6 backends — `TF-F1`.
- Add an `aws:SourceArn` condition to the CloudTrail bucket policy — `SEC-F3`.
- Scope the Bedrock `InvokeModel` resource to the configured model ARNs — `SEC-F4`.
- Pin Python dependencies with a lock file — `SEC-F5`/`MNT-F5`.
- Add `tests/test_analyzer.py` for `_extract_json`/`select_model` — `MNT-F3`.
- Update `ARCHITECTURE.md` to document the CloudFront/WAF/origin-verify layer — `ARC-F3`.

### Structural work
- Stand up a CI/CD pipeline (fmt/validate/pytest gate on PR; schedule the new E2E harness) — closes `OPS-F1`, `OPS-F4`, `TF-F3`, `MNT-F2` together.
- Add an automated post-apply smoke test (or staged rollout) for the worker IAM role / runtime deployment, so a third IAM regression can't reach 100% of traffic silently — `REL-F3`.
- Deduplicate the DynamoDB idempotency logic shared (by convention only) between the webhook Lambda and the agent runtime — `MOD-F1`/`DEC-F1`/`DEC-F3`.
- Parameterize the Terraform backend per environment — `OPS-F3`.
- Run a synthetic end-to-end load test before widening the repo allowlist — `SCAL-F3`/`PERF-F5`.
- Reintroduce customer-managed KMS keys once the account-level `kms:CreateKey` deny is lifted — `SEC-F2`.

## Method & limitations

- **Mode:** static-only (`live_aws=OFF`); no AWS API calls made by any sub-agent for this run's evidence. (Separately, outside this audit, a live debugging session earlier the same day used AWS CLI access to diagnose and fix the two incidents described above — that is operational history informing the context pack, not audit evidence.)
- **Target:** repo root, real project under `documentation/`. Working tree clean at commit `f89ea51`.
- **Orchestration:** 12 independent sub-agents (general-purpose, one per pillar), same shared context pack, run in parallel. `terraform fmt`/`validate` independently re-run by the Terraform and Maintainability agents this session (isolated scratch copies, real state never touched); both pytest suites actually executed (107+2 skipped, 23 passed).
- **Prior audits available to every sub-agent** as unverified claims to independently re-check: the original full audit (`audit/20260721-133806/`, 76/100) and two Security-focused re-runs (`audit/20260721-154651/`, `audit/20260722-152501/`, both 81/100). Scores were independently re-derived, not carried forward — several pillars landed on values close to prior runs by coincidence of unchanged verdicts, not by copying.
- **De-duplication:** the alarm-notification gap surfaces in 5 pillars; scored independently per pillar's own rubric (per instructions), but cross-referenced rather than repeated in the top-findings table above.
- **Coverage:** 80–95% per pillar, reported in each detail file.
