# Performance Efficiency — Audit

**Score:** 75/100  **Maturity:** 4 (Managed)  **Coverage:** 80%  **Confidence:** medium
**Applicable:** yes

## Charter & scope

Assesses efficient use of compute/storage/network to meet performance requirements and adapt as demand/technology evolve: resource selection, data access patterns, caching, and performance observability. Elasticity mechanics are covered by Scalability (11), resource cost by Cost Optimization (05), availability-under-failure by Reliability (03) — noted where a boundary is crossed but not double-scored here.

## Delta since the prior run (audit/20260721-133806/04-performance-efficiency.md, score 75/100)

Re-verified every criterion independently against the current committed state (`develop`, working tree has an in-progress uncommitted `ingestion/main.tf` diff per `git status` — read as the effective on-disk state, no perf-relevant delta found in it beyond what's already described below). All prior findings (PERF-F1..F5) were re-checked file-by-file and **still hold** — no CloudWatch alarm exists on `DurationMs`, no `Throttles`/`ConcurrentExecutions`/DynamoDB-throttle widgets exist, sequential file reads/blob creation are unchanged (`docagent/orchestrator.py:97`, `docagent/committer.py:71-81`), `urllib.request` still has no connection pooling (`docagent/github_client.py:58-64`), and no load-test scripts exist (only a single-run local integration harness at `documentation/scripts/agents/agent-technical-doc/e2e/local_run.py`).

The one architecturally significant change since the prior run is the new WAF + CloudFront layer in front of the public webhook (`documentation/terraform/ingestion/waf.tf`, added for `SEC-F1`). From a Performance Efficiency lens (as opposed to Security, which is scored separately):

- **Net positive for PERF-12 (bounded resource use):** the `WebhookBodySize` WAF rule (`size_constraint_statement`, 128 KiB threshold, `oversize_handling=MATCH`) now rejects oversized request bodies **at the edge**, before they reach API Gateway or invoke the webhook Lambda — `documentation/terraform/ingestion/waf.tf:83-114`. This is a strictly cheaper failure mode than the prior state (Lambda invocation + cold-start + Secrets Manager read all avoided for oversized/malformed traffic). The `RateLimitPerIP` rule (2000 req/5min/IP, `waf.tf:179-199`) adds a second, edge-level volumetric guard layered in front of the pre-existing API Gateway stage throttle (`main.tf:275-278`) and the DynamoDB-backed per-repo quota (`webhook-receiver/handler.py:219-233`) — three independent, complementary bounding mechanisms now sit in front of compute.
- **Latency-conscious ordering preserved end-to-end:** the new `verify_origin()` check (`documentation/scripts/lambdas/webhook-receiver/handler.py:59-73, 246-248`) runs as the *first* step in the handler, using a cheap constant-time in-memory comparison, and short-circuits **before** the Secrets Manager `GetSecretValue` call for the HMAC secret (`handler.py:150-157, 251`). Spoofed/direct-to-origin traffic that skips CloudFront now fails without paying for a network round-trip to Secrets Manager, partially offsetting the extra hop CloudFront itself introduces.
- **Caching correctly and explicitly disabled, not simply absent:** `default_cache_behavior` uses `Managed-CachingDisabled` (`waf.tf:250`, referencing `data.aws_cloudfront_cache_policy.disabled` at `waf.tf:42-44`) with a documented rationale (`waf.tf:247-249`) — the webhook must never be cached because the GitHub HMAC signature covers the raw body. This is the *correct* choice for this workload, not a caching gap; it does not change the PERF-04 verdict (still Partial, for the same in-process-secret-cache-only reason as before) but is worth noting as deliberate rather than an oversight.
- **New, un-costed latency source (not separately scored, informational):** every webhook request now makes one additional network hop (GitHub → CloudFront edge → API Gateway origin) versus the prior direct-to-API-Gateway path. CloudFront's `default_size_inspection_limit = KB_64` (`waf.tf:65-71`) means WAF content-inspection rules buffer/inspect up to 64 KiB of body before forwarding, adding a small, bounded amount of edge-side processing per request. Given the workload is async (webhook Lambda enqueues to SQS and returns; `worker_timeout_seconds` design already assumes non-blocking dispatch, `variables.tf:41-44`), this added latency is not on any user-facing critical path and is judged immaterial — flagged here for completeness rather than as a finding.

Net effect: no criterion verdict changed from the prior run's grid, so the score independently re-derives to the same 75/100 — this is a genuine re-verification landing on the same number, not a carried-forward assumption. PERF-12's evidence base is now stronger (three-layer bounding: WAF size/rate limit → API Gateway throttle → DynamoDB quota), but a criterion already at `Met` doesn't move further under this rubric. No new findings were introduced by the WAF layer; no prior finding was resolved by it either (it does not touch monitoring, load testing, prompt caching, or concurrency, which remain the open gaps).

## Strengths

- Two-tier LLM model selection (economical Haiku by default, Sonnet escalation only for large/complex repos) is a pure, deterministic function driven by selected-context size — right-sizes the expensive resource (LLM inference) to the workload — _evidence: `docagent/analyzer.py:124-156`, `docagent/config.py:90-95`_
- All AWS compute is serverless and ARM64/Graviton (Lambda `webhook`/`worker`) — matches the bursty, event-driven, scale-to-zero nature of the workload — _evidence: `terraform/ingestion/main.tf:192,222`_
- Data access is exclusively single-item point operations (`PutItem`/`UpdateItem`/`DeleteItem`/conditional writes, plus one atomic counter `UpdateItem` for rate limiting) on a `PAY_PER_REQUEST` DynamoDB table keyed by `pk` — no scans, no secondary indexes needed — _evidence: `terraform/security/main.tf:57-68`, `docagent/idempotency.py:22-74`, `scripts/lambdas/webhook-receiver/handler.py:160-233`_
- Fully asynchronous pipeline: webhook Lambda enqueues to SQS and returns immediately (15s timeout); worker Lambda makes a single non-blocking `invoke_agent_runtime` call and returns (60s timeout, explicitly documented as sufficient because the call is non-blocking) — _evidence: `terraform/ingestion/variables.tf:41-44`, `scripts/lambdas/worker-dispatcher/handler.py:46-77`_
- Deliverables are batched into a **single** Git commit (one `create_tree`/`create_commit`/`update_ref`) regardless of file count — _evidence: `docagent/committer.py:39-93`_
- Context sent to the LLM is bounded on every axis (file count, per-file bytes, total bytes, selected-file count) — _evidence: `docagent/config.py:55-68`, `docagent/repo_reader.py:86-135`, `docagent/selection.py:89-96`_
- Compute is bounded by three complementary, layered guards in front of the Lambda invocation path: WAF body-size/rate-limit at the edge (`terraform/ingestion/waf.tf:83-199`), API Gateway stage throttling (20 burst/10 rps, `terraform/ingestion/main.tf:275-278`), and a DynamoDB-backed per-repo/per-window run quota (`scripts/lambdas/webhook-receiver/handler.py:219-233`) plus a worker SQS-scaling concurrency cap of 5 (`terraform/ingestion/main.tf:244-246`) and `maxReceiveCount=2`→DLQ (`terraform/ingestion/main.tf:19-22`)
- Latency is measured: EMF metric `DurationMs` (with `Outcome` dimension) is emitted per run and visualized as both average and p90 on the CloudWatch dashboard — _evidence: `docagent/metrics.py:18-49`, `terraform/observability/main.tf:122-134`_
- Explicit timeouts at every network boundary: Bedrock client (`read_timeout=900`, `connect_timeout=60`, adaptive retries), GitHub HTTP calls (`timeout=60`), Lambda function timeouts — _evidence: `docagent/analyzer.py:176-181`, `docagent/github_client.py:63`, `terraform/ingestion/main.tf:193,223`_
- The new origin-verification step in the webhook Lambda is ordered to fail fast and cheaply (in-memory constant-time comparison) before the Secrets Manager round-trip for HMAC verification — avoids paying for a network call on spoofed/malformed traffic — _evidence: `scripts/lambdas/webhook-receiver/handler.py:59-73, 150-157, 246-251`_

## Weaknesses / Findings

### [Medium] PERF-F1 — No performance target (SLO) defined for run latency, only measured
- **Evidence:** `docagent/metrics.py:18-49` (DurationMs emitted, no threshold); `terraform/observability/main.tf:24-70` (alarms exist only for DLQ depth and Lambda `Errors` count — none on `DurationMs`/p90)
- **Impact:** The team has visibility into latency trends but no documented target (e.g., "p90 doc-gen run < N minutes") and no alarm fires when latency degrades — regressions are only caught by manual dashboard inspection.
- **Recommendation:** Define an explicit latency SLO (e.g., p90 end-to-end run duration) in README/ARCHITECTURE.md and add a CloudWatch alarm on the `DurationMs` p90 EMF metric (already emitted, just not alarmed on).
- **Alternative solution:** None — Medium severity, straightforward operational addition, no architectural trade-off.

### [Medium] PERF-F2 — Resource-utilization monitoring covers invocations/errors/queue depth but not throttles or concurrency pressure
- **Evidence:** `terraform/observability/main.tf:75-163` (dashboard widgets: Lambda `Invocations`/`Errors`, SQS `ApproximateNumberOfMessagesVisible`, EMF `DurationMs`/`Runs` only — no `Throttles`, `ConcurrentExecutions`, or DynamoDB `ThrottledRequests`/`SystemErrors` widgets or alarms)
- **Impact:** No signal for Lambda `Throttles`/`ConcurrentExecutions` (vs. the `worker_max_concurrency=5` cap, `terraform/ingestion/variables.tf:53-57`), or DynamoDB throttled requests. Under sustained load, the worker's SQS-scaling concurrency cap could be silently saturated (backlog growing in the `main` queue) without a distinct throttle signal — only inferred indirectly from queue depth.
- **Recommendation:** Add `AWS/Lambda Throttles`/`ConcurrentExecutions` widgets/alarms for both functions, and a DynamoDB `ThrottledRequests` widget.
- **Alternative solution:** None — Medium severity, additive monitoring, no trade-off.

### [Low] PERF-F3 — Sequential (non-concurrent) file reads and Git blob creation
- **Evidence:** `docagent/orchestrator.py:97` (`files = {path: reader.read_file(path) for path in selected}` — sequential dict comprehension over up to 40 files), `docagent/committer.py:69-78` (one `create_blob` HTTP call per output file, in a sequential `for` loop)
- **Impact:** Bounded today (≤40 local file reads, small number of Markdown/`.drawio` output files), so latency cost is currently minor, but this doesn't parallelize as either cap grows and each blob creation is a full GitHub API round-trip.
- **Recommendation:** Parallelize local file reads (bounded thread pool) and/or investigate batched blob creation; low priority given current caps.
- **Alternative solution:** None — Low severity, bounded impact under current config.

### [Low] PERF-F4 — No HTTP connection reuse/pooling for the GitHub client
- **Evidence:** `docagent/github_client.py:58-69` (`urllib.request.urlopen` per call, no persistent `Session`/connection pool)
- **Impact:** Each GitHub API call pays a fresh TCP+TLS handshake instead of reusing a keep-alive connection, adding latency overhead proportional to call count (compounded by PERF-F3's sequential per-file blob calls).
- **Recommendation:** Wrap calls in a pooled HTTP client (`urllib3.PoolManager` or `requests.Session`); the module already isolates transport in `_http()`, making this a localized change.
- **Alternative solution:** None — Low severity; the module's design comment (implicit in its "no third-party dependency" framing, `github_client.py:1-5`) reflects a reasonable image-size/cost trade-off to weigh against this latency cost.

### [Low] PERF-F5 — No caching for LLM prompts, and no load/benchmark testing evidence
- **Evidence:** `docagent/analyzer.py:170-184` (no Bedrock prompt-caching configuration on `BedrockModel`); `documentation/scripts/agents/agent-technical-doc/e2e/` contains only a single-run local integration harness (`local_run.py`, `smoke_check.py`) and unit tests under `tests/` — no load/concurrency/throughput test found repo-wide
- **Impact:** The system prompt + output contract (`instructions.md` + `OUTPUT_CONTRACT`, a non-trivial fixed block, `docagent/analyzer.py:25-74`) is resent in full on every invocation without prompt caching, adding avoidable input-token latency/cost. Separately, behavior under concurrent PR bursts (up to `worker_max_concurrency=5`) is unverified by any automated test.
- **Recommendation:** Enable Bedrock prompt caching for the static system-prompt/output-contract portion; add a lightweight load test driving 5+ concurrent SQS messages through the worker path in a non-prod environment.
- **Alternative solution:** None — Low severity for a POC-stage system; reasonable to defer until traffic volume justifies it.

## Criteria grid

| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| PERF-01 | Compute type right-sized & appropriate (serverless/containers/instances) for the workload. | Met | `terraform/ingestion/main.tf:187-235` (ARM64 Lambda, 256MB, timeouts matched to workload), `docagent/analyzer.py:124-156` (two-tier model selection) |
| PERF-02 | Data store choice fits access patterns (SQL/NoSQL/object/cache). | Met | `terraform/security/main.tf:57-68` (single-table `PAY_PER_REQUEST` DynamoDB, point-key access), `terraform/ingestion/main.tf:12-23` (SQS for async decoupling) |
| PERF-03 | Query/index design avoids N+1, full scans, hot partitions. | Met | `docagent/idempotency.py:22-74`, `scripts/lambdas/webhook-receiver/handler.py:150-233` (exclusively `PutItem`/`UpdateItem`/`DeleteItem`, no `Scan`, no GSIs needed) |
| PERF-04 | Caching used where beneficial (CDN, app cache, DB cache) with invalidation. | Partial | In-process secret cache (`scripts/lambdas/webhook-receiver/handler.py:32,150-157`); CDN caching deliberately and correctly disabled for the webhook (`terraform/ingestion/waf.tf:42-44,250`, not a gap); no DB cache/LLM prompt cache found |
| PERF-05 | Async / batching for expensive or bursty work. | Met | `terraform/ingestion/variables.tf:41-44`, `scripts/lambdas/worker-dispatcher/handler.py:46-96`, `docagent/committer.py:39-93` |
| PERF-06 | Timeouts, connection pooling, and payload sizes tuned. | Partial | Timeouts present everywhere (`docagent/analyzer.py:176-181`, `docagent/github_client.py:63`, `terraform/ingestion/main.tf:193,223`); payload sizes bounded end-to-end including new edge-level WAF body-size guard (`terraform/ingestion/waf.tf:83-114`); no connection pooling (`docagent/github_client.py:58-64`) |
| PERF-07 | Concurrency/parallelism used where it helps; no needless serialization. | Partial | Bounded worker concurrency appropriate (`terraform/ingestion/variables.tf:53-57`); sequential local file reads and blob creation (`docagent/orchestrator.py:97`, `docagent/committer.py:69-78`) |
| PERF-08 | Content/data placed close to consumers (edge/region) where relevant. | N/A | No user-facing content delivery — generated docs are committed to the target Git repo and consumed via GitHub's own UI; CloudFront is used for WAF attachment (security), not content locality; single-region backend is not a latency-sensitive edge case for this async pipeline |
| PERF-09 | Performance targets defined and measured (latency/throughput SLIs). | Partial | Measured (`docagent/metrics.py:18-49`, `terraform/observability/main.tf:122-134`); no documented target/SLO, no alarm on latency (`terraform/observability/main.tf:24-70`) |
| PERF-10 | Load/perf testing or benchmarking evidence. | Missing | `documentation/scripts/agents/agent-technical-doc/e2e/` contains only a single-run local integration harness, no load/concurrency test found |
| PERF-11 | Resource utilization monitored (CPU/mem/IO/throttles). | Partial | Invocations/Errors/SQS depth covered (`terraform/observability/main.tf:75-163`); no Throttles/ConcurrentExecutions/DynamoDB-throttle metrics |
| PERF-12 | Bounded resource use (pagination, limits) to avoid pathological cases. | Met | `docagent/config.py:55-68`, `docagent/repo_reader.py:86-135`, `terraform/ingestion/main.tf:244-246,275-278`, `terraform/ingestion/variables.tf:41-88`, plus new edge-level WAF size/rate guards (`terraform/ingestion/waf.tf:83-199`) |

## Prioritized improvements

| priority | action | effort |
|----------|--------|--------|
| P1 | Define an explicit latency SLO and add a CloudWatch alarm on the `DurationMs` p90 EMF metric (PERF-F1) | S |
| P1 | Add Lambda `Throttles`/`ConcurrentExecutions` and DynamoDB throttle metrics to the observability dashboard/alarms (PERF-F2) | S |
| P2 | Enable Bedrock prompt caching for the static system-prompt/output-contract block (PERF-F5) | S |
| P2 | Add a bounded-concurrency load test exercising `worker_max_concurrency=5` in a non-prod environment (PERF-F5) | M |
| P3 | Parallelize local file reads and Git blob creation, or switch the GitHub client to a pooled HTTP transport (PERF-F3, PERF-F4) | M |

## Notes & assumptions

- Scored against the current `develop` branch working tree, including the uncommitted `ingestion/main.tf` diff (per `git status` at session start); no performance-pillar-relevant content was found in that diff beyond what's cited above (it reflects the SQS/AgentCore IAM fixes documented in the shared context pack, which are Security/Reliability-relevant, not Performance-relevant).
- Coverage estimate (~80%) reflects deep reads of `selection.py`, `repo_reader.py`, `analyzer.py`, `config.py`, `idempotency.py`, `github_client.py`, `committer.py`, `metrics.py`, `orchestrator.py`, both Lambda handlers (`webhook-receiver`, `worker-dispatcher`) including their tests, and the `ingestion` (including the new `waf.tf`), `security`, and `observability` Terraform modules. `doc_builder.py`, `drawio.py`, `comments.py`, `paths.py`, `correlation.py`, `payload.py`, `secrets.py`, `github_auth.py`, `retry.py`, and the `runtime`/`roles`/`ecr`/`bootstrap` Terraform modules were not fully read this pass — none surfaced as performance-relevant via the context pack or the reads performed, but this is not a guarantee of exhaustiveness.
- Lambda `memory_size` is hardcoded at 256MB for both `webhook` and `worker` (`terraform/ingestion/main.tf:194,224`) with no documented power-tuning rationale; not scored as a standalone finding (PERF-01 kept Met given the overall right-sizing story is otherwise strong) but flagged as a minor gap.
- `terraform/ingestion/main.tf:82-92` still grants `dynamodb:Query` (`RateLimitQuery` statement) to the webhook role, but no code path in `scripts/lambdas/webhook-receiver/handler.py` issues a `Query` call — all observed access is `PutItem`/`UpdateItem`. This is a least-privilege (Security pillar) concern, not scored here, but it reinforces that the app's actual data-access pattern is point-lookup only (PERF-03 = Met).
- The new WAF/CloudFront layer (`terraform/ingestion/waf.tf`) was assessed specifically for performance implications per this run's instructions: caching is explicitly and correctly disabled for the webhook, the body-size constraint provides a genuine edge-level resource-bounding improvement (PERF-12), and the added network hop is judged immaterial given the fully asynchronous design — see "Delta" section above for full reasoning.
- No live AWS calls were made (`live_aws=OFF` per this run); verdicts rely entirely on static evidence.
