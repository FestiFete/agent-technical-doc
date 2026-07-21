# Scalability — Audit

**Score:** 79/100  **Maturity:** 4 (Managed)  **Coverage:** 80%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
This pillar covers the ability of the system to absorb growth in volume, repository size, and request frequency.

## Strengths
- The solution is built on serverless services and uses concurrency controls for queue processing — _evidence: [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L208-L216), [documentation/scripts/lambdas/worker-dispatcher/handler.py](documentation/scripts/lambdas/worker-dispatcher/handler.py)
- The runtime and ingestion paths include explicit caps to protect the system from pathological usage — _evidence: [documentation/scripts/agents/agent-technical-doc/docagent/config.py](documentation/scripts/agents/agent-technical-doc/docagent/config.py#L65-L68), [documentation/scripts/lambdas/webhook-receiver/handler.py](documentation/scripts/lambdas/webhook-receiver/handler.py#L199-L250)

## Weaknesses / Findings
### [Medium] SCA-F1 — Scale is bounded by runtime and large-repo analysis limits
- **Evidence:** [documentation/scripts/agents/agent-technical-doc/docagent/config.py](documentation/scripts/agents/agent-technical-doc/docagent/config.py#L65-L68), [documentation/AUDIT.md](documentation/AUDIT.md#L56-L57)
- **Impact:** Very large or bursty workloads can still hit practical ceilings.
- **Recommendation:** Introduce more streaming and batching for repository context processing.
- **Alternative solution:** Use hierarchical summarization to reduce the amount of context passed to the model. Effort: M.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SCA-01 | Serverless scale-to-demand | Met | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L208-L216) |
| SCA-02 | Concurrency controls | Met | [documentation/scripts/lambdas/worker-dispatcher/handler.py](documentation/scripts/lambdas/worker-dispatcher/handler.py) |
| SCA-03 | Large-workload handling | Partial | [documentation/AUDIT.md](documentation/AUDIT.md#L56-L57) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add streaming and batching for large repository analysis | M |

## Notes & assumptions
The foundation is scalable, but the system is not yet optimized for very large or highly bursty workloads.
