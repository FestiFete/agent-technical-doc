# Reliability — Audit

**Score:** 78/100  **Maturity:** 4 (Managed)  **Coverage:** 80%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
This pillar covers resilience, backup and recovery expectations, idempotency, retries, and failure handling. It does not cover the broader security posture of the system.

## Strengths
- The webhook path contains idempotency and SQS dead-letter handling — _evidence: [documentation/scripts/lambdas/webhook-receiver/handler.py](documentation/scripts/lambdas/webhook-receiver/handler.py#L141-L157), [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L1-L20)_
- The worker uses retries and classifies transient errors distinctly — _evidence: [documentation/scripts/lambdas/worker-dispatcher/handler.py](documentation/scripts/lambdas/worker-dispatcher/handler.py#L1-L80)

## Weaknesses / Findings
### [High] REL-F1 — No multi-region or disaster recovery design is present
- **Evidence:** [documentation/AUDIT.md](documentation/AUDIT.md#L57-L61)
- **Impact:** A regional outage would disrupt the ingestion chain and documentation generation flow.
- **Recommendation:** Add a DR strategy with replicated state, backup, and failover coverage.
- **Alternative solution:** None — this is a deliberate gap in the current POC posture.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| REL-01 | Idempotency and deduplication | Met | [documentation/scripts/lambdas/webhook-receiver/handler.py](documentation/scripts/lambdas/webhook-receiver/handler.py#L141-L157) |
| REL-02 | Retries and DLQ | Met | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L1-L20) |
| REL-03 | Disaster recovery / multi-region | Missing | [documentation/AUDIT.md](documentation/AUDIT.md#L57-L61) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add a DR strategy with failover coverage | L |

## Notes & assumptions
The system appears reliable within a single AWS region, but its DR posture is not yet mature.
