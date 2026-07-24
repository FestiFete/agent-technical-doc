# Scalability — Audit

**Score:** 78/100  **Maturity:** 4 (Managed)  **Coverage:** 100%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Ability to absorb growth in load/data gracefully: horizontal scale-out,
statelessness, elasticity, data-layer partitioning, bottleneck avoidance,
back-pressure and load management.

Does **not** cover: per-request tuning/latency → Performance Efficiency (04);
failure recovery/redundancy/DR → Reliability (03); loose coupling as an enabler
→ Decoupling (10). Shared issues are cross-referenced by id.

Static audit (live_aws OFF): verdicts are grounded on code/IaC, not on observed
runtime capacity.

## Strengths
- Fully **stateless** compute across the chain: webhook + worker Lambdas hold no
  local state, and the AgentCore runtime runs with **no Memory / no KB** — every
  run is self-contained — _evidence: `scripts/agents/agent-technical-doc/agent.py:31-33` ("Sans état : ni AgentCore Memory, ni Knowledge Base"), `scripts/agents/agents.json:4`_
- **On-demand elasticity** end to end: Lambda auto-scaling, SQS→Lambda event
  source mapping with a `scaling_config`, DynamoDB `PAY_PER_REQUEST`, managed
  CloudFront/API GW — _evidence: `terraform/ingestion/main.tf:270-278`, `terraform/security/main.tf:66`_
- **Layered back-pressure / load leveling**: SQS buffer + DLQ (`maxReceiveCount 2`),
  bounded worker concurrency, API GW throttle (10 rps / burst 20), WAF rate-based
  rule (2000/5 min per IP) and a per-repo run quota — _evidence: `terraform/ingestion/main.tf:16-23,270-278,297-301`, `terraform/ingestion/waf.tf` (RateLimitPerIP), `scripts/lambdas/webhook-receiver/handler.py:224-238`_
- **Externalized session state**: idempotency + rate counters in DynamoDB, auth
  in Secrets Manager, `correlation_id` propagated as the AgentCore `runtimeSessionId`
  — nothing pins a request to a specific instance — _evidence: `scripts/lambdas/worker-dispatcher/handler.py:44-47`, `docagent/idempotency.py`_
- **Downstream protection** of the scarce dependency (Bedrock/AgentCore): worker
  concurrency capped and Bedrock client using adaptive retries — _evidence: `terraform/ingestion/variables.tf:66-70`, `docagent/analyzer.py:187-191`_
- **Bounded per-run footprint**: read caps (max 400 files, 80 KB/file, 1.2 MB total,
  40 selected) keep context/memory/cost inside the model window — _evidence: `docagent/config.py:70-79`_
- **High-cardinality idempotency keys** (`repo#pr#comment_id`, `repo#pr#sha`) spread
  writes well across DynamoDB partitions — _evidence: `scripts/lambdas/webhook-receiver/handler.py:246`, `docagent/idempotency.py:19-22`_

## Weaknesses / Findings

### [Medium] SCAL-F1 — Per-repo rate counter is a single hot DynamoDB item
- **Evidence:** `scripts/lambdas/webhook-receiver/handler.py:198-214` (`_rate_key` = `ratelimit#{repo}#{bucket}`, `_increment_repo_counter` = `UpdateExpression="… ADD #c :one"` on one `pk`)
- **Impact:** All triggers from a single repository inside one time window increment
  **one item** (`ratelimit#repo#bucket`). Under a repo's burst this serializes on a
  single partition key, the DynamoDB per-item write ceiling. In practice it is
  bounded upstream (API GW 10 rps, per-repo quota of 20/window, WAF), so it is not a
  production failure risk today, but it does not follow the "distribute writes"
  principle and would bite if the upstream throttle were relaxed.
- **Recommendation:** Shard the counter key (`ratelimit#repo#bucket#{0..N}`) and sum
  the shards, or keep as-is and document that the upstream throttle guarantees the
  item stays well under the write ceiling.
- **Alternative solution:** Move rate limiting to API Gateway usage plans / WAF
  rate rules only (drop the DynamoDB counter). _Pros:_ no hot item, no extra write
  on the hot path. _Cons:_ coarser (per-IP/stage, not per-repo), loses the
  post-dedup semantics. _Effort:_ M. _Cross-pillar:_ cost −, decoupling +.

### [Medium] SCAL-F2 — Fixed worker concurrency (5) is a hard throughput ceiling with no capacity model
- **Evidence:** `terraform/ingestion/variables.tf:66-70` (`worker_max_concurrency` default 5), `terraform/ingestion/main.tf:275-277` (`scaling_config { maximum_concurrency = ... }`)
- **Impact:** At most 5 documentation runs proceed concurrently. This is a deliberate
  guard on Bedrock TPS / AgentCore session limits (good), but the value is a static
  default with no documented capacity model tying it to the actual downstream quotas,
  and no headroom analysis. Under sustained multi-repo load, queue age and end-to-end
  latency grow; the ceiling would need manual tuning to scale.
- **Recommendation:** Document the Bedrock account TPS and AgentCore concurrent-session
  quotas, derive the cap from them, and add a main-queue `ApproximateAgeOfOldestMessage`
  alarm (currently absent per inventory) to detect saturation before latency degrades.
