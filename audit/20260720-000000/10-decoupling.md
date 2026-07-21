# Decoupling — Audit

**Score:** 87/100  **Maturity:** 4 (Managed)  **Coverage:** 80%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
This pillar covers how well the system isolates concerns and avoids tight coupling between components.

## Strengths
- The webhook and worker pipeline uses an event-driven SQS boundary, which strongly decouples ingress from execution — _evidence: [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L208-L216), [documentation/scripts/lambdas/worker-dispatcher/handler.py](documentation/scripts/lambdas/worker-dispatcher/handler.py)
- The runtime uses a narrow payload contract and independent execution steps — _evidence: [documentation/scripts/agents/agent-technical-doc/docagent/payload.py](documentation/scripts/agents/agent-technical-doc/docagent/payload.py)

## Weaknesses / Findings
### [Medium] DEC-F1 — The runtime is still tightly coupled to a single ingress flow and region
- **Evidence:** [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L1-L40), [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L159-L205)
- **Impact:** Future failover or alternate entry paths would require more restructuring.
- **Recommendation:** Introduce a more explicit deployment contract and optional failover path.
- **Alternative solution:** Use a multi-region or private ingress model for higher resilience. Effort: L.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| DEC-01 | Event-driven boundary | Met | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L208-L216) |
| DEC-02 | Narrow payload and interface contracts | Met | [documentation/scripts/agents/agent-technical-doc/docagent/payload.py](documentation/scripts/agents/agent-technical-doc/docagent/payload.py) |
| DEC-03 | Resilience to alternate ingress paths | Partial | [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L1-L40) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Generalize the ingress contract and add a failover-oriented design | L |

## Notes & assumptions
The current design is well decoupled for a single-path internal workflow.
