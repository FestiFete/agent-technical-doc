# Sustainability — Audit

**Score:** 81/100  **Maturity:** 4 (Managed)  **Coverage:** 75%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
This pillar covers the environmental operating profile of the system: efficiency, resource usage, and explicit sustainability practices.

## Strengths
- The system is event-driven and serverless, reducing idle energy consumption — _evidence: [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md#L14-L25), [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L159-L205)
- ARM64 resources are used, which is generally more efficient than older architectures — _evidence: [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L159-L205), [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L11-L20)

## Weaknesses / Findings
### [Info] SUST-F1 — No explicit sustainability policy or governance is documented
- **Evidence:** [documentation/README.md](documentation/README.md#L1-L40)
- **Impact:** The design is already efficient, but the operating model has no explicit sustainability targets or review points.
- **Recommendation:** Document sustainability goals and review model selection thresholds periodically.
- **Alternative solution:** None — this is more governance than an architectural defect.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SUST-01 | Efficient event-driven compute | Met | [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md#L14-L25) |
| SUST-02 | Efficient hardware / runtime choices | Met | [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L11-L20) |
| SUST-03 | Sustainability governance | Partial | [documentation/README.md](documentation/README.md#L1-L40) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add lightweight sustainability guidance and review cadence | S |

## Notes & assumptions
This is a relatively efficient system by design, but sustainability is not yet treated as a formal operating concern.
