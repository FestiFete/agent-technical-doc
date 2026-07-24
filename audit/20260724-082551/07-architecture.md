# Architecture — Audit

**Score:** 96/100  **Maturity:** 5 (Optimized)  **Coverage:** 90%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Judges whether the *chosen design* is sound and coherent for the stated goal: an
event-driven, serverless documentation agent triggered by a GitHub PR comment
(`webhook → API Gateway → Lambda → SQS → Lambda worker → InvokeAgentRuntime →
agent`). Assesses architectural style, component boundaries, data flow/ownership,
integration patterns, consistency/idempotency, state placement, cross-cutting
concerns, documentation fidelity, over-engineering, failure domains, technology
consistency, and extensibility.

Does **not** cover (cross-referenced): internal module granularity → **Modularity
(09)**; coupling mechanics → **Decoupling (10)**; growth under load → **Scalability
(11)**; security/reliability specifics → **02 / 03** (e.g. single-region DR, alarm
notification targets).

## Strengths
- Event-driven serverless style is a natural fit for a bursty, comment-triggered
  workload and is explicitly justified (async native, no synchronous 15-min cap) —
  _evidence: `.kiro/specs/agent-technical-doc/design.md:§7`, `documentation/scripts/agents/agent-technical-doc/agent.py:29-60`_
- Crisp component boundaries, each with a single responsibility: webhook-receiver
  (auth/filter/authz/dedup/quota/enqueue), worker (SQS→InvokeAgentRuntime), agent
  (analyze/commit/comment) — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:1-21`, `documentation/scripts/lambdas/worker-dispatcher/handler.py:1-12`_
- The LLM is a **pure analyzer with no write power**; rendering, schema validation,
  commit and comment are deterministic code — a deliberate blast-radius/security
  design choice — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/analyzer.py:1-12`, `docagent/orchestrator.py:200-233`_
- Explicit data flow & ownership: metadata-only payloads, DynamoDB keys namespaced
  per concern (`repo#pr#comment_id`, `repo#pr#sha`, `ratelimit#…`), webhook
  deliberately has no GitHub token — _evidence: `documentation/ARCHITECTURE.md:§4`, `webhook-receiver/handler.py:216-241`_
- Coherent consistency/idempotency across boundaries: two-level idempotency,
  conditional `PutItem`, release-on-failure to allow safe re-run, writes never
  replayed — _evidence: `docagent/orchestrator.py:170-188`, `docagent/orchestrator.py:235-250`_
- Deliberate statelessness: no AgentCore Memory / no Knowledge Base; state lives in
  DynamoDB + Secrets Manager only — _evidence: `agent.py:38-40`, `design.md:§1`_
- Cross-cutting concerns handled consistently: `correlation_id` propagated across
  all three components, secret masking, centralized `config`, EMF metrics module —
  _evidence: `worker-dispatcher/handler.py:58-63`, `docagent/orchestrator.py:1-25`_
- Dependency injection (`OrchestratorDeps`) + deferred boto3/strands imports make
  the design testable and extensible without redesign — _evidence: `docagent/orchestrator.py:44-70`_

## Weaknesses / Findings

### [Medium] ARC-F1 — Design spec (`design.md`) has drifted from the implemented system
- **Evidence:** `.kiro/specs/agent-technical-doc/design.md:§5` lists only 4 Terraform
  modules (`roles/runtime/ingestion/observability`) while the repo has 7
  (`bootstrap, ecr, security, roles, runtime, ingestion, observability`, see
  `documentation/terraform/`); `design.md:§2.2` places DynamoDB + KMS in
  `ingestion` whereas they live in the `security` module (inventory); `design.md:§2.2`
  states runtime is *Python 3.11* while the runtime image/inventory is Python 3.12.
- **Impact:** The authoritative design document no longer matches the code, which
  erodes onboarding trust and can mislead future changes. Note the far more detailed
  `documentation/ARCHITECTURE.md` **does** match the code faithfully (handlers,
  orchestrator flow, invariants all verified), so the drift is confined to the spec.
- **Recommendation:** Refresh `design.md §2.2/§5` to reflect the 7-module layout,
  correct the DynamoDB/KMS module placement, and align the Python version. Consider
  making `ARCHITECTURE.md` the single source of truth and having `design.md` link to
  it rather than duplicating structure.
