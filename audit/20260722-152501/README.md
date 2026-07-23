# Security Audit (focused re-run #3) — agent-technical-doc — 20260722-152501

**Scope:** Security pillar only, at the user's explicit request — not a full 12-pillar audit. Third security-focused run, following up on the SEC-F3 implementation (CloudTrail + GuardDuty + IAM/Secrets Manager alarms) done in this session but **not yet committed** to git — this run evaluated the current working tree, including that uncommitted diff.

**Score:** 81/100  **Maturity:** 4/5 (Managed)
**Capping:** none — no unresolved Critical finding
**Mode:** static  **Profile/Region:** n/a (live_aws OFF)
**Delta vs. prior Security run:** 81 → 81 (unchanged — see why below)

## Why the score didn't move even though real work landed

Commit-in-progress `documentation/terraform/observability/cloudtrail.tf` (uncommitted) adds a correctly-built account-wide detective baseline: multi-region CloudTrail with global service events and log file validation, a least-privilege log-delivery IAM role, a GuardDuty detector, and two purpose-built CloudWatch alarms (IAM policy changes, Secrets Manager access volume). All of that was independently re-verified this run and is real.

The **SEC-10 criterion verdict stayed at `Partial`** (not upgraded to `Met`) for two reasons the agent flagged directly:
1. **Neither the new alarms nor GuardDuty findings have a default notification path.** Like the module's three pre-existing alarms, they depend on `var.alarm_actions`, which still defaults to `[]` — no SNS topic exists anywhere in the repo. A detective control nobody gets paged for is weaker credit than one that's fully wired.
2. **AWS Config and Security Hub — both named explicitly in the SEC-10 criterion — remain entirely absent.** CloudTrail + GuardDuty cover two of the four named control types, not all four.

So `SEC-F3`'s **severity** dropped from Medium to Low (the underlying risk genuinely shrank), but the **criterion verdict** didn't cross from Partial to Met — which is why the pillar score is unchanged. This is intentional, strict scoring per the rubric ("no evidence → not Met"), not an oversight.

## Findings (no Critical; 5 Low)

| id | severity | title | evidence |
|----|----------|-------|----------|
| SEC-F3 | Low | Detective controls substantially implemented, but notification path unwired and Config/Security Hub still absent | [documentation/terraform/observability/cloudtrail.tf:185](documentation/terraform/observability/cloudtrail.tf#L185) |
| SEC-F1 | Low | WAF/CloudFront front in place, raw API Gateway origin still directly reachable (unchanged) | [documentation/terraform/ingestion/waf.tf:18-21](documentation/terraform/ingestion/waf.tf#L18-L21) |
| SEC-F2 | Low | No customer-managed KMS keys (CMK); blocked at the account level (unchanged) | [documentation/terraform/security/main.tf:8-16](documentation/terraform/security/main.tf#L8-L16) |
| SEC-F4 | Low | Bedrock model-invoke permission scoped wider than the models actually used (unchanged) | [documentation/terraform/roles/main.tf:38-45](documentation/terraform/roles/main.tf#L38-L45) |
| SEC-F5 | Low | Unpinned Python dependencies, no lockfile (unchanged) | [documentation/scripts/agents/agent-technical-doc/requirements.txt:1-8](documentation/scripts/agents/agent-technical-doc/requirements.txt#L1-L8) |

All five findings are now Low severity — this is the first Security run with no Medium or higher.

## Remediation roadmap

### Quick wins
- **Create an SNS topic and populate `var.alarm_actions`** so all 5 CloudWatch alarms (3 operational + 2 new security) actually notify someone — `SEC-F3` (P1, S effort). This is the single highest-value remaining action: it closes the main reason SEC-10 is still `Partial`, and doubles as fixing the earlier `OPS-F2` gap from the full audit.
- Add an `aws:SourceArn` condition to the CloudTrail S3 bucket policy statements (AWS-documented confused-deputy hardening) — P2, S effort.
- Add a CloudFront origin custom-header check in the webhook Lambda to close the SEC-F1 residual bypass — P2, S effort.
- Scope the Bedrock `InvokeModel` resource to the two configured model ARNs — `SEC-F4` (P2, S effort).
- Pin Python dependencies with a lockfile, add `pip-audit`/Dependabot — `SEC-F5` (P2, S effort).

### Structural work
- Evaluate AWS Config and/or Security Hub once past POC scale, to fully satisfy SEC-10's four named control types — `SEC-F3` (P3, M effort).
- Reintroduce customer-managed KMS keys once the account-level `kms:CreateKey` deny is lifted — `SEC-F2` (P3, M effort, blocked on an org-level change).

## Method & limitations

- Static analysis only (`live_aws=OFF`); no AWS API calls made.
- Evaluated the **current working tree**, including the uncommitted `observability/cloudtrail.tf` (new) and `observability/variables.tf` (modified) — not just the last commit.
- Single-agent focused run (Security pillar only) — no global cross-pillar weighting applies; the score above is the Security pillar's own score.
- `terraform validate`/`plan` not re-run this session (validated in a prior session against the same, unchanged file content).
- Coverage ~96%. Not independently assessed: IAM Access Analyzer/policy-simulator results, `ingestion/terraform.tfvars` contents, any manual/undocumented AWS console configuration.
- Full pillar detail: [`02-security.md`](02-security.md). Prior security runs: `audit/20260721-154651/` (score 81, verified SEC-F1) and `audit/20260721-133806/` (score 79, original full 12-pillar audit — the other 11 pillars there are still current).
