# Security Audit (focused re-run) — agent-technical-doc — 20260721-154651

**Scope:** Security pillar only, at the user's explicit request — not a full 12-pillar audit. This is a follow-up to the full audit at `audit/20260721-133806/`, run after commit `6abcd3a` ("SEC-F1 : Add WAF") implemented that run's SEC-F1 finding.

**Score:** 81/100  **Maturity:** 4/5 (Managed)
**Capping:** none — no unresolved Critical finding
**Mode:** static  **Profile/Region:** n/a (live_aws OFF)
**Delta vs. prior Security run:** 79 → 81 (+2)

## What changed since the last Security run (79/100)

Commit `6abcd3a` added `documentation/terraform/ingestion/waf.tf`: a WAFv2 WebACL (AWS Managed Core Rule Set + Known Bad Inputs + a 2000 req/5min per-IP rate-based rule) attached to a new CloudFront distribution placed in front of the existing API Gateway HTTP API, with WAF logging to CloudWatch. This is the AWS-documented workaround for the fact that WAFv2 cannot attach directly to an HTTP API.

The re-audit independently re-verified this and found it correctly built (`SEC-04`, encryption-in-transit, moved from evidence at the API Gateway only to also covering the CloudFront layer), but identified one residual gap: **the raw API Gateway `execute-api` URL remains directly reachable**, bypassing WAF/CloudFront entirely. This keeps `SEC-F1` open, but downgraded from Medium (prior run) to **Low** — the underlying risk was never an unauthenticated write path (HMAC verification and the API Gateway stage throttle apply on both routes), only a narrower "WAF managed-rule coverage can be bypassed" gap. This finding's own detail file already documented this exact limitation as a known, deliberate scope decision when SEC-F1 was implemented.

All other prior findings (SEC-F2 no CMK, SEC-F3 no detective controls, SEC-F4 broad Bedrock IAM scope, SEC-F5 unpinned Python deps) were independently re-verified fresh against current code and are unchanged.

## Findings (no Critical; 1 Medium, 4 Low)

| id | severity | title | evidence |
|----|----------|-------|----------|
| SEC-F3 | Medium | No account/project-level detective controls (CloudTrail, Config, GuardDuty, Security Hub) | [documentation/terraform/observability/main.tf:1-169](documentation/terraform/observability/main.tf#L1-L169) |
| SEC-F1 | Low | WAF/CloudFront front now in place, but the raw API Gateway origin remains directly reachable | [documentation/terraform/ingestion/waf.tf:18-21](documentation/terraform/ingestion/waf.tf#L18-L21) |
| SEC-F2 | Low | No customer-managed KMS keys (CMK); blocked at the account level | [documentation/terraform/security/main.tf:8-13](documentation/terraform/security/main.tf#L8-L13) |
| SEC-F4 | Low | Bedrock model-invoke permission scoped wider than the models actually used | [documentation/terraform/roles/main.tf:42-49](documentation/terraform/roles/main.tf#L42-L49) |
| SEC-F5 | Low | Unpinned Python dependencies, no lockfile | [documentation/scripts/agents/agent-technical-doc/requirements.txt:1-8](documentation/scripts/agents/agent-technical-doc/requirements.txt#L1-L8) |

## Remediation roadmap

### Quick wins
- Enable a baseline CloudTrail trail + metric filters/alarms on IAM/Secrets Manager activity — `SEC-F3` (P1, S effort).
- Add a CloudFront origin custom-header check in the webhook Lambda to reject direct API Gateway traffic, fully closing the SEC-F1 residual bypass — P2, S effort.
- Scope the Bedrock `InvokeModel` resource to the two configured model ARNs and region — `SEC-F4` (P2, S effort).
- Pin Python dependencies with a lockfile and add `pip-audit`/Dependabot — `SEC-F5` (P2, S effort).

### Structural work
- Reintroduce customer-managed KMS keys once the account-level `kms:CreateKey` deny is lifted; enable automatic rotation — `SEC-F2` (P3, M effort, blocked on an org-level permissions change).

## Method & limitations

- Static analysis only (`live_aws=OFF`); no AWS API calls made.
- Single-agent focused run (Security pillar only), not the full 12-pillar workflow — no global cross-pillar weighting applies; the score above is the Security pillar's own score.
- `terraform validate`/`plan` not run this session (time-boxed, same as the full audit).
- The AWS Documentation MCP was not available this session; WAFv2/CloudFront target-support statements rely on documented AWS behavior, not a freshly fetched doc citation.
- Coverage ~95%. Not independently assessed: IAM Access Analyzer/policy-simulator results, `ingestion/terraform.tfvars` contents, and any manual/undocumented AWS console configuration outside Terraform.
- Full pillar detail: [`02-security.md`](02-security.md). For the other 11 pillars (unchanged since 2026-07-21 13:38 UTC), see `audit/20260721-133806/`.
