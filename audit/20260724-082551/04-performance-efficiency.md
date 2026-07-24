# Performance Efficiency — Audit

**Score:** 79/100  **Maturity:** 4 (Managed)  **Coverage:** 95%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Efficient use of compute/storage/network to meet performance needs and adapt as
demand/technology evolve: resource selection, data-access patterns, caching,
async/batching, connection/timeout tuning, and performance observability.

Cross-referenced (not scored here):
- Elasticity / capacity to absorb growth → **Scalability (11)**.
- Cost of the chosen resources (token cost, on-demand pricing) → **Cost Optimization (05)**.
- Availability under failure (retries, DLQ, idempotency) → **Reliability (03)**.

Static audit only (`live_aws = OFF`): runtime metrics (actual latency percentiles,
Lambda throttles, DynamoDB consumed capacity) are judged from IaC/code, not observed.

Grounded in the AWS Well-Architected Performance Efficiency pillar
([WAF userguide](https://docs.aws.amazon.com/wellarchitected/latest/userguide/waf.html)),
Lambda memory/CPU allocation guidance
([Lambda function memory](https://docs.aws.amazon.com/lambda/latest/dg/configuration-memory.html)),
and the DynamoDB Well-Architected Lens
([DynamoDB perf efficiency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-wal.html)).

## Strengths
- **Serverless + ARM64 everywhere**, with the heavy LLM work offloaded to AgentCore async so the worker frees its concurrency slot in ~1 s — _evidence: `terraform/ingestion/main.tf:186-210` (Lambdas `architectures = ["arm64"]`), `terraform/runtime/main.tf:18-24` (PUBLIC serverless runtime), `agent.py:78-104` (`add_async_task`)_
- **Model tiering (mechanical sympathy):** economical Haiku by default, deterministic escalation to Sonnet only for large contexts (>25 files or >400 KB) — _evidence: `docagent/analyzer.py:130-160` (`select_model`), `docagent/config.py:88-95`, `scripts/agents/agents.json:8-12`_
- **Data store fits access pattern:** DynamoDB on-demand, single-table `pk`, purely key-addressed (conditional `PutItem`, atomic `UpdateItem ADD`, `Query` scoped by `LeadingKeys`) — no `Scan`, no GSI churn — _evidence: `terraform/security/main.tf:55-75`, `scripts/lambdas/webhook-receiver/handler.py:171-190`, `227-241`_
- **Bounded resource use** across every layer: read caps, tree cap, escalation thresholds, API GW throttling, per-repo quota, SQS redrive, runtime idle/max-lifetime — _evidence: `docagent/config.py:60-70`, `terraform/ingestion/main.tf:277-283` (throttle 10 rps / burst 20)_
- **Payload tuned to the model context window:** `max_total_bytes` deliberately sized below ~200K-token window with headroom — _evidence: `docagent/config.py:52-66`_
- **Timeout tuning** on the Bedrock client (read 900 s, connect 60 s, adaptive retries, streaming) — _evidence: `docagent/analyzer.py:180-190`_

## Weaknesses / Findings

### [Medium] PERF-F1 — No prompt/response caching where it would help
- **Evidence:** `docagent/analyzer.py:178-192` (`_build_agent` — no cache-point config); `docagent/config.py` (no prompt-cache setting); inventory "no caching/prompt-caching".
- **Impact:** The large system prompt + output contract (`instructions.md` + `OUTPUT_CONTRACT`) is re-sent on every invocation as input tokens, adding latency and cost per run. Bedrock prompt caching can cut time-to-first-token and input-token spend for the stable prefix.
- **Recommendation:** Enable Bedrock prompt caching on the stable system-prompt prefix; keep per-repo context uncached (it is unique per run).
- **Alternative solution:** Cache the invariant prefix via a Bedrock cache checkpoint.
  - _Pros:_ lower latency + input-token cost on repeated runs; no architectural change.
  - _Cons:_ model/region support constraints; marginal benefit at low POC volume; cache TTL to reason about.
  - _Effort:_ S. _Cross-pillar impact:_ cost-optimization +, sustainability +.

### [Low] PERF-F2 — Sequential file reads + whole tarball held in memory
- **Evidence:** `docagent/orchestrator.py:196-206` (`{path: reader.read_file(path) for path in selected}` — serial comprehension); `docagent/repo_reader.py:39-66` (`extract_tarball_safely` loads `io.BytesIO(tar_bytes)` fully).
- **Impact:** Reads are serialized and the archive is fully materialized in memory. Bounded by caps (≤40 files, ≤1.2 MB), so impact is small; would matter for larger budgets.
- **Recommendation:** Acceptable at current caps. If caps grow, stream extraction and/or parallelize reads (note the shared byte budget makes naive parallelism stateful).
- **Alternative solution:** None required — current approach is appropriate for the bounded workload; the sequential byte-budget accounting is intentional and correct.

### [Low] PERF-F3 — Performance measured but no defined targets/SLOs
- **Evidence:** `docagent/metrics.py:24-52` (`DurationMs` EMF), `terraform/observability/main.tf` ("Durée de run" widget avg/p90) — no latency/throughput SLO threshold anywhere.
- **Impact:** Duration is observable but there is no target to alarm on; regressions in run latency go unnoticed until they become failures.
- **Recommendation:** Define a p90 run-duration objective and add a latency alarm on the `DurationMs` EMF metric.
- **Alternative solution:** None — small, additive change.

### [Low] PERF-F4 — Resource-utilization metrics not monitored
- **Evidence:** `terraform/observability/main.tf:34-120` — dashboards/alarms cover Invocations, Errors, SQS depth, DLQ, runtime errors, DurationMs; no Lambda `Throttles`/memory, no DynamoDB `ThrottledRequests`/consumed capacity.
- **Impact:** Throttling or under/over-sized memory would not surface; on-demand DynamoDB throttling during bursts would be invisible.
- **Recommendation:** Add Lambda `Throttles` + `ConcurrentExecutions` and DynamoDB throttle/consumed-capacity widgets/alarms.
- **Alternative solution:** None — additive observability.

### [Low] PERF-F5 — No load/performance benchmarking
- **Evidence:** `e2e/` provides dry-run + synthetic signed event (functional harness), not perf/load testing; inventory "pas de couverture mesurée".
- **Impact:** No baseline for latency/throughput under concurrent PRs; sizing (memory, concurrency, throttles) is chosen by reasoning, not measurement.
- **Recommendation:** Add a lightweight benchmark (e.g. Lambda Power Tuning for the Lambdas; a burst of synthetic events to observe queue drain + run duration).
- **Alternative solution:** None strictly required for a POC.

### [Low] PERF-F6 — boto3 clients recreated per operation (no reuse)
- **Evidence:** `scripts/lambdas/webhook-receiver/handler.py:161-166` (`_get_secret`), `171-190` (`_claim_idempotency`), `227-241` (`_increment_repo_counter`), `211-215` (`_enqueue`) each construct a fresh `boto3.client(...)`.
- **Impact:** Clients (and their connection pools) are not reused across the 2-3 AWS calls in a single invocation, adding minor init overhead per request. The HMAC secret itself is cached module-level (`_SECRET_CACHE`), which is good.
- **Recommendation:** Hoist boto3 clients to module scope so warm invocations reuse connections.
- **Alternative solution:** None — small refactor.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| PERF-01 | Compute type right-sized & appropriate | Met | `terraform/ingestion/main.tf:186-210` (arm64, 256 MB Lambdas); `terraform/runtime/main.tf:18-24` (serverless); `agent.py:78-104` (async offload); `docagent/analyzer.py:130-160` (model tiering) |
| PERF-02 | Data store choice fits access patterns | Met | `terraform/security/main.tf:55-75` (DynamoDB on-demand KV); SQS `terraform/ingestion/main.tf:8-27`; stateless agent (`agent.py` docstring) |
| PERF-03 | Query/index design avoids N+1, scans, hot partitions | Met | `handler.py:171-190` (conditional PutItem on `pk`), `227-241` (atomic ADD), `terraform/ingestion/main.tf:83-92` (`Query` scoped by `LeadingKeys`) — no Scan |
| PERF-04 | Caching where beneficial, with invalidation | Partial | Secret cache `handler.py:38,161-166`; GitHub App token reused ~1h; **no** Bedrock prompt caching (`analyzer.py:178-192`) — see PERF-F1 |
| PERF-05 | Async / batching for expensive/bursty work | Met | `agent.py:78-104` (async task); SQS decoupling `terraform/ingestion/main.tf:8-27`; worker non-blocking |
| PERF-06 | Timeouts, connection pooling, payload sizes tuned | Met | `analyzer.py:180-190` (read/connect timeouts, adaptive retries, streaming); `config.py:52-66` (payload caps); `ingestion/main.tf:18` (SQS visibility = worker_timeout+60). Minor: client reuse (PERF-F6) |
| PERF-07 | Concurrency/parallelism; no needless serialization | Partial | Infra concurrency: `ingestion/main.tf:264-270` (`maximum_concurrency`), async offload. But serial file reads + in-memory tarball `orchestrator.py:196-206`, `repo_reader.py:39-66` — see PERF-F2 |
| PERF-08 | Content/data close to consumers (edge/region) | N/A | Backend-only, webhook-driven workload; no distributable user-facing content to place at the edge. Single-region eu-central-1 is appropriate. Justified N/A. |
| PERF-09 | Performance targets defined and measured | Partial | Measured: `metrics.py:24-52` + dashboard p90; no defined SLO/target — see PERF-F3 |
| PERF-10 | Load/perf testing or benchmarking evidence | Missing | Only functional E2E harness (`e2e/`); no load/perf benchmark — see PERF-F5 |
| PERF-11 | Resource utilization monitored (CPU/mem/IO/throttles) | Partial | `observability/main.tf` covers invocations/errors/duration/queue; no throttles/memory/DDB-capacity — see PERF-F4 |
| PERF-12 | Bounded resource use (pagination, limits) | Met | `config.py:60-70` (read caps), `analyzer.py:130-160` (escalation thresholds), `ingestion/main.tf:277-283` (throttling), `handler.py:244-266` (per-repo quota), redrive `maxReceiveCount` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Enable Bedrock prompt caching on the stable system-prompt prefix (latency + token cost) | S |
| P2 | Define a p90 run-duration SLO and alarm on the `DurationMs` EMF metric | S |
| P2 | Add Lambda `Throttles`/`ConcurrentExecutions` + DynamoDB throttle/consumed-capacity to the dashboard/alarms | S |
| P3 | Hoist boto3 clients to module scope in the webhook Lambda for connection reuse | S |
| P3 | Add a lightweight benchmark (Lambda Power Tuning + synthetic burst) to validate sizing | M |

## Notes & assumptions
- Static audit: verdicts derive from code/IaC, not observed runtime metrics. The system was reportedly deployed/validated E2E, but no live metrics were consulted.
- PERF-08 marked `N/A` (excluded from the denominator) and justified: no distributable content served to geographically dispersed consumers; a single-region backend is the right fit.
- Score computation over 11 applicable criteria: Σ(credit×weight)=9.5 / Σ(weight)=12.0 → 79/100.
- No Critical/High findings; the workload is well-bounded and the compute/data choices are appropriate. Main headroom is caching (prompt caching) and closing the observability gap on utilization/SLOs.
- Cross-pillar: token-cost impact of missing prompt caching is scored under Cost Optimization (05); infra elasticity under Scalability (11); retry/idempotency/DLQ under Reliability (03).
