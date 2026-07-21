# Terraform — Audit

**Score:** 76/100  **Maturity:** 4 (Managed)  **Coverage:** 80%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
This pillar covers Terraform structure, module boundaries, provider usage, and deployment discipline. It does not cover runtime application quality.

## Strengths
- The infrastructure is split into modules by concern (ingestion, security, runtime, observability, roles) — _evidence: [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf), [documentation/terraform/security/main.tf](documentation/terraform/security/main.tf), [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf)
- The Terraform configuration includes explicit role policies, environment variables, and lifecycle guards — _evidence: [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L64-L145), [documentation/terraform/runtime/main.tf](documentation/terraform/runtime/main.tf#L1-L40)

## Weaknesses / Findings
### [High] TF-F1 — State backend and deployment flow are still manual and hard-coded
- **Evidence:** [documentation/README.md](documentation/README.md#L69-L80)
- **Impact:** Repeatability and governance are weaker than they should be for larger teams or regulated environments.
- **Recommendation:** Parameterize the backend and wire CI/CD for terraform init/validate/apply workflows.
- **Alternative solution:** Use a shared remote state bootstrap and automated deployment pipeline. Effort: M.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| TF-01 | Module structure and separation | Met | [documentation/terraform](documentation/terraform) |
| TF-02 | Policy and input validation | Partial | [documentation/terraform/ingestion/main.tf](documentation/terraform/ingestion/main.tf#L64-L145) |
| TF-03 | Repeatable deployment flow | Partial | [documentation/README.md](documentation/README.md#L69-L80) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Parameterize the Terraform backend and add CI/CD validation | M |

## Notes & assumptions
The IaC is reasonably structured, but its operationalization is still immature.
