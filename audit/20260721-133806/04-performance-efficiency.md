# Performance Efficiency — Audit

**Score:** 75/100  **Maturity:** 4 (Managed)  **Coverage:** 75%  **Confidence:** medium
**Applicable:** yes

## Charter & scope

Assesses efficient use of compute/storage/network to meet performance requirements and adapt as demand/technology evolve: resource selection, data access patterns, caching, and performance observability. Elasticity mechanics are covered by Scalability (11), resource cost by Cost Optimization (05), availability-under-failure by Reliability (03) — noted where a boundary was crossed but not double-scored here.

## Strengths

- Two-tier LLM model selection (economical Haiku by default, Sonnet escalation only for large/complex repos) is a pure, deterministic function driven by selected-context size — right-sizes the expensive resource (LLM inference) to the workload — _evidence: `docagent/analyzer.py:124-156`, `docagent/config.py:90-95`_
- All AWS compute is serverless and ARM64/Graviton (Lambda `webhook`/`worker`, Bedrock AgentCore runtime), matching the bursty, event-driven, scale-to-zero nature of the workload — _evidence: `terraform/ingestion/main.tf:171-217`, `terraform/runtime/main.tf:3-44`_
- Data access is exclusively single-item point operations (`PutItem`/`UpdateItem`/`DeleteItem`/conditional writes) on a `PAY_PER_REQUEST` DynamoDB table keyed by `pk` — no scans, no secondary indexes needed, billing matches unpredictable low-volume traffic — _evidence: `terraform/security/main.tf:57-79`, `docagent/idempotency.py:22-74`, `scripts/lambdas/webhook-receiver/handler.py:140-213`_
- Fully asynchronous pipeline: webhook Lambda enqueues to SQS and returns immediately (15s timeout); worker Lambda makes a single non-blocking `InvokeAgentRuntime` call and returns (60s timeout, documented as intentionally short because the call doesn't block on the agent run) — decouples the expensive, variable-duration LLM/doc-gen work from the request path — _evidence: `terraform/ingestion/variables.tf:41-44`, `scripts/lambdas/worker-dispatcher/handler.py:46-77`_
- Deliverables (Markdown + `.drawio` diagrams) are batched into a **single** Git commit via the Git Data API (one `create_tree`/`create_commit`/`update_ref`), regardless of file count, instead of one commit per file — _evidence: `docagent/committer.py:39-83`_
- Context sent to the LLM is tightly bounded on every axis (file count, per-file bytes, total bytes, selected-file count), calibrated to stay under the model context window — controls both latency and cost, and prevents pathological large-repo cases — _evidence: `docagent/config.py:55-68`, `docagent/repo_reader.py:86-135`_
- API Gateway stage throttling (20 burst / 10 rps), SQS worker concurrency cap (5), `maxReceiveCount=2`→DLQ, and a DynamoDB-backed per-repo/per-window run quota bound the system's worst-case resource consumption end-to-end — _evidence: `terraform/ingestion/main.tf:226-229,257-260`, `terraform/ingestion/variables.tf:53-63`, `scripts/lambdas/webhook-receiver/handler.py:184-213`_
- Latency is actually measured: EMF metric `DurationMs` (with `Outcome` dimension) is emitted per run and visualized as both average and p90 on the CloudWatch dashboard — _evidence: `docagent/metrics.py:18-49`, `terraform/observability/main.tf:122-134`_
- Explicit timeouts are set at every network boundary: Bedrock client (`read_timeout=900`, `connect_timeout=60`, adaptive retries), GitHub HTTP calls (`timeout=60`), Lambda function timeouts — _evidence: `docagent/analyzer.py:176-181`, `docagent/github_client.py:63`, `terraform/ingestion/main.tf:177,205`_

## Weaknesses / Findings

### [Medium] PERF-F1 — No performance target (SLO) defined for run latency, only measured
- **Evidence:** `docagent/metrics.py:18-49` (DurationMs emitted, no threshold), `terraform/observability/main.tf:41-70` (alarms exist only for Lambda `Errors` count and DLQ depth — none on `DurationMs`/p90)
- **Impact:** The team has visibility into latency trends but no documented target (e.g. "p90 doc-gen run < N minutes") and no alarm fires when latency degrades — regressions are only caught by manual dashboard inspection.
- **Recommendation:** Define an explicit latency SLO (e.g. p90 end-to-end run duration) in README/ARCHITECTURE.md and add a CloudWatch alarm on the `DurationMs` p90 EMF metric.
- **Alternative solution:** None — Medium severity, straightforward operational addition, no architectural trade-off.

### [Medium] PERF-F2 — Resource-utilization monitoring covers invocations/errors/queue depth but not throttles or concurrency pressure
- **Evidence:** `terraform/observability/main.tf:24-160` (dashboard/alarms: `Invocations`, `Errors`, SQS `ApproximateNumberOfMessagesVisible` only)
- **Impact:** No alarm/widget for Lambda `Throttles`, `ConcurrentExecutions` (vs. the `worker_max_concurrency=5` cap), or DynamoDB throttled requests. Under load, the worker's SQS-scaling concurrency cap could be silently saturated (backlog growing in `main` queue) without a distinct throttle signal — only inferred indirectly from queue depth.
- **Recommendation:** Add `AWS/Lambda Throttles` and `ConcurrentExecutions` widgets/alarms for both functions, and a DynamoDB `ThrottledRequests`/`SystemErrors` widget.
- **Alternative solution:** None — Medium severity, additive monitoring, no trade-off.

### [Low] PERF-F3 — Sequential (non-concurrent) file reads and Git blob creation
- **Evidence:** `docagent/orchestrator.py:97` (`files = {path: reader.read_file(path) for path in selected}` — sequential dict comprehension over up to 40 files), `docagent/committer.py:71-81` (one `create_blob` HTTP call per output file, in a sequential `for` loop)
- **Impact:** Bounded today (≤40 local file reads, and the committed-file count is small — a handful of Markdown/`.drawio` outputs), so the latency cost is currently minor. But the blob-creation loop makes one GitHub API round-trip per output file with no concurrency, and this doesn't parallelize as either cap grows. Self-acknowledged in the repo's own `AUDIT.md` ("lectures séquentielles").
- **Recommendation:** Parallelize local file reads (bounded thread pool) and/or batch blob creation where the GitHub API allows it; low priority given current caps.
- **Alternative solution:** None — Low severity, bounded impact under current config.

### [Low] PERF-F4 — No HTTP connection reuse/pooling for the GitHub client
- **Evidence:** `docagent/github_client.py:58-69` (`urllib.request.urlopen` per call, no persistent `Session`/connection pool)
- **Impact:** Each GitHub API call (including the sequential per-file blob-creation calls in PERF-F3) pays a fresh TCP+TLS handshake instead of reusing a keep-alive connection, adding latency overhead proportional to call count.
- **Recommendation:** Wrap calls in a pooled HTTP client (`urllib3.PoolManager` or `requests.Session`) reused across the client's lifetime; the module already isolates transport in `_http()`, making this a localized change.
- **Alternative solution:** None — Low severity, no architectural trade-off; a design comment in the module explains `urllib` was chosen to avoid a third-party dependency, which is a reasonable image-size/cost trade-off to weigh against this latency cost.

### [Low] PERF-F5 — No caching for LLM prompts, and no load/benchmark testing evidence
- **Evidence:** `docagent/analyzer.py:170-184` (no Bedrock prompt-caching configuration on the `BedrockModel`); no load-test scripts found under `scripts/agents/agent-technical-doc/e2e/` or `tests/`
- **Impact:** The system prompt + output contract (`instructions.md` + `OUTPUT_CONTRACT`, a non-trivial fixed block) is resent in full on every invocation without prompt caching, adding avoidable input-token latency/cost on repeated runs. Separately, there is no evidence of load or throughput benchmarking (single-repo, single-run local/E2E tests only), so behavior under concurrent PR bursts (up to `worker_max_concurrency=5`) is unverified.
- **Recommendation:** Enable Bedrock prompt caching for the static system-prompt/output-contract portion; add a lightweight load test that drives 5+ concurrent SQS messages through the worker path in a non-prod environment.
- **Alternative solution:** None — Low severity for a POC-stage system; reasonable to defer until traffic volume justifies it.

## Criteria grid

| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| PERF-01 | Compute type right-sized & appropriate (serverless/containers/instances) for the workload. | Met | `terraform/ingestion/main.tf:171-217`, `terraform/runtime/main.tf:3-44`, `docagent/analyzer.py:124-156` |
| PERF-02 | Data store choice fits access patterns (SQL/NoSQL/object/cache). | Met | `terraform/security/main.tf:57-79`, `terraform/ingestion/main.tf:12-23` |
| PERF-03 | Query/index design avoids N+1, full scans, hot partitions. | Met | `docagent/idempotency.py:22-74`, `scripts/lambdas/webhook-receiver/handler.py:140-213`, `terraform/ingestion/main.tf:77-92` |
| PERF-04 | Caching used where beneficial (CDN, app cache, DB cache) with invalidation. | Partial | `scripts/lambdas/webhook-receiver/handler.py:30-137` (in-process secret cache); no CDN/DB cache/prompt cache found |
| PERF-05 | Async / batching for expensive or bursty work. | Met | `terraform/ingestion/variables.tf:41-44`, `scripts/lambdas/worker-dispatcher/handler.py:46-77`, `docagent/committer.py:39-83` |
| PERF-06 | Timeouts, connection pooling, and payload sizes tuned. | Partial | `docagent/analyzer.py:176-181`, `docagent/github_client.py:63` (timeouts present); `docagent/github_client.py:58-64` (no pooling); `docagent/config.py:55-68` (payload bounds) |
| PERF-07 | Concurrency/parallelism used where it helps; no needless serialization. | Partial | `terraform/ingestion/variables.tf:53-57` (bounded worker concurrency, appropriate); `docagent/orchestrator.py:97`, `docagent/committer.py:71-81` (sequential reads/blob creation) |
| PERF-08 | Content/data placed close to consumers (edge/region) where relevant. | N/A | No user-facing content delivery — generated docs are committed to the target Git repo and consumed via GitHub's own UI, not served by this system; single-region backend (eu-central-1) is not a latency-sensitive edge case here |
| PERF-09 | Performance targets defined and measured (latency/throughput SLIs). | Partial | Measured: `docagent/metrics.py:18-49`, `terraform/observability/main.tf:122-134`; no documented target/SLO, no alarm on latency |
| PERF-10 | Load/perf testing or benchmarking evidence. | Missing | No load-test scripts found in `scripts/agents/agent-technical-doc/e2e/` or `tests/` |
| PERF-11 | Resource utilization monitored (CPU/mem/IO/throttles). | Partial | `terraform/observability/main.tf:24-160` (Invocations/Errors/SQS depth covered); no Throttles/ConcurrentExecutions/DynamoDB-throttle metrics |
| PERF-12 | Bounded resource use (pagination, limits) to avoid pathological cases. | Met | `docagent/config.py:55-68`, `docagent/repo_reader.py:86-135`, `terraform/ingestion/main.tf:226-229,257-260`, `terraform/ingestion/variables.tf:41-63` |

## Prioritized improvements

| priority | action | effort |
|----------|--------|--------|
| P1 | Define an explicit latency SLO and add a CloudWatch alarm on the `DurationMs` p90 EMF metric (PERF-F1) | S |
| P1 | Add Lambda `Throttles`/`ConcurrentExecutions` and DynamoDB throttle metrics to the observability dashboard/alarms (PERF-F2) | S |
| P2 | Enable Bedrock prompt caching for the static system-prompt/output-contract block (PERF-F5) | S |
| P2 | Add a bounded-concurrency load test exercising `worker_max_concurrency=5` in a non-prod environment (PERF-F5) | M |
| P3 | Parallelize local file reads and Git blob creation, or switch the GitHub client to a pooled HTTP transport (PERF-F3, PERF-F4) | M |

## Notes & assumptions

- Scored against the on-disk working tree including the uncommitted `ingestion/main.tf` diff (worker IAM narrowed to `sqs:ReceiveMessage`/`sqs:DeleteMessage`), which has no performance-pillar effect.
- Coverage estimate (~75%) reflects deep reads of `selection.py`, `repo_reader.py`, `analyzer.py`, `config.py`, `idempotency.py`, `github_client.py`, `retry.py`, `committer.py`, `metrics.py`, both Lambda handlers, and the `ingestion`/`security`/`runtime`/`observability` Terraform modules. `orchestrator.py`, `doc_builder.py`, `drawio.py`, `comments.py`, `paths.py`, `correlation.py`, `payload.py`, `secrets.py`, `github_auth.py`, and the `roles`/`ecr`/`bootstrap` Terraform modules were not fully read (grepped or skipped) — none surfaced as performance-relevant via the context pack or the reads performed, but a full pass could not be guaranteed exhaustive in the time available.
- Lambda `memory_size` is hardcoded at 256MB for both `webhook` and `worker` with no documented power-tuning rationale; not scored as a standalone finding (PERF-01 kept Met given the overall right-sizing story around serverless/model selection is strong) but flagged here as a minor gap — low risk given the worker's non-blocking, sub-second workload.
- `terraform/ingestion/main.tf` grants `dynamodb:Query` (`RateLimitQuery` statement, condition on `LeadingKeys`) to the webhook role, but no code path in `scripts/lambdas/webhook-receiver/handler.py` issues a `Query` call — all access observed is `PutItem`/`UpdateItem`. This over-grant is a least-privilege (Security pillar) concern, not scored here, but it does confirm the app's actual data-access pattern is point-lookup only (reinforces PERF-03 = Met).
- No live AWS calls were made (`live_aws=OFF` per this run); verdicts rely entirely on static evidence.
