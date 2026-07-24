# Decoupling — Audit

**Score:** 92/100  **Maturity:** 5 (Optimized)  **Coverage:** 95%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Runtime and build-time looseness of coupling between components: dependency
inversion, async/event-driven boundaries, contract stability, failure isolation,
and the ability to change/deploy one part without breaking others.

Does **not** cover: static decomposition/cohesion → **Modularity (09)**; overall
style choice → **Architecture (07)**; elastic independent scaling →
**Scalability (11)**. Shared findings are cross-referenced by id.

## Strengths
- Event-driven boundary: SQS main queue + DLQ decouples the webhook receiver from
  the worker, absorbing bursts and isolating downstream failures — _evidence: `terraform/ingestion/main.tf:8-31`_
- Asynchronous invocation: the agent entrypoint runs the long job in a background
  thread and returns `accepted` in ~1s, so the worker's `InvokeAgentRuntime` call
  never blocks on the full run — _evidence: `scripts/agents/agent-technical-doc/agent.py:97-118`, `scripts/lambdas/worker-dispatcher/handler.py:55-73`_
- Textbook dependency inversion: `OrchestratorDeps` injects all collaborators as
  `Callable` abstractions; concrete boto3/strands/pyjwt implementations are built
  lazily in `default_deps()` with deferred imports — _evidence: `docagent/orchestrator.py:38-96`_
- Config and secrets fully injected via environment and Secrets Manager ARNs; no
  hardcoded cross-references between components — _evidence: `docagent/config.py:60-95`, `terraform/ingestion/main.tf:200-224`_
- Failure isolation on the critical path: transient/permanent error classification
  in the worker (transient → SQS retry → DLQ, permanent → drop), orchestrator
  guarantees a terminal PR comment on any exception, idempotency claim released on
  failure, and metric emission never breaks a run — _evidence: `scripts/lambdas/worker-dispatcher/handler.py:75-95`, `docagent/orchestrator.py:236-266`, `docagent/orchestrator.py:130-138`_
- Temporal decoupling: buffered queue (4-day retention), bounded worker concurrency
  via `scaling_config`, and redrive to DLQ (`maxReceiveCount`) — _evidence: `terraform/ingestion/main.tf:16-31`, `terraform/ingestion/main.tf:246-255`_
- Explicit, documented contracts at each hop: SQS message shape
  `{repo_full_name, pr_number, comment_id, correlation_id}` and the runtime payload
  are documented and parsed through a typed `InvocationRequest` dataclass rather
  than reaching into internals — _evidence: `docagent/payload.py:11-24`, `docagent/payload.py:30-97`, `scripts/lambdas/webhook-receiver/handler.py:322-329`_
- Acyclic runtime and build dependency graph: linear flow GitHub → API GW → webhook
  → SQS → worker → InvokeAgentRuntime → agent → GitHub; the agent calls back to
  GitHub, never to the webhook/worker — _evidence: `docagent/orchestrator.py:200-232`, `terraform/ingestion/data.tf:3-25`_

## Weaknesses / Findings

### [Medium] DEC-F1 — No explicit contract versioning between components
- **Evidence:** `docagent/payload.py:63-90` (`parse_request` validates only presence
  of `repo_full_name`/`pr_number`, no version field), `scripts/lambdas/webhook-receiver/handler.py:322-329`
  (SQS message emitted as an unversioned JSON dict).
- **Impact:** Inter-component payloads (SQS message, runtime invocation) carry no
  schema version. A future producer change (renamed/removed field) could silently
  break the consumer with no negotiated compatibility contract. Mitigated today by
  tolerant parsing (optional PR details resolved later by the agent) and a single
  owner for both sides.
- **Recommendation:** Add a `schema_version` field to the SQS message and runtime
  payload; have consumers reject/branch on unknown versions.
- **Alternative solution:** Adopt a shared, validated schema (e.g. a small pydantic
  model or JSON Schema) versioned alongside both components. Pros: enforced contract,
  early failure on drift. Cons: added dependency/build coupling, marginal for a
  single-team POC. Effort: S. Cross-pillar impact: maintainability +, operational
  excellence +.

### [Low] DEC-F2 — Build-time module coupling via remote_state and hard ordering
- **Evidence:** `terraform/ingestion/data.tf:3-25` (reads `security` and `runtime`
  remote state from a shared, hardcoded state bucket), `terraform/ingestion/main.tf:126-131`
  (`precondition` forces `runtime` to be deployed first).
