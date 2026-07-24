# Sustainability — Audit

**Score:** 98/100  **Maturity:** 5 (Optimized)  **Coverage:** 100%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Environmental impact of the workload: maximizing utilization, minimizing wasted
resources, and choosing efficient regions / hardware / patterns. Grounded in the AWS
Well-Architected **Sustainability** pillar
([Sustainability Pillar — AWS WAF](https://docs.aws.amazon.com/sustainability/latest/userguide/resources.html),
[sustainability pillar overview](https://docs.aws.amazon.com/managedservices/latest/appguide/well-architected-aog.html)):
maximize utilization, adopt efficient hardware/software, prefer managed services,
reduce downstream impact, right-size and scale to actual demand.

**Not covered here (cross-reference):** dollar cost → **Cost Optimization (05)**
(strongly correlated; utilization/retention/ARM64 findings are scored here and
cross-referenced there, not double-counted); raw latency/throughput →
**Performance Efficiency (04)**.

This is a **static** audit (live_aws OFF): utilization is assessed from the
architecture and IaC, not from live CloudWatch utilization metrics.

## Strengths
- Fully serverless, event-driven pipeline (API GW HTTP API → Lambda → SQS → Lambda
  worker → AgentCore Runtime) with scale-to-zero — no always-on compute to idle-burn
  — _evidence: `terraform/ingestion/main.tf:150-210` (Lambdas + event source mapping)_
- ARM64/Graviton everywhere: both Lambdas and the runtime container image —
  _evidence: `terraform/ingestion/main.tf:181,205` (`architectures = ["arm64"]`), `scripts/agents/agent-technical-doc/Dockerfile:1` (`FROM --platform=linux/arm64`)_
- Only managed services (Lambda, SQS, DynamoDB, API Gateway, Secrets Manager, Bedrock
  AgentCore, CloudWatch) — zero self-managed always-on infrastructure —
  _evidence: `terraform/ingestion/main.tf`, `terraform/security/main.tf`, `terraform/runtime/main.tf`_
- Aggressive data minimization: SQS main queue 4-day / DLQ 14-day retention, DynamoDB
  TTL purge, 14-day CloudWatch log retention, CloudTrail S3 lifecycle expiration —
  _evidence: `terraform/ingestion/main.tf:9,17`, `terraform/security/main.tf:64-67`, `terraform/runtime/logs.tf:6`, `terraform/observability/cloudtrail.tf:60-70`_
- Stateless agent — no Bedrock Memory, no Knowledge Base, no vector store to keep warm
  or duplicate data — _evidence: `scripts/agents/agents.json:3` ("sans état (ni Memory ni KB)")_
- Bounded processing caps the LLM context (40 files / 80 KB per file / 1.2 MB total),
  directly limiting input tokens (compute/energy per run) —
  _evidence: `docagent/config.py:60-64`, `scripts/agents/agents.json:12-14`_
- Two-tier model selection (economical Haiku by default, escalate to Sonnet only for
  large repos) matches compute to demand — _evidence: `docagent/config.py:78-84`_
- DynamoDB on-demand (PAY_PER_REQUEST) matches capacity to actual demand —
  _evidence: `terraform/security/main.tf:52`_

## Weaknesses / Findings

### [Low] SUS-F1 — Region choice has no documented sustainability rationale
- **Evidence:** `terraform/shared.tfvars:19` (`aws_region = "eu-central-1"`), hard-coded per-module in `providers.tf`
- **Impact:** Region (`eu-central-1`, Frankfurt) is fixed with no recorded
  consideration of carbon intensity. It happens to be a comparatively low-carbon EU
  region, so real-world impact is small, and the choice is likely driven by data
  residency/latency rather than being freely flexible. Purely a documentation gap.
- **Recommendation:** Record the region-selection rationale (residency + carbon) in
  `ARCHITECTURE.md` so the sustainability trade-off is explicit and revisitable.
- **Alternative solution:** None — the workload is EU-bound for data residency, so the
  region is not a free variable; documenting the rationale is the appropriate action.

### [Info] SUS-F2 — AgentCore idle session timeout keeps a session warm for 15 min
- **Evidence:** `terraform/runtime/data.tf:62` (`idle_timeout = 900`), applied at `terraform/runtime/main.tf:23-26`
- **Impact:** After a run, the runtime session stays alive up to 900 s idle (max
  lifetime 3600 s). This is a bounded, session-scoped warm window — not sustained
  idle burn — and improves warm-start behaviour for bursty PR activity. Negligible.
- **Recommendation:** Keep as-is; optionally lower `idle_timeout` if telemetry shows
  runs are rarely clustered, to trim residual warm time. No action required for a POC.
- **Alternative solution:** None — the current bounded window is a reasonable
  utilization/latency trade-off.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SUS-01 | High utilization; scale-to-zero / demand-matched capacity (no idle burn). | Met | `terraform/ingestion/main.tf:150-210` (Lambda pay-per-invoke + SQS event source), `terraform/runtime/data.tf:61-64` (idle 900s/max 3600s session-scoped), `terraform/security/main.tf:52` (DynamoDB PAY_PER_REQUEST) |
| SUS-02 | Energy-efficient compute (ARM/Graviton, serverless) where feasible. | Met | `terraform/ingestion/main.tf:181,205` (`arm64`), `scripts/agents/agent-technical-doc/Dockerfile:1` (`--platform=linux/arm64`) |
| SUS-03 | Managed services preferred over self-managed always-on infrastructure. | Met | `terraform/ingestion/main.tf` (API GW/Lambda/SQS), `terraform/security/main.tf` (DynamoDB/Secrets Mgr), `terraform/runtime/main.tf:3` (AgentCore Runtime) |
| SUS-04 | Data minimization: retention/lifecycle limits, no needless data duplication. | Met | `terraform/ingestion/main.tf:9,17` (SQS 14d/4d), `terraform/security/main.tf:59-62` (DynamoDB TTL), `terraform/runtime/logs.tf:6` (14d logs), `terraform/observability/cloudtrail.tf:60-70` (S3 lifecycle expiration); stateless — `scripts/agents/agents.json:3` |
| SUS-05 | Efficient algorithms/bounded processing (no wasteful recompute/polling). | Met | `docagent/config.py:60-64` (read caps 40/80KB/1.2MB), `docagent/config.py:78-84` (deterministic model escalation), `docagent/retry.py:63-90` (bounded retries on transient only), idempotency avoids recompute (`terraform/security/main.tf` TTL table) |
| SUS-06 | Batching/async to smooth utilization vs constant polling. | Met | `terraform/ingestion/main.tf:214-223` (managed SQS event source mapping, no custom polling), async agent invocation per inventory (`agent.py` add_async_task) |
| SUS-07 | Region choice considers sustainability where flexible. | Partial | `terraform/shared.tfvars:19` (`eu-central-1`, fixed, no documented sustainability rationale) — see SUS-F1 |
| SUS-08 | Right-sized storage tiers; cold data on efficient tiers. | Met | Data is small/short-lived: DynamoDB on-demand + TTL (`terraform/security/main.tf:52,59-62`); CloudTrail S3 expires cold logs via lifecycle (`terraform/observability/cloudtrail.tf:60-70`) — expiration is more efficient than tiering for ephemeral data |
| SUS-09 | Test/dev environments not left running idle. | Met | Serverless scale-to-zero → no idle dev burn; single `POC` env (`terraform/shared.tfvars:13`); tests run offline via dependency injection, E2E harness is local/dry-run (inventory) |
| SUS-10 | Observability/log volume proportionate (no excessive retention). | Met | `terraform/runtime/logs.tf:6` + `terraform/ingestion/main.tf` (14-day CW retention), lightweight EMF metrics (`docagent/metrics.py`), CloudTrail retention parameterized (`terraform/observability/cloudtrail.tf:104`) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P3 | Document the region-selection rationale (residency + carbon intensity) in `ARCHITECTURE.md` (SUS-F1) | S |
| P3 | Optionally tune AgentCore `idle_timeout` down if run-clustering telemetry shows sparse activity (SUS-F2) | S |

## Notes & assumptions
- **Static audit only.** SUS-01 (utilization) and SUS-09 (idle) are judged from the
  serverless/event-driven architecture and IaC configuration, not from live
  utilization metrics; the design guarantees scale-to-zero, which is the dominant
  sustainability lever here.
- Retention/lifecycle, ARM64, and on-demand billing findings are shared with **Cost
  Optimization (05)**: scored here, cross-referenced there — not double-counted.
- `Critical` is reserved for gross sustained waste; none exists. The two findings are
  Low/Info documentation/tuning items with negligible real impact.
- Score = 100 × (10.25 / 10.5) = 97.6 → **98**. Only SUS-07 is Partial (weight 0.5).
- Coverage 100%: all 10 criteria assessable from code/IaC. Confidence high because
  every verdict is backed by a concrete IaC/code fact; the one architecture-level
  inference (actual runtime utilization) does not change any verdict.
