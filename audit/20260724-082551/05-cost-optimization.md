# Cost Optimization — Audit

**Score:** 86/100  **Maturity:** 4 (Managed)  **Coverage:** 95%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Assesses running at the lowest price point for the required outcome: pricing-model
fit, right-sizing, scale-to-zero, storage/log lifecycle, cost attribution, spend
visibility/alerting, avoidance of undifferentiated heavy lifting, data-transfer
cost, and efficiency per unit of business value. Grounded in the AWS
Well-Architected **Cost Optimization** pillar
([welcome](https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html)).

Does **not** cover raw latency/throughput tuning → **Performance Efficiency (04)**
(this pillar only judges the price/perf trade-off), nor elastic-scaling correctness
→ **Scalability (11)**.

Context: fully serverless, event-driven, scale-to-zero pipeline (API GW HTTP API →
Lambda → SQS → Lambda worker → Bedrock AgentCore Runtime), ARM64/Graviton
everywhere, Bedrock on-demand with Haiku-default / Sonnet-escalation model tiering,
read caps bounding token spend, DynamoDB on-demand + TTL, 14-day log retention, and
a per-repo quota that also bounds Bedrock spend. Audit is **static** (code/IaC only).

## Strengths
- Consumption/on-demand pricing model end-to-end: Lambda + API GW HTTP API + SQS +
  AgentCore Runtime + Bedrock on-demand + DynamoDB `PAY_PER_REQUEST`. No provisioned
  capacity, no Savings-Plan-shaped baseline to waste — _evidence: `terraform/security/main.tf:55` (`billing_mode = "PAY_PER_REQUEST"`), `terraform/ingestion/main.tf:238-246` (event-source mapping, no provisioned concurrency)_
- ARM64/Graviton on all compute (both Lambdas + runtime container image) — the
  cheaper price/perf point — _evidence: `terraform/ingestion/main.tf:190` & `:220` (`architectures = ["arm64"]`)_
- Right-sized functions: 256 MB memory, short timeouts (webhook 15 s, worker 60 s
  for a non-blocking async ack) — _evidence: `terraform/ingestion/main.tf:194,224`; `terraform/ingestion/variables.tf:60,66`_
- Scale-to-zero runtime: AgentCore idle-session timeout 900 s + max-lifetime 3600 s;
  no idle compute between PR events — _evidence: `terraform/runtime/data.tf:59-63` (`default_agent_config`), `terraform/runtime/main.tf:26-29`_
- Bedrock spend actively bounded: two-tier model selection (Haiku default, escalate
  to Sonnet only for large/complex repos) + deterministic read caps (40 selected
  files / 80 KB per file / 1.2 MB total) capping input tokens per run — _evidence: `docagent/analyzer.py:126-176` (`select_model`), `docagent/config.py:62-74` (`ReadCaps`), `scripts/agents/agents.json:8-16`_
- Storage/log lifecycle bounded across the board: 14-day CloudWatch retention
  (Lambdas, runtime, WAF), ECR lifecycle expiry (untagged 1 day, keep N tagged),
  DynamoDB TTL purge, SQS message retention (4 d main / 14 d DLQ), CloudTrail S3
  expiration — _evidence: `terraform/ingestion/main.tf:159-166`, `terraform/runtime/logs.tf:7`, `terraform/ecr/main.tf:34-63`, `terraform/security/main.tf:65-68` (TTL), `terraform/ingestion/main.tf:16,10`_
- Cheapest fitting managed features: no OpenSearch/vector DB (agent is stateless —
  no KB, no Memory), no NAT Gateway (serverless), CloudFront `PriceClass_100`
  (cheapest edge tier), AWS-managed keys instead of CMK — _evidence: `scripts/agents/agents.json:4`, `terraform/ingestion/waf.tf:218` (`price_class = "PriceClass_100"`)_
- Per-unit-of-value telemetry: EMF metrics `Runs` / `DurationMs` / `FilesCommitted`
  dimensioned by Agent+Outcome give a cost-per-run efficiency proxy — _evidence: `docagent/metrics.py`, `terraform/observability/main.tf:118-155` (dashboard DurationMs/Runs widgets)_

## Weaknesses / Findings

### [Medium] COST-F1 — No budgets, alerts, or cost anomaly detection
- **Evidence:** no `aws_budgets_budget`, `aws_ce_anomaly_monitor`, or
  `aws_ce_anomaly_subscription` anywhere in `terraform/**` (repo-wide grep for
  `budget|anomaly|ce_` returns only unrelated matches). CloudWatch alarms exist for
  DLQ/errors (`terraform/observability/main.tf:18-84`) but none track spend.
- **Impact:** No financial guardrail or notification. Although runaway Bedrock spend
  is structurally bounded by the per-repo quota (`max_runs_per_repo = 20` / 3600 s,
  `terraform/ingestion/variables.tf:96-104`) and read caps, there is no visibility if
  costs drift (e.g. escalation firing more than expected, log volume growth, an
  added agent). Absence of a budget means overspend is discovered on the bill, not
  proactively.
