# Security — Audit

**Score:** 68/100  **Maturity:** 3 (Defined)  **Coverage:** 80%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
This pillar covers identity, data protection, network exposure, secret handling, and the authenticity of webhook inputs. It does not cover backup and disaster recovery, which are addressed by Reliability.

## Strengths
- Webhook signature validation and repository allowlist logic are implemented in the ingress Lambda — _evidence: [documentation/scripts/lambdas/webhook-receiver/handler.py](documentation/scripts/lambdas/webhook-receiver/handler.py#L56-L101), [documentation/scripts/lambdas/webhook-receiver/handler.py](documentation/scripts/lambdas/webhook-receiver/handler.py#L224-L250)_
- The agent uses AWS Secrets Manager and avoids logging secret values — _evidence: [documentation/scripts/agents/agent-technical-doc/docagent/secrets.py](documentation/scripts/agents/agent-technical-doc/docagent/secrets.py#L44-L58), [documentation/scripts/agents/agent-technical-doc/docagent/correlation.py](documentation/scripts/agents/agent-technical-doc/docagent/correlation.py#L1-L28)_

## Weaknesses / Findings
### [Critical] SEC-F1 — Publicly exposed entrypoint without WAF and without CMK-backed encryption controls
- **Evidence:** [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L1-L20), [documentation/terraform/security/main.tf](documentation/terraform/security/main.tf#L9-L12), [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L17-L20)
- **Impact:** The public API endpoint and sensitive data stores remain exposed to a higher-than-necessary attack surface in a production-style deployment.
- **Recommendation:** Add WAF and CMK-based encryption for secrets, queues, and data stores before production hardening.
- **Alternative solution:** Place a WAF and private networking layer in front of the public endpoint while preserving the current serverless design. Pros: improved L7 protection and reduced public attack surface. Cons: additional infrastructure components and operational overhead. Effort: M.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SEC-01 | Least-privilege IAM | Partial | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L64-L145) |
| SEC-02 | Secrets in Secrets Manager | Met | [documentation/terraform/security/main.tf](documentation/terraform/security/main.tf#L16-L50), [documentation/scripts/agents/agent-technical-doc/docagent/secrets.py](documentation/scripts/agents/agent-technical-doc/docagent/secrets.py#L44-L58) |
| SEC-03 | Encryption at rest | Partial | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L1-L20), [documentation/terraform/security/main.tf](documentation/terraform/security/main.tf#L9-L12) |
| SEC-04 | Encryption in transit | Partial | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L227-L260) |
| SEC-05 | Network segmentation and least exposure | Partial | [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L17-L20) |
| SEC-06 | No public exposure of data stores/admin surfaces | Missing | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L227-L260) |
| SEC-07 | KMS CMK usage | Missing | [documentation/terraform/security/main.tf](documentation/terraform/security/main.tf#L9-L12) |
| SEC-08 | Authentication/authorization on endpoints | Met | [documentation/scripts/lambdas/webhook-receiver/handler.py](documentation/scripts/lambdas/webhook-receiver/handler.py#L56-L101) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add WAF and CMK-backed encryption controls | M |

## Notes & assumptions
The review is static and based on repository evidence; no live AWS deployment was inspected.
