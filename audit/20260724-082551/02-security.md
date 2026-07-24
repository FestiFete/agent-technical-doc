# Security — Audit

**Score:** 77/100  **Maturity:** 4 (Managed)  **Coverage:** 90%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Confidentiality, integrity, availability: IAM & least privilege, data protection
(at rest/in transit), network exposure, secrets management, detective controls,
injection/prompt-injection defense, webhook authenticity, secure SDLC, blast-radius
containment. **Static audit** (code/IaC only, `live_aws = OFF`): controls verifiable
only at runtime (effective encryption, active alarms, account-level detective
services) are judged on the IaC, not the deployed state.

Cross-references (not double-scored here): backup/DR availability → Reliability (03);
IaC hygiene (state locking, formatting) → Terraform (08).

## Strengths
- **SEC-F1 remediated — public webhook now behind CloudFront + WAFv2.** A WebACL
  (Core Rule Set, Known Bad Inputs, per-IP rate limit, custom body-size rule) is
  attached to a CloudFront distribution fronting the HTTP API; a CloudFront→origin
  `X-Origin-Verify` shared secret is checked by the Lambda **before** HMAC, closing
  the direct-`execute-api` bypass. — _evidence: `terraform/ingestion/waf.tf:60-210`, `terraform/ingestion/main.tf:243-249` (`ORIGIN_VERIFY_SECRET`), `scripts/lambdas/webhook-receiver/handler.py:180-186`_
- **Per-service least-privilege IAM**, ARN-scoped, `limited-` org prefix. — _evidence: `terraform/roles/main.tf:19-90`, `terraform/ingestion/main.tf:69-190`_
- **No secrets in code/state**: placeholders + `ignore_changes`; GitHub App issues a short-lived (~1h) installation token, PAT only as fallback. — _evidence: `terraform/security/main.tf:28-58`, `docagent/github_auth.py:110-170`_
- **Secret redaction & no value logging.** — _evidence: `docagent/correlation.py:33-58`, `docagent/secrets.py:52-70`_
- **Constant-time HMAC webhook verification.** — _evidence: `scripts/lambdas/webhook-receiver/handler.py:95-103`_
- **Prompt-injection defense is code-enforced**: commit target hard-pinned to `docs/agent/**` regardless of LLM/repo content; anti path-traversal. — _evidence: `docagent/paths.py:35-73`, `instructions.md:11-24`_
- **Tarball extraction hardened** against tar-slip / symlink / hardlink / special files. — _evidence: `docagent/repo_reader.py:44-73`_
- **Data stores private + encrypted**: DynamoDB (default) + PITR, SQS SSE, ECR AES256 + scan-on-push, S3 state bucket KMS + full public-access block. — _evidence: `terraform/security/main.tf:60-83`, `terraform/ingestion/main.tf:8-19`, `terraform/ecr/main.tf:5-22`, `terraform/bootstrap/main.tf:47-67`_
- **Authorization on the endpoint**: repo allowlist (fail-safe empty→deny) + `author_association` check + per-repo rate quota. — _evidence: `scripts/lambdas/webhook-receiver/handler.py:130-152, 236-244`_

## Weaknesses / Findings

### [Medium] SEC-F1 — No customer-managed KMS keys (CMK) on any data store
- **Evidence:** `terraform/security/main.tf:11-16, 44, 57, 74` (CMK removed; DynamoDB comment "server_side_encryption CMK retiré"), `terraform/ingestion/main.tf:8-19` (SSE-SQS managed), `terraform/roles/main.tf:82-84` (KMS statement removed).
- **Impact:** All at-rest encryption relies on AWS-owned / AWS-managed keys. No customer control over key policy, no independent key-access audit trail, no controlled key rotation, no cryptographic blast-radius isolation between the secret store, queues and table. Deliberate POC constraint (org role has an explicit `DENY kms:CreateKey`).
- **Recommendation:** Restore CMKs (SSE-KMS) for Secrets Manager, DynamoDB and SQS once KMS rights are available; enable automatic annual key rotation and scope key policies to the consuming roles.
- **Alternative solution:** Keep AWS-managed keys but compensate with tight resource policies + CloudTrail data events on Secrets Manager and an SCP restricting cross-account access. _Pros:_ no KMS cost, unblocks the POC; _Cons:_ no dedicated key audit/rotation, weaker isolation; _Effort:_ S; _Cross-pillar impact:_ cost + (CMK adds spend), operational-excellence + (auditability).