- **Alternative solution:** Keep the cap but make it environment-driven per account
  quota, and add reserved/provisioned settings only if a load test shows need.
  _Pros:_ headroom is explicit and observable. _Cons:_ requires the quota model.
  _Effort:_ M. _Cross-pillar:_ reliability +, operational-excellence +.

### [Low] SCAL-F3 — Repo tarball loaded fully into memory before bounded extraction
- **Evidence:** `docagent/repo_reader.py:44-64` (`tarfile.open(fileobj=io.BytesIO(tar_bytes) …)` — the whole archive is held in memory)
- **Impact:** File **reads** are strictly capped (SCAL-11), but the raw archive is
  materialized in memory in full before those caps apply. A pathologically large repo
  archive could pressure the runtime container's memory independently of the read caps.
- **Recommendation:** Cap the downloaded archive size (reject above a threshold, matching
  `max_total_bytes` headroom) or stream extraction from the HTTP response instead of
  buffering the whole tarball.
- **Alternative solution:** Use a shallow, path-filtered fetch (sparse checkout / GitHub
  contents API for selected paths) rather than the full tarball. _Pros:_ bounded memory,
  less bytes transferred. _Cons:_ more API calls, more code. _Effort:_ M.
  _Cross-pillar:_ performance +, cost +.

### [Low] SCAL-F4 — No load test or capacity model beyond current POC usage
- **Evidence:** context pack "Tests" (127 functional tests, E2E harness = dry-run/synthetic event, "Pas de couverture mesurée"); no load-test artifact found in repo
- **Impact:** Scaling behavior (queue depth vs. concurrency, Bedrock throttling onset,
  DynamoDB item throughput) is reasoned about in comments but never measured. Growth
  limits are estimated, not validated.
- **Recommendation:** Add a lightweight load scenario (N synthetic signed events across
  M repos) and record the saturation point of the worker cap + Bedrock TPS.
- **Alternative solution:** None strictly required for a POC — acceptable to defer to
  pre-production, but the limits should be documented in the meantime.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SCAL-01 | Stateless compute enabling horizontal scale-out | Met | `scripts/agents/agent-technical-doc/agent.py:31-33`; `scripts/agents/agents.json:4`; `scripts/lambdas/webhook-receiver/handler.py` (no local state) |
| SCAL-02 | Auto-scaling / on-demand elasticity for variable load | Met | `terraform/ingestion/main.tf:270-278`; `terraform/security/main.tf:66` (PAY_PER_REQUEST) |
| SCAL-03 | Data layer scales (on-demand capacity, TTL) | Met | `terraform/security/main.tf:63-84` (on-demand + TTL, single table) |
| SCAL-04 | No single-threaded/singleton bottleneck on hot path | Partial | fixed cap 5 `terraform/ingestion/variables.tf:66-70`; hot counter item `scripts/lambdas/webhook-receiver/handler.py:198-214` (see SCAL-F1/F2) |
| SCAL-05 | Back-pressure / rate limiting / queue buffering | Met | `terraform/ingestion/main.tf:16-23,297-301`; `waf.tf` RateLimitPerIP; `scripts/lambdas/webhook-receiver/handler.py:224-238` |
| SCAL-06 | Partition keys avoid hot spots | Partial | good: `docagent/idempotency.py:19-22`; hot: `scripts/lambdas/webhook-receiver/handler.py:191-214` (single item/repo/window) |
| SCAL-07 | Statelessness of sessions (externalized state) | Met | `docagent/idempotency.py`; `scripts/lambdas/worker-dispatcher/handler.py:44-47`; Secrets Manager |
| SCAL-08 | Concurrency limits & downstream protection | Met | `terraform/ingestion/variables.tf:66-70`; `docagent/analyzer.py:187-191` (adaptive retries) |
| SCAL-09 | Scaling limits/quotas understood, headroom exists | Partial | awareness in comments `docagent/config.py:56-63`, `agent.py:28-38`; no explicit quota/headroom model (see SCAL-F2) |
| SCAL-10 | Load tested / capacity model beyond current usage | Missing | only functional E2E harness; no load test artifact |
| SCAL-11 | No unbounded in-memory growth / per-instance state | Partial | reads capped `docagent/config.py:70-79`; tarball fully in memory `docagent/repo_reader.py:44-64` (see SCAL-F3) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Derive `worker_max_concurrency` from documented Bedrock TPS / AgentCore session quotas; add main-queue `ApproximateAgeOfOldestMessage` alarm (SCAL-F2) | M |
| P2 | Shard the per-repo rate counter or document the upstream-throttle guarantee (SCAL-F1) | M |
| P3 | Cap tarball download size / stream extraction to bound runtime memory (SCAL-F3) | M |
| P3 | Add a minimal load scenario + capacity notes (SCAL-F4) | S |

## Notes & assumptions
- Full grid assessed (coverage 100%); confidence high — every verdict is anchored on
  directly-read code/IaC.
- Static audit only: DynamoDB on-demand elasticity, Lambda auto-scaling and AgentCore
  session scaling are judged from IaC/design, not from observed runtime metrics.
- SCAL-F1/SCAL-F6 hot-key concern is bounded in practice by the upstream API GW throttle
  and per-repo quota, hence Medium not High.
- Concurrency cap (5) is intentional downstream protection (a strength for SCAL-08),
  but its static, unmodeled value is simultaneously the main scaling ceiling (SCAL-F2).
- Main-queue age alarm / `ReportBatchItemFailures` gaps are owned by Reliability (03);
  referenced here only as observability for saturation.