- **Impact:** Modules are separately applied but not independently deployable: the
  ingestion module cannot be provisioned before `runtime`/`security`, and all modules
  share one state bucket. This is build-time coupling, not runtime coupling, and the
  precondition makes the ordering explicit and safe. Deeper module-boundary analysis
  belongs to **Modularity (09)** / **Terraform (08)** — cross-reference.
- **Recommendation:** Keep the explicit precondition; consider passing cross-module
  values via input variables/SSM parameters instead of `terraform_remote_state` to
  reduce direct state coupling if modules ever need separate ownership.
- **Alternative solution:** Publish module outputs to SSM Parameter Store and consume
  them as data sources. Pros: no cross-module state reads, looser coupling. Cons: extra
  moving parts, eventual-consistency of parameters. Effort: M. Cross-pillar impact:
  modularity +, operational excellence +/-.

### [Info] DEC-F3 — DynamoDB idempotency table shared by webhook and agent
- **Evidence:** `scripts/lambdas/webhook-receiver/handler.py:181-205` (webhook claims
  `repo#pr#comment_id` + rate-limit counter), `docagent/orchestrator.py:207-214`
  (agent claims `repo#pr#sha`).
- **Impact:** Two components write to one table. This is a legitimate distributed
  coordination store (deduplication/idempotency) using disjoint key namespaces — no
  business data flows through it, so it is not a hidden integration bus. Noted for
  awareness only.
- **Recommendation:** None required; the namespacing keeps concerns separated.
- **Alternative solution:** None — current approach is appropriate.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| DEC-01 | Components communicate via stable contracts/interfaces, not internals. | Met | `docagent/payload.py:11-24`, `docagent/payload.py:30-58`, `scripts/lambdas/worker-dispatcher/handler.py:57-73` |
| DEC-02 | Async decoupling (queues/events) where sync coupling is risky. | Met | `terraform/ingestion/main.tf:8-31`, `agent.py:97-118`, `worker-dispatcher/handler.py:55-73` |
| DEC-03 | Dependency inversion: high-level code depends on abstractions. | Met | `docagent/orchestrator.py:38-96` |
| DEC-04 | No shared mutable state / DB as hidden integration bus. | Met | `webhook-receiver/handler.py:181-205`, `docagent/orchestrator.py:207-214` (disjoint namespaces; queue is the integration channel) |
| DEC-05 | Config & secrets injected (env/param store), not hardcoded. | Met | `docagent/config.py:60-95`, `terraform/ingestion/main.tf:200-224` |
| DEC-06 | Failure isolation: no synchronous cascade. | Met | `worker-dispatcher/handler.py:75-95`, `docagent/orchestrator.py:236-266`, `docagent/orchestrator.py:130-138` |
| DEC-07 | Versioned/back-compatible contracts. | Partial | `docagent/payload.py:63-90` (tolerant parsing, but no version field) |
| DEC-08 | Independent deployability of components. | Partial | `terraform/ingestion/data.tf:3-25`, `terraform/ingestion/main.tf:126-131` (hard ordering via remote_state + precondition) |
| DEC-09 | Temporal decoupling (buffering) for bursty load. | Met | `terraform/ingestion/main.tf:16-31`, `terraform/ingestion/main.tf:246-255` |
| DEC-10 | No circular runtime dependencies between services. | Met | `docagent/orchestrator.py:200-232`, `terraform/ingestion/data.tf:3-25` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Add a `schema_version` field to the SQS message and runtime invocation payload; branch/reject on unknown versions (DEC-F1). | S |
| P3 | Reduce build-time module coupling by sourcing cross-module values from SSM Parameter Store instead of `terraform_remote_state` (DEC-F2, cross-ref Modularity/Terraform). | M |

## Notes & assumptions
- Static audit only (live_aws OFF); runtime decoupling assessed from code/IaC.
- All 10 criteria assessed → coverage ~95% (deducted slightly because contract
  versioning and independent-deployability behavior can only be fully confirmed at
  deploy/run time). Confidence high — evidence is direct and consistent.
- DEC-04 kept `Met`: the DynamoDB table is coordination/idempotency state with
  disjoint key namespaces, not a data-passing integration bus (see DEC-F3).
- The missing `ReportBatchItemFailures`/partial-batch response on the SQS event
  source mapping is a reliability concern (batch_size=1 makes it moot here) and is
  scored under **Reliability**, not decoupling.
- No Critical or High findings; the two Partials are contract versioning (DEC-07)
  and build-time module coupling (DEC-08).