### [Medium] SEC-F2 — Detective controls not evidenced in IaC
- **Evidence:** no CloudTrail / AWS Config / GuardDuty / Security Hub resources anywhere under `terraform/` (only CloudWatch logs/alarms in `terraform/observability/` and `terraform/runtime/logs.tf`, plus WAF logging `terraform/ingestion/waf.tf:130-138`).
- **Impact:** No codified account-level threat detection or API-audit trail; incident detection/forensics depend on controls that cannot be verified statically. May exist at org/account scope outside this repo (unverifiable in a static audit).
- **Recommendation:** Add CloudTrail (management + Secrets Manager data events), GuardDuty and Security Hub (or reference the org baseline that provides them) to IaC so the guarantee is explicit and reviewable.
- **Alternative solution:** Reference an org landing-zone/Control Tower baseline instead of per-project resources. _Pros:_ centralized, no duplication; _Cons:_ project can't prove coverage on its own; _Effort:_ M; _Cross-pillar impact:_ operational-excellence +.

### [Medium] SEC-F3 — Long-lived secrets without automatic rotation
- **Evidence:** `terraform/security/main.tf:30-58` — `github-token` and `webhook-hmac` secrets set out-of-band with `lifecycle { ignore_changes }`, no `aws_secretsmanager_secret_rotation`. GitHub App installation token is short-lived, but the HMAC secret and the PAT fallback are long-lived.
- **Impact:** A leaked HMAC secret or PAT stays valid until manually rotated; contradicts AWS guidance to rotate secrets on a schedule ([Secrets Manager rotation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_BestPractices.Security.html), [SecretsManager.1 control](https://docs.aws.amazon.com/securityhub/latest/userguide/secretsmanager-controls.html)).
- **Recommendation:** Prefer the GitHub App path (already implemented) and drop the PAT fallback for prod; document/automate HMAC secret rotation, or rotate via a scheduled Lambda.
- **Alternative solution:** None strictly required — GitHub App short-lived tokens already minimize exposure; formalizing HMAC rotation is the residual gap.

### [Low] SEC-F4 — Python dependencies pinned only by floor (`>=`); no dependency scanning
- **Evidence:** `scripts/agents/agent-technical-doc/requirements.txt:1-10` (all `>=` ranges); no `pip-audit`, lockfile, or Dependabot config. Terraform providers are properly pinned (`~> 6.0`) with `.terraform.lock.hcl`.
- **Impact:** Non-reproducible builds; a compromised/yanked upstream version can be pulled at build time; no automated CVE alerting on the runtime image dependencies.
- **Recommendation:** Pin exact versions (or add a hash-locked `requirements.lock`) and run `pip-audit`/image scanning in the build. ECR `scan_on_push` already covers the built image (`terraform/ecr/main.tf:9-11`).
- **Alternative solution:** None required — small change; ECR scan-on-push partially compensates.

### [Low] SEC-F5 — No CI/CD security gates (branch protection, signed artifacts)
- **Evidence:** inventory confirms no `.github/workflows`/pipeline; deploys are manual and secrets set by hand. No branch protection or artifact signing evidenced.
- **Impact:** No enforced review/gate before deploy, no image signing/provenance; secure-SDLC controls rely on manual discipline. Note: absence of a pipeline also means no pipeline-borne secret-leakage surface.
- **Recommendation:** Add a pipeline with least-privilege OIDC role, `terraform validate`/scan gates, protected branches, and image signing (cosign / ECR + Notation).
- **Alternative solution:** None required for a POC; revisit before prod.

### [Low] SEC-F6 — AgentCore runtime uses PUBLIC network mode; ECR tags mutable
- **Evidence:** `terraform/runtime/main.tf:20-23` (`network_mode = "PUBLIC"`); `terraform/ecr/main.tf:6` (`image_tag_mutability = "MUTABLE"`).
- **Impact:** Runtime egress is unrestricted internet (needed for GitHub + Bedrock, but no allowlist/PrivateLink); mutable tags allow a tag to be overwritten (mitigated: the runtime pins the image by `@digest`).
- **Recommendation:** Where AgentCore supports it, use VPC/PrivateLink egress with an allowlist; set ECR `IMMUTABLE` tags.
- **Alternative solution:** None required — egress is inherent to the workload; digest-pinning already neutralizes the mutable-tag risk.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| SEC-01 | Least-privilege IAM (no unjustified wildcards) | Met | `terraform/roles/main.tf:24-90`; `terraform/ingestion/main.tf:75-190` (ARN-scoped; `ecr:GetAuthorizationToken`/`PutMetricData` `*` justified w/ namespace condition) |
| SEC-02 | No long-lived creds/secrets in code/state; Secrets Manager/roles | Partial | `terraform/security/main.tf:30-58` (placeholders, `ignore_changes`); `docagent/github_auth.py:110-170` (short-lived App token) — but no rotation (SEC-F3) |
| SEC-03 | Encryption at rest on all data stores | Met | `terraform/security/main.tf:60-83`; `terraform/ingestion/main.tf:8-19`; `terraform/ecr/main.tf:17-19`; `terraform/bootstrap/main.tf:53-60` |
| SEC-04 | Encryption in transit (TLS), no plaintext | Met | `terraform/ingestion/waf.tf:196-201` (`origin_protocol_policy=https-only`, `TLSv1.2`), `:167` (`viewer_protocol_policy=https-only`); `docagent/github_auth.py` (https api_base) |
| SEC-05 | Network segmentation & least-exposure | Partial | `terraform/runtime/main.tf:20-23` runtime `PUBLIC` egress; serverless (no VPC/SG); no private egress control (SEC-F6) |
| SEC-06 | No public exposure of data stores/admin surfaces | Met | `terraform/bootstrap/main.tf:62-67` (S3 public-access block); DynamoDB/SQS/Secrets/ECR IAM-only; only intended public surface is the webhook (protected) |
| SEC-07 | KMS CMK usage & key rotation | Missing | `terraform/security/main.tf:11-16,44,57,74`; `terraform/roles/main.tf:82-84` — CMK removed (POC `DENY kms:CreateKey`) (SEC-F1) |
| SEC-08 | AuthN/AuthZ on network-exposed endpoints | Met | `scripts/lambdas/webhook-receiver/handler.py:180-193` (origin+HMAC), `:130-152` (allowlist + `author_association`) |
| SEC-09 | Input validation / injection protection | Met | `docagent/paths.py:35-73`; `docagent/repo_reader.py:44-73`; `instructions.md:11-24`; WAF `terraform/ingestion/waf.tf:100-129` |
| SEC-10 | Detective controls (CloudTrail/Config/GuardDuty/Security Hub) | Missing | none in `terraform/` (only CW logs/alarms + WAF logging) (SEC-F2) |
| SEC-11 | Dependency & image vuln management | Partial | `terraform/ecr/main.tf:9-11` (`scan_on_push`); `requirements.txt:1-10` (`>=` floors, no scan) (SEC-F4) |
| SEC-12 | Secrets not logged; PII redaction | Met | `docagent/correlation.py:33-58`; `docagent/secrets.py:64-70` |
| SEC-13 | Webhook authenticity (signature verification) | Met | `scripts/lambdas/webhook-receiver/handler.py:106-113` (HMAC-SHA256, `compare_digest`) |
| SEC-14 | Security in CI/CD | Partial | no pipeline / branch protection / signing; secrets out of code + `.terraform.lock.hcl` pinned (SEC-F5) |
| SEC-15 | Blast-radius containment (per-service roles/boundaries) | Met | `terraform/roles/main.tf`, `terraform/ingestion/main.tf:60-190` (3 scoped roles, `limited-` prefix); LLM has no write power (`docagent/paths.py`) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Restore SSE-KMS CMKs (Secrets Manager, DynamoDB, SQS) with rotation once KMS rights are available (SEC-F1) | M |
| P1 | Add/reference CloudTrail + GuardDuty + Security Hub baseline in IaC (SEC-F2) | M |
| P2 | Automate/formalize secret rotation; drop PAT fallback for prod (SEC-F3) | S |
| P2 | Pin/lock Python deps + add `pip-audit` to build (SEC-F4) | S |
| P3 | Add CI/CD with protected branches, scan gates, image signing (SEC-F5) | M |
| P3 | ECR `IMMUTABLE` tags; consider VPC/PrivateLink egress for runtime (SEC-F6) | M |

## Notes & assumptions
- **Static audit only.** Effective encryption, active alarms, and account-level
  detective services (CloudTrail/GuardDuty/Config/Security Hub) cannot be observed;
  they are judged on IaC. SEC-10 may be satisfied at org scope outside this repo but
  is not verifiable here → scored `Missing` per the honesty rule (absence of evidence
  = not Met).
- **SEC-F1 (public API with no WAF) from prior audits is remediated** in this snapshot
  (`terraform/ingestion/waf.tf`), so the pillar carries **no Critical/High finding** and
  does not cap the global maturity. WAFv2 cannot attach directly to an HTTP API; the
  CloudFront-front pattern used here is the supported approach ([WAF supported resources](https://docs.aws.amazon.com/waf/latest/developerguide/how-aws-waf-works-resources.html)).
- Grounded in the AWS Well-Architected Security pillar and the cited Secrets Manager /
  WAF docs. Coverage ~0.9 (all 15 criteria assessed with code/IaC evidence; runtime
  state unverifiable). Confidence medium.
