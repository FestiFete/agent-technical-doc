# Scalability — Audit

**Score:** 73/100  **Maturity:** 3 (Defined)  **Coverage:** 90%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Assess the ability to handle growth in load/data/users gracefully: horizontal scaling, statelessness, elasticity, partitioning/sharding, bottleneck avoidance, and load management. Excludes per-request efficiency (Performance Efficiency), failure recovery/redundancy (Reliability), and loose coupling (Decoupling) — cross-referenced where relevant.

## Strengths
- Ingestion pipeline is decoupled via SQS with a DLQ, providing queue-based load leveling and buffering under burst — _evidence: `documentation/terraform/ingestion/main.tf:6-23`_
- Per-repository sliding-window rate limiting (atomic DynamoDB counter, `MAX_RUNS_PER_REPO`/`RATE_WINDOW_SECONDS`) protects downstream capacity from a single noisy repo — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:174-213`_
- Agent runtime is explicitly stateless (no AgentCore Memory/Knowledge Base); each run uses a fresh temp workdir and a fresh clone, with idempotency externalized to DynamoDB rather than kept in-process — _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:17-18`, `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:216`_
- DynamoDB idempotency table uses on-demand capacity (`PAY_PER_REQUEST`) with a high-cardinality partition key (`repo#pr#sha` / `repo#pr#comment_id`), avoiding both capacity planning and hot-partition risk — _evidence: `documentation/terraform/security/main.tf:57-65`, `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py:1-4`, `documentation/scripts/lambdas/webhook-receiver/handler.py:244`_
- Worker Lambda classifies errors as transient vs. permanent and only re-raises transient ones for SQS retry, with an internal exponential-backoff helper for idempotent sub-operations — _evidence: `documentation/scripts/lambdas/worker-dispatcher/handler.py:25-28,71-77`, `documentation/scripts/agents/agent-technical-doc/docagent/retry.py:53-82`_
- Per-invocation resource caps (`MAX_FILES`, `MAX_TOTAL_BYTES`, etc.) bound memory/context growth regardless of target repo size — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/config.py:65-68`_

## Weaknesses / Findings
### [Medium] SCAL-F1 — Worker concurrency hard-capped at 5, shared across all repos/PRs
- **Evidence:** `documentation/terraform/ingestion/variables.tf:53-57`, `documentation/terraform/ingestion/main.tf:220-229`
- **Impact:** `worker_max_concurrency` defaults to 5 and is the single system-wide concurrency budget for every allowed repository. As usage grows (more repos in the allowlist, more simultaneous PR activity), messages queue in SQS rather than processing in parallel, inflating latency; sustained bursts beyond capacity risk exhausting `max_receive_count = 2` (`documentation/terraform/ingestion/main.tf:21`) before enough retries occur, landing legitimate work in the DLQ.
- **Recommendation:** Treat the value as a tuned/environment-specific parameter (already is, via `var.worker_max_concurrency`), document its relationship to actual AgentCore/Bedrock concurrent-session quotas, and add an alarm on SQS backlog age so capacity increases are made before user-visible delay, not after.
- **Alternative solution:** Raise `maximum_concurrency` incrementally under load testing once Bedrock AgentCore/model quotas are confirmed sufficient; for stronger isolation, shard by repo/org across multiple queues so one busy repo cannot starve others. Pros: removes the single global throttle point. Cons: sharding adds routing/ops complexity. Effort: S (raise value) / M (sharding). Cross-pillar: Cost Optimization (higher concurrency raises Bedrock spend), Reliability (backlog/DLQ behavior).

### [Medium] SCAL-F2 — No monitoring of scaling headroom (Lambda throttles/concurrency, SQS backlog)
- **Evidence:** `documentation/terraform/observability/main.tf:24-69` (only `dlq_not_empty`, `worker_errors`, `webhook_errors` alarms defined — no `Throttles`, `ConcurrentExecutions`, or SQS `ApproximateAgeOfOldestMessage`/`ApproximateNumberOfMessagesVisible` alarms), `documentation/AUDIT.md:22` (acknowledges "plafonds = quota Bedrock" qualitatively, without quantification)
- **Impact:** The team has no early warning before hitting AWS Lambda concurrent-execution limits, Bedrock AgentCore session concurrency limits, or a growing SQS backlog — these only become visible after failures accumulate in the DLQ.
- **Recommendation:** Add CloudWatch alarms for Lambda `Throttles`/`ConcurrentExecutions` on both `webhook` and `worker` functions, and SQS `ApproximateAgeOfOldestMessage` on the main queue; document known AWS service quotas and current headroom vs. expected peak.
- **Alternative solution:** None — this is a monitoring gap, not an architectural trade-off. Effort: S.

### [Low] SCAL-F3 — No load testing or capacity model beyond design-time reasoning
- **Evidence:** absence of load-test tooling/results — `documentation/scripts/agents/agent-technical-doc/e2e/` contains only `local_run.py`, `smoke_check.py`, `harness.py` (functional/local, not load tests); no `locust`/`k6`/`artillery` config found in the repository.
- **Impact:** Whether `worker_max_concurrency = 5`, the API Gateway throttle (`throttling_burst_limit = 20` / `throttling_rate_limit = 10`, `documentation/terraform/ingestion/main.tf:257-260`), and SQS buffering actually hold up under realistic concurrent PR-comment bursts is unverified.
- **Recommendation:** Run a synthetic load test simulating N concurrent webhook deliveries end-to-end (API GW → SQS → worker → AgentCore) to validate the pipeline before widening the repo allowlist or usage volume.
- **Alternative solution:** None — this is a verification exercise, not a design change. Effort: M.

### [Low] SCAL-F4 — Per-run temp working directory is never explicitly cleaned up
- **Evidence:** `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:216` (`tempfile.mkdtemp(prefix="docagent-")`); no matching `shutil.rmtree`/`TemporaryDirectory` cleanup found in `orchestrator.py`, `agent.py`, or the rest of `docagent/`.
- **Impact:** If the underlying AgentCore compute is reused across multiple invocations/sessions (typical for warm-start optimization in serverless-like platforms), repeated shallow clones accumulate on local disk across runs on the same host — a per-instance state leak that could eventually cause disk-exhaustion failures under sustained throughput, undermining safe instance reuse at scale.
- **Recommendation:** Use `tempfile.TemporaryDirectory()` as a context manager, or add an explicit `shutil.rmtree(wd, ignore_errors=True)` in a `finally` block around the run.
- **Alternative solution:** None — straightforward defensive fix. Effort: S.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SCAL-01 | Stateless compute enabling horizontal scale-out. | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:17-18`, `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:216` |
| SCAL-02 | Auto-scaling / on-demand elasticity configured for variable load. | Partial | `documentation/terraform/security/main.tf:59` (DynamoDB on-demand, Met); `documentation/terraform/ingestion/variables.tf:53-57` (worker capped at 5, static ceiling) |
| SCAL-03 | Data layer scales (partitioning/sharding, read replicas, on-demand capacity). | Met | `documentation/terraform/security/main.tf:57-79` |
| SCAL-04 | No single-threaded/singleton bottleneck on the hot path. | Partial | `documentation/terraform/ingestion/main.tf:220-229`, `documentation/terraform/ingestion/variables.tf:53-57` |
| SCAL-05 | Back-pressure / rate limiting / queue buffering under surge. | Met | `documentation/terraform/ingestion/main.tf:6-23,252-261`, `documentation/scripts/lambdas/webhook-receiver/handler.py:174-213` |
| SCAL-06 | Partition keys avoid hot spots (good cardinality/distribution). | Met | `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py:1-4`, `documentation/scripts/lambdas/webhook-receiver/handler.py:179-181,244` |
| SCAL-07 | Statelessness of sessions (externalized session/cache). | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:17-18`, `documentation/terraform/security/main.tf:57-65` |
| SCAL-08 | Concurrency limits & downstream protection to prevent overload. | Met | `documentation/terraform/ingestion/main.tf:226-228`, `documentation/scripts/lambdas/worker-dispatcher/handler.py:25-28,71-77`, `documentation/scripts/agents/agent-technical-doc/docagent/retry.py:53-82` |
| SCAL-09 | Scaling limits/quotas understood and headroom exists. | Partial | `documentation/AUDIT.md:22` (qualitative only); `documentation/terraform/observability/main.tf:24-69` (no throttle/concurrency alarms) |
| SCAL-10 | Load tested / capacity model beyond current usage. | Missing | absence — no load-test artifacts under `documentation/scripts/agents/agent-technical-doc/e2e/` |
| SCAL-11 | No unbounded in-memory growth or per-instance state that blocks scaling. | Partial | `documentation/scripts/agents/agent-technical-doc/docagent/config.py:65-68` (bounded, Met); `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:216` (temp workdir not cleaned, Partial) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add CloudWatch alarms for Lambda Throttles/ConcurrentExecutions and SQS backlog age; document known AWS quotas vs. expected peak | S |
| P2 | Validate/raise `worker_max_concurrency` against measured Bedrock AgentCore concurrent-session capacity | S |
| P3 | Run an end-to-end synthetic load test of the ingestion pipeline before widening usage/allowlist | M |
| P4 | Clean up per-run temp working directory (`TemporaryDirectory`/`shutil.rmtree`) | S |

## Notes & assumptions
- `live_aws` is OFF for this run: actual AWS service quotas (Lambda account concurrency, Bedrock AgentCore concurrent sessions, Bedrock model TPS/RPM) could not be verified live; SCAL-09 verdict is based solely on what is documented/monitored in-repo, not on the true headroom, which may in fact be adequate.
- The `awscc_bedrockagentcore_runtime` resource (`documentation/terraform/runtime/main.tf`) exposes no explicit concurrency/throttle setting, so the AgentCore-side concurrency ceiling is governed by AWS defaults not visible in this codebase — flagged as a coverage limitation, not a finding.
- Scored against the 11-criterion SCAL grid in this run's charter; the prior run (`audit/20260720-000000/11-scalability.md`, 79/100) used only 3 informal criteria and is not directly comparable — its findings were independently re-verified here rather than carried forward.
- DynamoDB single hash-key design (`pk`) is adequate at current scale; no sort key or GSI exists, which is fine for the current access pattern (dedup lookups by exact key) but was not stress-tested for very high write throughput on a single logical entity.
