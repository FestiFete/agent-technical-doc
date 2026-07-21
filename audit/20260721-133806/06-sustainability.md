# Sustainability — Audit

**Score:** 80/100  **Maturity:** 4 (Managed)  **Coverage:** 90%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Assesses environmental impact of the workload: utilization/scale-to-zero, energy-efficient compute (Graviton/serverless), managed vs self-managed infra, data minimization/retention, algorithmic/processing efficiency, batching vs polling, region choice, storage tiering, idle test/dev environments, and proportionate observability volume. Dollar cost is out of scope (→ Cost Optimization, pillar 05); raw latency/throughput is out of scope (→ Performance Efficiency, pillar 04) — this review looks only at the resource-waste dimension of choices that overlap those pillars.

## Strengths
- Fully serverless, event-driven pipeline with no always-on compute anywhere in the stack: API Gateway HTTP API → Lambda `webhook` → SQS → Lambda `worker` → Bedrock AgentCore Runtime. No `aws_instance`, `aws_nat_gateway`, `aws_db_instance`, `aws_elasticache*`, `aws_ecs_service`, `aws_eks_cluster`, or load balancer resources exist anywhere in the Terraform tree (repo-wide grep, zero matches) — _evidence: `documentation/terraform/ingestion/main.tf`, `documentation/terraform/runtime/main.tf`_
- ARM64/Graviton used for 100% of custom compute: both Lambdas and the AgentCore runtime container — _evidence: `documentation/terraform/ingestion/main.tf:170`, `documentation/terraform/ingestion/main.tf:197`, `documentation/scripts/agents/agent-technical-doc/Dockerfile:1`_
- Bedrock AgentCore Runtime configured with a bounded idle-session timeout and max lifetime, so compute is released rather than kept warm indefinitely — _evidence: `documentation/terraform/runtime/data.tf:55-56` (`idle_timeout = 900`, `max_lifetime = 3600`), wired at `documentation/terraform/runtime/main.tf:24-25`_
- DynamoDB idempotency table is `PAY_PER_REQUEST` (no provisioned/idle capacity) with TTL-based purge — _evidence: `documentation/terraform/security/main.tf:57-58` (billing_mode), `:66-68` (ttl block), default 30-day TTL at `documentation/terraform/security/variables.tf:16-19`_
- Repository content is fetched as a single bounded tarball at a specific ref (not a full `git clone` with history), with capped file selection (`MAX_SELECTED_FILES=40`, `MAX_FILE_BYTES=80000`, `MAX_TOTAL_BYTES=1200000`) and a cheap default model (Haiku) with escalation to a larger model only for bigger repos — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/github_client.py:103-106` (tarball download), `documentation/scripts/agents/agent-technical-doc/docagent/config.py:66-68` (byte/file caps), `documentation/scripts/agents/agents.json` (`MODEL_ID`/`MODEL_ID_ESCALATION`/`MODEL_ESCALATION_MAX_FILES`/`MODEL_ESCALATION_MAX_BYTES`)_
- SQS decouples webhook ingestion from worker processing (async, event-driven consumption via Lambda event source mapping, not a polling loop) — _evidence: `documentation/terraform/ingestion/main.tf:222-229`_
- CloudWatch log retention is explicitly bounded (14 days) for every log group in the stack — no indefinite-retention log groups found — _evidence: `documentation/terraform/ingestion/variables.tf:65-69`, `documentation/terraform/runtime/variables.tf:39-42`, applied at `documentation/terraform/ingestion/main.tf:159-165` and `documentation/terraform/runtime/logs.tf:4-8`_
- ECR lifecycle policy expires untagged images after 1 day and caps tagged image retention (default 10) — bounded image storage growth — _evidence: `documentation/terraform/ecr/main.tf:23-46`, default at `documentation/terraform/ecr/variables.tf:22-26`_
- SQS queues have bounded message retention (main: 4 days, DLQ: 14 days), avoiding unbounded queue growth — _evidence: `documentation/terraform/ingestion/main.tf:8-10` (dlq), `:14-16` (main)_
- Single POC environment, no separate always-on dev/staging stacks found in the Terraform tree; everything scales to zero on idle by construction (Lambda, SQS, API GW, DynamoDB on-demand, AgentCore idle timeout) — _evidence: `documentation/terraform/shared.tfvars` (`environment = "POC"`, single environment), `documentation/scripts/agents/agents.json` (single agent entry)_

## Weaknesses / Findings

### [Low] SUS-F1 — Terraform state S3 bucket has versioning enabled with no lifecycle rule to expire noncurrent versions
- **Evidence:** `documentation/terraform/bootstrap/main.tf:34-39` (`aws_s3_bucket_versioning` "Enabled", no accompanying `aws_s3_bucket_lifecycle_configuration`)
- **Impact:** Every `terraform apply` across 7 modules adds a new state object version that is retained forever. State files are small, so the absolute waste is negligible, but it is unbounded by design and contradicts the data-minimization pattern applied everywhere else in this repo (SQS/DynamoDB/CW logs/ECR all have explicit retention limits).
- **Recommendation:** Add an `aws_s3_bucket_lifecycle_configuration` rule that expires noncurrent state versions after e.g. 90 days.
- **Alternative solution:** None — Low severity, effort is trivial (a few lines of HCL), no meaningful cross-pillar trade-off.

### [Low] SUS-F2 — Region choice (`eu-central-1`) has no documented sustainability rationale
- **Evidence:** `documentation/terraform/shared.tfvars:15` (`aws_region = "eu-central-1"`, hardcoded and identical across all 7 modules' backends); no mention of carbon/region trade-offs found in `documentation/README.md` (grepped for region/carbon/RGPD/GDPR keywords, no sustainability-specific rationale returned — only project defaults)
- **Impact:** `eu-central-1` (Frankfurt) is a reasonable EU-resident choice for data-locality/latency reasons, but the repo shows no evidence that sustainability (grid carbon intensity) was weighed against alternative EU regions when the region was picked. This is a low-impact criterion at POC scale and workload is tiny (event-driven, low request volume).
- **Recommendation:** If/when the workload scales or a region change is otherwise on the table, document the trade-off between `eu-central-1` and lower-carbon-intensity EU regions as part of that decision; not worth a dedicated migration today given the workload's small footprint.
- **Alternative solution:** None — Low severity; a region migration is disproportionate effort for a POC-scale event-driven workload with no measured environmental impact data to justify it.

### [Info] SUS-F3 — Local E2E smoke-check script polls with a `while True` + `sleep` loop
- **Evidence:** `documentation/scripts/agents/agent-technical-doc/e2e/smoke_check.py:82-93`
- **Impact:** This is a local developer/CI convenience script (not part of deployed infrastructure), so its resource footprint is confined to whoever runs it manually; no production waste. Flagged for completeness only.
- **Recommendation:** No action needed; noted as informational since the pillar charter calls out polling-vs-event-driven patterns specifically.
- **Alternative solution:** None — Info-level, out of production scope.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SUS-01 | High utilization; scale-to-zero / demand-matched capacity (no idle burn). | Met | `documentation/terraform/runtime/data.tf:55-56`; `documentation/terraform/security/main.tf:57-58`; no `aws_instance`/`aws_nat_gateway`/`aws_db_instance`/`aws_ecs_service` found repo-wide |
| SUS-02 | Energy-efficient compute (ARM/Graviton, serverless) where feasible. | Met | `documentation/terraform/ingestion/main.tf:170,197`; `documentation/scripts/agents/agent-technical-doc/Dockerfile:1` |
| SUS-03 | Managed services preferred over self-managed always-on infrastructure. | Met | `documentation/terraform/ingestion/main.tf` (Lambda, API GW, SQS); `documentation/terraform/security/main.tf` (Secrets Manager, DynamoDB); `documentation/terraform/runtime/main.tf` (`awscc_bedrockagentcore_runtime`) — no self-hosted servers/containers found |
| SUS-04 | Data minimization: retention/lifecycle limits, no needless data duplication. | Partial | Bounded: `documentation/terraform/ingestion/main.tf:8-10,14-16` (SQS), `security/main.tf:66-68` (DynamoDB TTL), `ecr/main.tf:23-46` (ECR lifecycle); gap: `documentation/terraform/bootstrap/main.tf:34-39` (S3 state versioning, no expiry) |
| SUS-05 | Efficient algorithms/bounded processing (no wasteful recompute/polling). | Met | `documentation/scripts/agents/agent-technical-doc/docagent/github_client.py:103-106`; `docagent/config.py:66-68`; `documentation/scripts/agents/agents.json` (model escalation thresholds) |
| SUS-06 | Batching/async to smooth utilization vs constant polling. | Met | `documentation/terraform/ingestion/main.tf:222-229` (SQS→Lambda event source mapping, async decoupling) |
| SUS-07 | Region choice considers sustainability where flexible. | Missing | `documentation/terraform/shared.tfvars:15`; no sustainability rationale documented in `documentation/README.md` |
| SUS-08 | Right-sized storage tiers; cold data on efficient tiers. | Partial | `security/main.tf:57-58` (DynamoDB on-demand, no over-provisioning); `ecr/main.tf:23-46` (ECR lifecycle bounds image storage); gap: S3 state bucket has no tiering/lifecycle for noncurrent versions (`bootstrap/main.tf:34-39`) — no other bulk/cold data stores exist in this architecture |
| SUS-09 | Test/dev environments not left running idle. | Met | `documentation/terraform/shared.tfvars` (single `environment = "POC"`, no parallel always-on dev/staging stack found); `documentation/terraform/runtime/data.tf:55` (idle auto-suspend) |
| SUS-10 | Observability/log volume proportionate (no excessive retention). | Met | `documentation/terraform/ingestion/variables.tf:65-69`; `documentation/terraform/runtime/variables.tf:39-42` (both default 14 days, applied everywhere) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P3 | Add an `aws_s3_bucket_lifecycle_configuration` on the Terraform state bucket to expire noncurrent object versions after ~90 days (SUS-04/SUS-08). | S |
| P3 | Document the region-choice rationale (data residency vs. carbon intensity trade-off among EU regions) for `eu-central-1`, revisit only if/when scale changes the calculus (SUS-07). | S |

## Notes & assumptions
- Static-only review (`live_aws=OFF`); no live carbon-intensity or utilization telemetry was queried — verdicts are based solely on the Terraform/code configuration as committed/uncommitted on disk (including the uncommitted `ingestion/main.tf` IAM narrowing, which does not affect this pillar).
- Region-carbon-intensity claims (SUS-07 discussion) reflect general AWS sustainability guidance/domain knowledge about relative grid carbon intensity across EU regions, not a specific cited AWS document — no AWS Documentation MCP lookup was available/performed to attach a doc URL; treat as directional, not authoritative.
- SUS-08 ("right-sized storage tiers") has limited applicability here: the workload has no data-lake/bulk-cold-storage use case (documentation output is committed to the source Git repo, not stored in S3), so the criterion is scored primarily against the two storage resources that do exist (DynamoDB, S3 state bucket) rather than a tiering strategy across large datasets.
- `terraform validate`/`fmt` were not re-run by this sub-agent (already captured once in the shared context pack); no functional issues affecting sustainability verdicts were introduced by the known cosmetic `terraform fmt` diff in `ingestion/main.tf`.
- Coverage is 90% rather than 100% because SUS-07's "considers sustainability where flexible" partly depends on unstated team/organizational constraints (e.g., customer data-residency requirements) that aren't visible in the repo and were not assumed either way.
