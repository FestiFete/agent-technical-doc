# Context Pack — agent-technical-doc (focused re-run: Security pillar only)

Target: `/Users/g.mirambeau/Development/AWS/agent-technical-doc` (repo root). Mode: static-only (`live_aws=OFF`). Branch: `develop`, working tree clean at commit `6abcd3a` ("SEC-F1 : Add WAF").

**Scope of this run**: user explicitly asked to re-run the **Security pillar only** (not the full 12-pillar audit). This context pack is a lean, security-focused refresh of the one built for the full run at `audit/20260721-133806/_context/inventory.md` (still available for reference) — read that file for the full repo map (languages, all 7 Terraform modules, entry points, docs) if broader context is needed. This file only calls out what changed since that run.

## What changed since the last full audit (`audit/20260721-133806`, 2026-07-21 13:38 UTC)

Commit history since then (`git log --oneline`, newest first):
1. `6abcd3a` **"SEC-F1 : Add WAF"** — implements the prior Security audit's SEC-F1 recommendation (public webhook endpoint had no WAF/L7 protection). Full diff: `documentation/terraform/ingestion/{main.tf,outputs.tf,providers.tf}` modified, `documentation/terraform/ingestion/waf.tf` added (176 lines).
2. `419b754` "Audit" — commits the `audit/20260721-133806/` deliverables (the prior full audit's own output) into the repo.
3. `3602351` "SEC-04 : Remove SQS GetQueueAttributes" — this is the change that was **uncommitted** during the prior audit run (`sqs:GetQueueAttributes` removed from the worker IAM policy); it is now committed. The prior Security pillar had already evaluated this in its "current on-disk state" and factored it into SEC-01.
4. `61e8425`, `d30a6a5` — predate the prior audit, already factored in.

### SEC-F1 remediation detail (`documentation/terraform/ingestion/waf.tf`, new file)

- `aws_wafv2_web_acl` (`scope = "CLOUDFRONT"`, created via an `aws.us_east_1` provider alias added in `providers.tf` — required since CLOUDFRONT-scope WAF must live in us-east-1 regardless of the stack's home region `eu-central-1`). Three rules:
  - Priority 1: AWS Managed Rules `AWSManagedRulesCommonRuleSet`.
  - Priority 2: AWS Managed Rules `AWSManagedRulesKnownBadInputsRuleSet`.
  - Priority 3: `RateLimitPerIP`, rate-based statement, `limit = 2000` requests/5min per source IP, `action { block {} }`.
  - Web ACL-level and per-rule `visibility_config` (CloudWatch metrics + sampled requests) all enabled.
- `aws_wafv2_web_acl_logging_configuration` → a new `aws_cloudwatch_log_group.waf` (`aws-waf-logs-technical-doc-POC-webhook`, `us-east-1`, retention = `var.log_retention_days` = 14d default).
- `aws_cloudfront_distribution.webhook`: sits in front of the existing `aws_apigatewayv2_api.webhook` (origin = the API's regional `execute-api` domain, `origin_protocol_policy = "https-only"`, TLS 1.2). `cache_policy_id` = managed `Managed-CachingDisabled` (webhook must never be cached), `origin_request_policy_id` = managed `Managed-AllViewerExceptHostHeader` (all headers/body forwarded unmodified — required for the GitHub HMAC signature, which signs the raw body). `web_acl_id` = the WAFv2 ACL's **ARN** (CloudFront's `web_acl_id` argument requires the ARN for WAFv2, not the plain ID — a common Terraform footgun). `price_class = "PriceClass_100"`. `viewer_certificate { cloudfront_default_certificate = true }` (no custom domain).
- `documentation/terraform/ingestion/outputs.tf`: `webhook_url` now returns the CloudFront domain (`https://${aws_cloudfront_distribution.webhook.domain_name}/webhook`) — this is what should be configured as the GitHub App's webhook Payload URL. A new `webhook_api_gateway_url` output exposes the raw API Gateway URL, explicitly documented in its `description` as "debug/diagnostic uniquement... contourne le WAF" (bypasses the WAF).
- **Known, explicitly documented residual gap** (in a comment block at the top of `waf.tf`): the raw API Gateway `execute-api` URL remains directly reachable and bypasses the WAF/CloudFront entirely — nothing on the API Gateway side (resource policy, custom header check in the Lambda, etc.) rejects direct-origin traffic. This was a deliberate scope decision when SEC-F1 was implemented (kept minimal, didn't touch the already-audited webhook Lambda's auth logic) and should be assessed fresh by this run, not assumed fixed.
- `terraform fmt -check -recursive` over the whole `documentation/terraform/` tree returns clean (verified this run, see `_context/scans/terraform-fmt.txt`, empty diff) — the `ingestion/main.tf` alignment issue flagged by the prior audit (TF-F2) was fixed as a side effect of running `terraform fmt` while implementing SEC-F1.

### SEC-F2, SEC-F3, SEC-F4, SEC-F5 status

Not addressed by any commit since the prior audit — re-verify fresh, do not assume prior verdicts still hold, but nothing in the diff touches KMS/CMK (`documentation/terraform/security/main.tf` unchanged), CloudTrail/GuardDuty/Config (`documentation/terraform/observability/main.tf` unchanged), the Bedrock IAM resource scope (`documentation/terraform/roles/main.tf` unchanged), or Python dependency pinning (`requirements.txt` unchanged).

## Tool availability (unchanged from prior run)

`terraform` ✅, `aws` CLI ✅ (not used, `live_aws=OFF`), `tflint`/`checkov`/`tfsec`/`trivy` ❌ not installed. `AWS_PROFILE`/`AWS_REGION` unset.

## Cheap scans run once this session

`terraform fmt -check -recursive -diff` over `documentation/terraform/` → clean, no output (see `_context/scans/terraform-fmt.txt`, confirmed via exit code 0 and empty diff). `terraform validate` not run this session (would require per-module `-backend=false` init across 7 chained modules; same time-boxing decision as the prior full audit).

## Instruction to the pillar agent

Re-assess the full Security criteria grid (SEC-01..SEC-15) against the **current** repo state (commit `6abcd3a`), not the prior run's verdicts. Explicitly re-verify SEC-F1: is it resolved, partially mitigated, or does a residual gap remain (see the direct-origin-bypass note above)? Do not carry forward any prior score without independent re-verification.
