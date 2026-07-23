# Context Pack — agent-technical-doc (full 12-pillar re-audit)

Target: `/Users/g.mirambeau/Development/AWS/agent-technical-doc` (repo root). Mode: static-only (`live_aws=OFF`). Branch: `develop`, working tree clean at commit `f89ea51` ("Fix AccessDenied error on InvokeAgentRuntime").

This is a full re-run of all 12 pillars, following the original full audit at `audit/20260721-133806/` (score 76/100, maturity 4/5) and two focused Security-only re-runs (`audit/20260721-154651/`, `audit/20260722-152501/`, both settling at 81/100). Substantial work has landed since the original full audit — not just Security. Treat every prior pillar verdict as an unverified claim to independently re-check against current code; do not carry forward scores.

## What changed since the original full audit (`audit/20260721-133806`)

Commit history since then, newest first (`git log --oneline`):
```
f89ea51 Fix AccessDenied error on InvokeAgentRuntime
3aef4df Ajustement de l'ARN pour appeler le runtime de bedrock-agentcore
4474197 Fix webhook body size
fb10956 Fixes
2080990 Deactivate direct call to API Gateway + activate WAF usage
c67dfbc Audit
b840bab SEC-F3 : Cloudtrail
d0b7ff5 Audit
6abcd3a SEC-F1 : Add WAF
419b754 Audit
3602351 SEC-04 : Remove SQS GetQueueAttributes   (already reflected in the original full audit's "current state")
61e8425 SEC-03 - Wildcard removed from /runtime-endpoint/*   (already reflected in the original full audit's "current state")
```

### 1. WAF + CloudFront in front of the public webhook (`documentation/terraform/ingestion/waf.tf`, new)

- `aws_wafv2_web_acl` (scope=CLOUDFRONT, `us-east-1` provider alias) with, in priority order:
  1. `WebhookBodySize` — custom `size_constraint_statement`, blocks body > 128 KiB (`oversize_handling=MATCH`). Added after discovering AWS Managed Core Rule Set's built-in `SizeRestrictions_BODY` (8 KiB default) was blocking real GitHub `issue_comment` payloads (~10.5 KiB) with a 403.
  2. AWS Managed Rules `AWSManagedRulesCommonRuleSet`, with `rule_action_override` setting `SizeRestrictions_BODY` to `Count` (superseded by rule 1 above, kept from re-blocking legitimate traffic).
  3. AWS Managed Rules `AWSManagedRulesKnownBadInputsRuleSet`.
  4. `RateLimitPerIP` — 2000 req/5min per source IP.
  - `association_config.request_body.cloudfront.default_size_inspection_limit = "KB_64"` (raised from the 16 KiB CloudFront default so content-inspection rules see more of larger legitimate payloads).
  - WAF logging to a dedicated CloudWatch log group (`aws-waf-logs-technical-doc-POC-webhook`, us-east-1).