- **Recommendation:** Add an `aws_budgets_budget` (monthly cost + optional
  Bedrock/usage budget) with an SNS/email action, and/or enable AWS Cost Anomaly
  Detection with a monitor scoped to the project's tags/service. Both are low-cost
  and IaC-friendly.
  ([AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html),
  [Cost Anomaly Detection](https://docs.aws.amazon.com/cost-management/latest/userguide/getting-started-ad.html))
- **Alternative solution:** _Managed budget vs. custom CloudWatch billing alarm_ —
  Pros of Budgets: purpose-built, tag/service filters, forecast alerts, near-zero
  cost. A CloudWatch `EstimatedCharges` billing alarm (us-east-1) is a lighter
  alternative but coarser (account total only, no tag scoping). Recommend Budgets +
  Anomaly Detection. Effort: **S**. Cross-pillar impact: operational-excellence +
  (spend observability).

### [Low] COST-F2 — Cost-allocation tagging is partial
- **Evidence:** `default_tags` set `Project` / `Env` / `Module` on the ingestion,
  ECR, security, runtime, and observability providers
  (`terraform/ingestion/providers.tf:36-42`), giving usable attribution. However the
  idempotency DynamoDB table explicitly drops its tags
  (`terraform/security/main.tf:70` — "tags retirés … évite tout appel TagResource"),
  there is no `Owner`/`CostCenter` dimension, and there is no evidence the keys are
  activated as **cost allocation tags** in Billing (only verifiable live).
- **Impact:** Cost reports can group by project/module but not by owner or
  cost-center; one resource is untagged, creating a small attribution blind spot.
- **Recommendation:** Keep `default_tags` uniform (let provider default_tags cover
  the DynamoDB table rather than removing tags), add an `Owner`/`CostCenter` tag, and
  activate the keys as cost-allocation tags in the payer account.
  ([Cost allocation tags](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html))
- **Alternative solution:** None needed — `default_tags` is the right mechanism;
  this is a completeness gap, not a design flaw.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| COST-01 | Pricing model fits usage (serverless/on-demand vs provisioned). | Met | `terraform/security/main.tf:55`; `terraform/ingestion/main.tf:238-246`; `terraform/runtime/main.tf:9` |
| COST-02 | No idle/over-provisioned resources; right-sizing. | Met | `terraform/ingestion/main.tf:190,194,220,224`; `terraform/ingestion/variables.tf:60,66`; `docagent/config.py:62-74` |
| COST-03 | Scale-to-zero / auto-stop for bursty workloads. | Met | `terraform/runtime/data.tf:59-63`; `terraform/runtime/main.tf:26-29` (idle 900 s / max-life 3600 s) |
| COST-04 | Storage lifecycle policies (tiering, expiry, log retention bounded). | Met | `terraform/ecr/main.tf:34-63`; `terraform/ingestion/main.tf:159-166`; `terraform/runtime/logs.tf:7`; `terraform/security/main.tf:65-68` |
| COST-05 | Cost allocation tags / attribution strategy. | Partial | `terraform/ingestion/providers.tf:36-42` (default_tags Project/Env/Module) vs `terraform/security/main.tf:70` (table tags removed); no Owner/CostCenter |
| COST-06 | Budgets/alerts or cost anomaly detection. | Missing | absent from `terraform/**` (see COST-F1) |
| COST-07 | Avoids expensive managed features when a cheaper fit exists. | Met | `scripts/agents/agents.json:4` (no KB/Memory/vector); `terraform/ingestion/waf.tf:218` (PriceClass_100); no NAT/CMK |
| COST-08 | Data transfer costs considered (cross-AZ/region/NAT). | Met | no NAT gateway (serverless); Bedrock in-region `docagent/config.py:80` (`BEDROCK_REGION` eu-central-1); CloudFront `PriceClass_100` `terraform/ingestion/waf.tf:218` |
| COST-09 | Ephemeral/dev environments torn down or scheduled. | N/A | fully serverless scale-to-zero — no always-on non-prod compute to schedule/tear down (idle cost ≈ negligible: secrets, on-demand table, log groups) |
| COST-10 | Observability cost bounded (retention, sampling). | Met | 14-day retention everywhere; EMF via stdout (no PutMetric API cost) `docagent/metrics.py`; WAF `sampled_requests_enabled` `terraform/ingestion/waf.tf` |
| COST-11 | Efficient resource use per unit of business value (proxy metric). | Met | `docagent/metrics.py` (Runs/DurationMs/FilesCommitted); `docagent/analyzer.py:126-176` (model tiering); dashboard `terraform/observability/main.tf:118-155` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Add `aws_budgets_budget` (monthly cost) + SNS action; enable Cost Anomaly Detection scoped to project tags (COST-F1). | S |
| P3 | Make `default_tags` uniform (restore DynamoDB tagging) and add `Owner`/`CostCenter`; activate cost-allocation tags in Billing (COST-F2). | S |
| P3 | Optionally add a Bedrock token/usage proxy metric (input tokens per run) to the dashboard to sharpen cost-per-run visibility. | S |

## Notes & assumptions
- Static audit: budget/anomaly absence is judged from IaC. A budget could
  theoretically exist at the org/payer account outside this repo — hence Confidence
  is **medium**, not high, on COST-06. Tag activation as cost-allocation tags and
  effective retention are only verifiable live.
- No `Critical`/`High` findings: worst-case runaway spend is structurally bounded by
  the per-repo quota, read caps, and Haiku-default model tiering, so cost risk stays
  Medium at most (per the pillar guidance to reserve Critical for unbounded spend).
- CloudFront + WAF (us-east-1 WebACL) were added since the shared inventory snapshot
  (`terraform/ingestion/waf.tf`); they add a modest fixed WAF + per-request cost but
  use the cheapest CloudFront tier and are justified as SEC-F1 defense-in-depth
  (cross-ref Security 02). CloudTrail multi-region trail (`observability/cloudtrail.tf`)
  adds minor cost (first trail free for management events; no data events enabled).
- COST-09 marked N/A rather than Missing: the workload has no persistent non-prod
  compute; scheduling teardown is inapplicable to a scale-to-zero serverless design.
