# Context Pack — agent-technical-doc (focused re-run: Security pillar only, #3)

Target: `/Users/g.mirambeau/Development/AWS/agent-technical-doc` (repo root). Mode: static-only (`live_aws=OFF`). Branch: `develop`, latest commit `d0b7ff5` ("Audit"), **plus uncommitted working-tree changes** (see below) — evaluate the current on-disk state, not just the last commit.

**Scope of this run**: user explicitly asked to re-run the **Security pillar only** again (third such request), following up on the SEC-F3 implementation from this session. Full prior context: `audit/20260721-133806/_context/inventory.md` (full repo map, all 7 modules) and `audit/20260721-154651/_context/inventory.md` (previous security-only run, which covered SEC-F1/WAF).

## History of Security-relevant runs, newest first

1. **This run** (`20260722-152501`) — re-verify after SEC-F3 implementation (uncommitted).
2. `audit/20260721-154651/02-security.md` — score 81/100, maturity 4. Verified SEC-F1 (WAF+CloudFront) as implemented but flagged a residual direct-API-Gateway-bypass gap (kept as Low). SEC-F3 was still open (Medium) at that point.
3. `audit/20260721-133806/02-security.md` — score 79/100 (the original full 12-pillar audit).

Treat every verdict/finding in both prior files as an **unverified claim** to independently re-check against current code, not as ground truth.

## What changed since the last Security run (`20260721-154651`, score 81/100)

**Uncommitted working-tree changes** (`git status --short`):
```
 M documentation/terraform/observability/variables.tf
?? documentation/terraform/observability/cloudtrail.tf
```

This is the SEC-F3 implementation (detective controls), done in this session but not yet committed:

- **New file `documentation/terraform/observability/cloudtrail.tf`**: an account-wide, multi-region `aws_cloudtrail` trail (`include_global_service_events = true`, `enable_log_file_validation = true`) delivering to a dedicated S3 bucket (SSE-KMS with the AWS-managed `aws/s3` key — no CMK, consistent with the project's existing SEC-07 POC compromise, not a new gap), public-access-blocked, with a bounded lifecycle expiration (`var.cloudtrail_s3_retention_days`, default 365d). Also streams to a CloudWatch Logs group (`var.cloudtrail_log_retention_days`, default 90d) via a scoped IAM role (`aws_iam_role.cloudtrail_to_cw`, `logs:CreateLogStream`/`logs:PutLogEvents` only, resource-scoped to that log group's ARN).
- Two `aws_cloudwatch_log_metric_filter` + `aws_cloudwatch_metric_alarm` pairs on top of the CloudTrail-fed log group:
  - IAM policy/role change detection (`iam.amazonaws.com`, `Put*Policy`/`Attach*`/`Detach*`/`Create*`/`Delete*`/`Update*` event names), threshold 0 (any change alarms).
  - Secrets Manager `GetSecretValue` volume detection, threshold `var.secrets_access_alarm_threshold` (default 30 per 5min) — deliberately not zero, since secret reads are routine/expected traffic here (once per webhook delivery + once per accepted run), not an anomaly by themselves.
  - Both alarms use the **existing** `var.alarm_actions` variable (already present, already wired to the module's 3 pre-existing operational alarms) — no new SNS topic was created; `alarm_actions` still defaults to `[]` (this remains the separate, not-yet-fixed `OPS-F2` gap from the full audit — these new alarms inherit that same "exists but nobody's notified by default" characteristic).
  - A minimal `aws_guardduty_detector` (`enable = true`, no extra feature blocks configured).
- **`documentation/terraform/observability/variables.tf`** additions: `enable_cloudtrail` (bool, default `true`), `enable_guardduty` (bool, default `true`) — both intended as escape hatches if the AWS org already runs a central trail/detector (GuardDuty allows only one detector per account/region); `cloudtrail_log_retention_days` (90), `cloudtrail_s3_retention_days` (365), `secrets_access_alarm_threshold` (30), `role_name_prefix` (`"limited-"`, mirrors the same org IAM-naming guardrail already used in the `ingestion` module, needed here because this file now creates an IAM role).
- Verified this session (by the implementer, re-verify independently): `terraform fmt -check -recursive` clean repo-wide (confirmed again in this run's own scan, see `_context/scans/terraform-fmt.txt`, empty). `terraform validate` passed in an isolated scratch copy (S3 backend stripped) — not re-run this session, but the file has not changed since.

### What SEC-F3 addresses vs. leaves open

The recommendation had three parts: (1) CloudTrail, (2) CloudWatch metric filters/alarms on IAM + Secrets Manager, (3) "consider GuardDuty." All three are now present in code (uncommitted). Re-verify independently whether this is a complete, correctly-wired implementation, or whether gaps remain (e.g., is the trail genuinely multi-region and capturing global/IAM events? Does the S3 bucket policy correctly scope to `cloudtrail.amazonaws.com`? Is the CloudWatch Logs role least-privilege? Does GuardDuty add any real value with zero extra feature configuration, or is a bare detector too thin to credit as "Met" rather than "Partial"?).

## SEC-F2, SEC-F4, SEC-F5 status

Not touched by any commit or uncommitted change since the last Security run — re-verify each fresh against current code (do not assume unchanged, but nothing in the diff touches KMS/CMK, the Bedrock IAM resource scope, or Python dependency pinning).

## Tool availability (unchanged)

`terraform` ✅, `aws` CLI ✅ (not used, `live_aws=OFF`), `tflint`/`checkov`/`tfsec`/`trivy` ❌ not installed. `AWS_PROFILE`/`AWS_REGION` unset.

## Instruction to the pillar agent

Re-assess the full Security criteria grid (SEC-01..SEC-15) against the **current on-disk working tree** (commit `d0b7ff5` plus the uncommitted `observability/cloudtrail.tf` + `observability/variables.tf` changes described above), not any prior run's verdicts. Read `documentation/terraform/observability/cloudtrail.tf` and the updated `variables.tf` in full yourself. Explicitly re-verify SEC-F3's status (resolved / partially mitigated / gaps remain) and SEC-F1's residual-bypass status (unchanged since the last run, but confirm). Do not carry forward any prior score without independent re-verification.