- **Alternative solution:** None needed — documentation reconciliation, effort S,
  no cross-pillar impact.

### [Low] ARC-F2 — Architectural decisions recorded as prose, not formal ADRs
- **Evidence:** Key decisions (async-native invocation, no KB/Memory, retry
  placement, egress boundaries) are captured in `.kiro/specs/agent-technical-doc/design.md:§7`
  ("Points techniques (tranchés)") rather than as discrete, dated ADRs.
- **Impact:** Decisions are traceable but not individually versioned; rationale for
  reversing a choice is harder to track over time. Low impact given the prose is
  clear and diagrams are present.
- **Recommendation:** Optionally externalize the §7 decisions into lightweight
  `docs/adr/NNN-*.md` records. Not required for a POC.
- **Alternative solution:** None — current prose-based decision log is acceptable
  for this scope.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| ARC-01 | Architectural style fits & justified | Met | `design.md:§7`, `agent.py:29-60`, `ARCHITECTURE.md:§1` |
| ARC-02 | Clear component boundaries, single responsibility | Met | `webhook-receiver/handler.py:1-21`, `worker-dispatcher/handler.py:1-12`, `ARCHITECTURE.md:§4` |
| ARC-03 | Explicit data flow & ownership, no ambiguous shared state | Met | `ARCHITECTURE.md:§4`, `webhook-receiver/handler.py:216-241`, `design.md:§4.1` |
| ARC-04 | Integration patterns appropriate (sync/async, queue) | Met | `design.md:§2.1`, `worker-dispatcher/handler.py:64-83`, `agent.py:62-90` |
| ARC-05 | Consistency & idempotency coherent across boundaries | Met | `docagent/orchestrator.py:170-188`, `webhook-receiver/handler.py:145-171` |
| ARC-06 | Statelessness / state placement deliberate | Met | `agent.py:38-40`, `design.md:§1`, `design.md:§4.1` |
| ARC-07 | Cross-cutting concerns handled consistently | Met | `worker-dispatcher/handler.py:58-63`, `docagent/orchestrator.py:1-25`, `analyzer.py:1-12` |
| ARC-08 | Design documented (diagrams/ADRs) and matches code | Partial | `ARCHITECTURE.md:§1-4` (matches) vs `design.md:§2.2/§5` (drift) |
| ARC-09 | No over-engineering vs requirements | Met | `analyzer.py:105-130` (Haiku default), `design.md:§1` (no KB/Memory), `docagent/config.py` (caps) |
| ARC-10 | Failure domains & blast radius intentional | Met | `ARCHITECTURE.md:§4`, `worker-dispatcher/handler.py:24-30`, `analyzer.py:1-12` |
| ARC-11 | Technology choices consistent & justified | Met | `design.md:§1`, ARM64 everywhere + Python 3.12 + TF `~>6.0` (inventory) |
| ARC-12 | Extensibility: new capabilities fit without redesign | Met | `docagent/orchestrator.py:44-70`, `agents.json` discovery, `design.md:§1` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Reconcile `design.md §2.2/§5` with the 7-module Terraform layout, DynamoDB/KMS placement and Python version; point spec at `ARCHITECTURE.md` as source of truth | S |
| P3 | (Optional) Externalize `design.md §7` decisions into lightweight dated ADRs | S |
| P3 | (Cross-ref reliability-03) Document the intentional single-region / no-DR blast-radius scope as an explicit accepted risk for the POC | S |

## Notes & assumptions
- Static audit only (no live AWS). Architecture judged on code/IaC + design docs.
- WAF + CloudTrail treated as PRESENT per the context-pack CORRECTION/REFRESH
  (`terraform/ingestion/waf.tf`, `terraform/observability/cloudtrail.tf`); the
  CloudFront + WAF + `X-Origin-Verify` front door is a justified defense-in-depth
  layer, not over-engineering — `webhook-receiver/handler.py:56-75`.
- Coverage 90%: read `ARCHITECTURE.md`, `design.md`, `agent.py`, `orchestrator.py`,
  `analyzer.py`, both Lambda handlers, and the Terraform module map; did not deep-read
  every `main.tf` (deferred to Terraform pillar 08).
- The design is genuinely strong and coherent; the only material architecture-level
  weakness is spec/code documentation drift (ARC-F1). No Critical/High findings.