- `aws_cloudfront_distribution` in front of the existing `aws_apigatewayv2_api.webhook` (origin unchanged). Caching disabled, all headers/body forwarded (`Managed-AllViewerExceptHostHeader`). `web_acl_id` = the WAFv2 ACL's ARN.
- **Origin-verify shared secret** (`random_password.origin_verify`, 32 chars): CloudFront attaches it as a custom header (`X-Origin-Verify`) on every request to the origin; the webhook Lambda checks for it (`ORIGIN_VERIFY_SECRET` env var, `verify_origin()` in `handler.py`, constant-time comparison) as the very first step, before the HMAC check, rejecting with the same generic 401 message as an invalid signature (no oracle). This closes the "raw API Gateway URL bypasses the WAF" gap — the direct `execute-api` URL is now functionally rejected even though it's still technically reachable at the network level (HTTP APIs don't support resource policies).
- `documentation/terraform/ingestion/outputs.tf`: `webhook_url` now points at the CloudFront domain (this is what's configured as the GitHub App's Payload URL); `webhook_api_gateway_url` is the raw debug-only URL, documented as rejected.
- `documentation/scripts/lambdas/webhook-receiver/handler.py` / `tests/test_webhook_receiver.py`: `verify_origin()` pure function + 3 new unit tests, `Config.origin_verify_secret` field, handler renumbered.
- `documentation/terraform/ingestion/providers.tf`: added `random` provider (`~> 3.6`) and the `aws.us_east_1` alias (required — CLOUDFRONT-scope WAFv2 resources must live in us-east-1 regardless of the stack's home region).

### 2. Account-wide detective controls (`documentation/terraform/observability/cloudtrail.tf`, new)

- Multi-region `aws_cloudtrail` trail (`include_global_service_events=true`, `enable_log_file_validation=true`) → dedicated encrypted, public-access-blocked S3 bucket (bounded lifecycle expiration) + a CloudWatch Logs group (`cloudtrail_log_retention_days`, default 90d) via a scoped delivery IAM role.
- Two metric-filter + alarm pairs on the CloudTrail-fed log group: IAM policy/role changes (threshold 0), Secrets Manager `GetSecretValue` volume (threshold `secrets_access_alarm_threshold`, default 30/5min — deliberately non-zero since secret reads are routine here).
- A bare `aws_guardduty_detector` (`enable=true`, no extra feature config).
- Both alarms reuse the module's pre-existing `var.alarm_actions` variable — **still defaults to `[]`, no SNS topic exists anywhere in the repo.** This remains an open gap (previously tracked as `OPS-F2` in the original audit, and re-confirmed as the reason `SEC-10` stayed `Partial` rather than `Met` in the second Security-only re-run).
- `variables.tf` additions: `enable_cloudtrail`/`enable_guardduty` toggles (default true), retention/threshold variables, `role_name_prefix` (mirrors the same org IAM-naming guardrail already used in `ingestion`).

### 3. Three production IAM/config bugs found and fixed via live end-to-end testing (commits `2080990`, `4474197`, `3aef4df`, `f89ea51`)

These were discovered by actually deploying and testing the pipeline live (not just static review) after the WAF work landed:
- **WAF body-size false positive** (see §1 `WebhookBodySize` rule) — real GitHub webhooks were getting 403'd.
- **`sqs:GetQueueAttributes` missing on the worker role** (`documentation/terraform/ingestion/main.tf`, `ConsumeQueue` statement) — this permission had been removed by the earlier `SEC-04` commit on the reasoning that the Lambda *code* never calls it directly; it turns out AWS Lambda's own SQS event-source-mapping poller (managed infrastructure, not the function code) requires it to function. Without it, the poller silently failed and the worker was never invoked — messages piled up in the main queue with zero throughput, no DLQ movement, no error surfaced anywhere until logs were inspected directly. **This is a live-verified, high-severity operational bug that existed in deployed production for some period** (exact duration unknown from static analysis alone).
- **`bedrock-agentcore:InvokeAgentRuntime` scoped to the wrong resource** (`documentation/terraform/ingestion/main.tf`, `InvokeRuntimeScoped` statement) — this had been narrowed by the earlier `SEC-03` commit (removing a `/runtime-endpoint/*` wildcard) to just the bare runtime ARN. Live testing showed AWS actually requires authorization on *both* the bare runtime ARN and the `.../runtime-endpoint/DEFAULT` ARN for this API call (confirmed via two consecutive, differently-scoped `AccessDeniedException` errors) — the statement's `Resource` is now a 2-element list covering both.
- **Net effect**: two prior "least-privilege tightening" commits (`SEC-03`, `SEC-04`), each plausible and well-intentioned in isolation, silently broke the pipeline's core async flow (worker never triggered; when it was, the runtime call was denied) for an unknown period until live end-to-end testing surfaced both. This is significant, first-hand evidence for the Reliability, Operational Excellence, and Maintainability pillars: no automated test or CI check caught either regression (per the original audit's `OPS-F1`/`OPS-F4`/`MNT-F2`, there is still no CI pipeline), and static code review alone (including this skill's own prior Security-pillar passes) did not catch the AgentCore/SQS managed-infrastructure permission requirements — this class of bug is specifically the kind that only live/integration testing surfaces, reinforcing the audit's prior `SCAL-F3`/`PERF-F5` "no load/integration testing" findings.
- All four fixes are `terraform validate`-clean and were confirmed live: the pipeline now runs end-to-end successfully (webhook → SQS → worker → AgentCore runtime → analysis → commit → PR comment), verified via direct CloudWatch Logs inspection during this session (multiple full successful runs observed, e.g. `Outcome: complete`, `FilesCommitted: 10`, PR comment posted).

### Everything else

No other module changed. `documentation/terraform/{bootstrap,ecr,security,roles,runtime}` are unchanged since the original full audit. Application code outside the webhook Lambda (agent runtime `docagent/*`, worker-dispatcher Lambda) is unchanged.

## Tool availability

`terraform` ✅, `aws` CLI ✅ (not used for this run's evidence gathering — `live_aws=OFF` per default; note the orchestrator DID use live AWS CLI access in a separate, prior debugging session this same day to diagnose and verify the fixes above, but that is out-of-band operational verification, not part of this audit's evidence — pillar agents should still ground every claim in static file evidence, `path:line`, per the skill's evidence rules). `tflint`/`checkov`/`tfsec`/`trivy` ❌ not installed. `AWS_PROFILE`/`AWS_REGION` unset in this shell (a profile `NewSysOps-375039967495` exists locally and was used for the live debugging session, but is not assumed available to sub-agents).

## Cheap scans run once this session

`terraform fmt -check -recursive -diff` over `documentation/terraform/` → clean, no output (`_context/scans/terraform-fmt.txt`). `terraform validate` not re-run this session (all 4 fixes above were individually validated via isolated scratch copies during the live debugging session and are unchanged since).

## Instruction to every pillar agent

Re-assess your full criteria grid against the **current committed state** (`f89ea51`, working tree clean). Do not assume any prior run's verdict still holds — re-verify independently, citing fresh `path:line` evidence. Pay particular attention to how the two "IAM tightening broke production" incidents (§3 above) and the still-open "alarms have no notification path" gap (§2) affect your pillar's criteria, if applicable (e.g. Reliability: change-safety/testing criteria; Operational Excellence: no CI/CD, no automated regression coverage for this exact failure class; Maintainability: test coverage gaps; Security: this is a Security-adjacent improvement, already scored 81/100 in the latest focused run — re-verify fresh rather than copying that number forward, since new commits landed after that run too).
