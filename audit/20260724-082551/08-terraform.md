# Terraform — Structure & Best Practices — Audit

**Score:** 80/100  **Maturity:** 4 (Managed)  **Coverage:** 95%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Terraform/IaC engineering quality of `documentation/terraform/` (7 root modules:
bootstrap, ecr, security, roles, runtime, ingestion, observability): repository/module
layout, state management, version pinning, variable/output hygiene, provider config,
idempotent addressing, lifecycle safety, tagging/naming, and idiomatic style.

Assessed statically by reading every `*.tf` plus read-only `terraform fmt -check
-recursive` (clean) and `terraform validate` (`-backend=false`, isolated `TF_DATA_DIR`)
on all 7 modules (all pass). No `apply`/`import`/remote-state mutation was run.

**Does NOT cover (cross-referenced):**
- Security *content* of the IaC (IAM breadth, public API exposure, KMS/CMK) → **Security (02)**.
- Whether the deployed architecture is sound → **Architecture (07)**.
- Reuse-granularity philosophy → **Modularity (09)**.

## Strengths
- `terraform fmt -check -recursive` is clean and `terraform validate` passes on all 7 modules — _evidence: fmt exit 0; validate "Success! The configuration is valid." ×7_
- Provider/Terraform versions pinned and lock files committed in all 7 modules — _evidence: `ecr/providers.tf:2-9` (`required_version >= 1.6.0`, `aws ~> 6.0`), `ecr/.terraform.lock.hcl:5-6` (`version = "6.53.0"`, `constraints = "~> 6.0"`)_
- Clean per-module remote-state segmentation (one S3 key per module) and state excluded from VCS — _evidence: `security/providers.tf:13-18` (`key = "security/terraform.tfstate"`), `documentation/.gitignore:2-4` (`**/.terraform/*`, `*.tfstate`); `git check-ignore` confirms `.terraform/*.tfstate` ignored_
- `for_each` used idiomatically over maps keyed by agent name; no fragile index addressing — _evidence: `runtime/main.tf:4` (`for_each = local.discovered_agents`), `runtime/logs.tf:4,15` (log groups + delivery sources), `runtime/data.tf:39-46`_
- Deliberate lifecycle controls: `ignore_changes` on secret values (managed out-of-band) and `precondition` guards on cross-module ordering — _evidence: `security/main.tf:34-36` (`ignore_changes = [secret_string]`), `runtime/build.tf:5-10` (validate_ecr precondition), `ingestion/main.tf:117-121` (worker policy `runtime_arn != ""` precondition)_
- No secrets committed: secret versions use `REPLACE_ME` placeholders with `ignore_changes`; state (which holds `random_password`) is gitignored — _evidence: `security/main.tf:28-37`, `ingestion/waf.tf:38-41`_
- `default_tags` + consistent naming convention (`${project}-${env}`, `limited-` IAM role prefix) — _evidence: `ecr/providers.tf:20-28`, `roles/main.tf:3` (`${var.role_name_prefix}...`)_
- Explicit `depends_on` where implicit dependencies are insufficient (build→image, log delivery chain, lambda→log group/policy) — _evidence: `runtime/build.tf:36`, `runtime/logs.tf:37-40`, `ingestion/main.tf:210`_

## Weaknesses / Findings

### [Critical] TF-F1 — Remote S3 state without locking
- **Evidence:** `ecr/providers.tf:11-16`, `security/providers.tf:13-18`, `roles/providers.tf:13-18`, `runtime/providers.tf:18-23`, `ingestion/providers.tf:23-28`, `observability/providers.tf:13-18` — every `backend "s3"` block declares `bucket`/`region`/`key`/`encrypt` but **no `dynamodb_table` and no `use_lockfile = true`**. No locking mechanism is present in any module.
- **Impact:** The S3 backend is shared infrastructure (one bucket, six module keys, usable by multiple operators/CI). Without a lock, two concurrent `terraform apply`/`plan -refresh` operations can interleave writes and corrupt or clobber the state file — a data-loss / consistency risk on the source of truth for the whole stack. Per the audit charter, unlocked shared state is a Critical-class defect.
- **Mitigations observed (reduce likelihood, not the gap):** the state bucket has versioning enabled (`bootstrap/main.tf:35-40`) so a corrupted state version can be manually rolled back; the project is a single-operator POC with no CI pipeline driving automated concurrent applies. The control itself is nonetheless absent.
- **Recommendation:** Enable S3-native state locking by adding `use_lockfile = true` to every `backend "s3"` block (supported on the pinned `required_version >= 1.6.0` with the `aws ~> 6.0` provider), then `terraform init -reconfigure` per module. No extra resource to manage.
- **Alternative solution:** DynamoDB lock table — add a small `aws_dynamodb_table` (PAY_PER_REQUEST, `LockID` hash key) in bootstrap and set `dynamodb_table` in each backend.
  - _Pros:_ battle-tested, works on older Terraform/provider versions; central lock visibility.
  - _Cons:_ an extra managed resource + IAM; the account has a `kms:CreateKey` DENY but the table can use the default AWS-owned key; slightly more moving parts than native lockfile.
  - _Effort:_ S. _Cross-pillar impact:_ reliability + (prevents state corruption), cost negligible (on-demand), operational-excellence + .
- **Cross-ref:** none (state-engineering concern owned by this pillar).

### [Medium] TF-F2 — Account id and region hardcoded in backend blocks
- **Evidence:** `ecr/providers.tf:12-13` (`bucket = "amzn-agent-technical-doc-statetf-375039967495-eu-central-1"`, `region = "eu-central-1"`) and the same literal in the 5 other remote modules; also `shared.tfvars:19`.
- **Impact:** The AWS account id (`375039967495`) and region are baked into source across six files. Re-homing to another account/region requires hand-editing every `providers.tf` (the `shared.tfvars` note acknowledges this). Terraform genuinely cannot interpolate variables inside `backend` blocks, so this is a partial constraint — but the value is still duplicated and committed rather than injected.
- **Recommendation:** Use partial backend configuration: leave the `backend "s3" {}` block keyless and pass `-backend-config=backend.hcl` (or `-backend-config="bucket=..."`) at `init`, keeping account/region out of committed source. Application code already resolves the account via `data.aws_caller_identity` (`security/main.tf:1-4`, `ingestion/data.tf:1`), so only the backend literals need this treatment.
- **Alternative solution:** A single generated `backend.hcl` per environment consumed by all modules.
  - _Pros:_ one source of truth, no per-file edits to re-home. _Cons:_ init ergonomics (must remember `-backend-config`); slightly less self-contained. _Effort:_ S. _Cross-pillar impact:_ maintainability +, security + (no account id in VCS — cross-ref Security 02).

### [Medium] TF-F3 — No `prevent_destroy` on critical stateful resources
- **Evidence:** `bootstrap/main.tf:33-35` (state bucket — no lifecycle), `security/main.tf:20-26,44-50` (Secrets Manager secrets), `security/main.tf:55-75` (DynamoDB idempotency table — `point_in_time_recovery` on but no `prevent_destroy`), `observability/cloudtrail.tf:26-29` (CloudTrail log bucket).
- **Impact:** A stray `terraform destroy`, a resource replacement, or a `for_each`/name change could delete the Terraform state bucket itself, the GitHub/HMAC secrets, or the idempotency table — irreversible for the state bucket and disruptive for the rest.
- **Recommendation:** Add `lifecycle { prevent_destroy = true }` to the state bucket, both secrets, the idempotency table, and the CloudTrail bucket. Pair with PITR (already on DynamoDB) and bucket versioning (already on state/CloudTrail buckets).
- **Alternative solution:** None strictly better — `prevent_destroy` is the idiomatic guard; deletion protection can be complemented by AWS-side (e.g. S3 bucket policies) but `prevent_destroy` is the primary IaC control. _Effort:_ S. _Cross-pillar impact:_ reliability +.

### [Low] TF-F4 — Variables lack `validation` blocks; intentionally-unused absorber vars
- **Evidence:** No `validation {}` block exists in any `variables.tf` (e.g. `ingestion/variables.tf`, `runtime/variables.tf`); `environment`, `mention_handle`, `allowed_repositories`, thresholds are unconstrained. `bootstrap/variables.tf:20-24` and `ecr/variables.tf:34-37` declare `state_bucket` purely to "absorb" a `shared.tfvars` value the module does not use.
- **Impact:** Invalid inputs (empty region, malformed handle, absurd thresholds) fail late or silently rather than at plan time; the placeholder vars are dead declarations that slightly muddy the interface.
- **Recommendation:** Add `validation` blocks for high-value invariants (non-empty `allowed_repositories` when quotas rely on it, `environment` against an allowlist, positive numeric thresholds). Consider per-module `-var-file` scoping instead of a single shared file to drop the absorber vars.
- **Alternative solution:** None — validation blocks are the idiomatic mechanism. _Effort:_ S. _Cross-pillar impact:_ maintainability +.

### [Low] TF-F5 — No explicit provider `assume_role`; relies on ambient credentials
- **Evidence:** `ecr/providers.tf:19-29` and all provider blocks: `provider "aws" { region = var.aws_region ... }` — no `assume_role {}`. Credentials come from the ambient environment/profile (`runtime/variables.tf:9-13` exposes `aws_profile` only for the build/push shell step).
- **Impact:** Positive: no long-lived/static credentials are embedded anywhere (good). Gap: least-privilege role assumption is not wired into the provider config, so the effective identity/permission scope is implicit and environment-dependent rather than declared in IaC.
- **Recommendation:** Add a scoped `assume_role { role_arn = var.deploy_role_arn }` (least-privilege deployment role) to the provider blocks, or document the SSO/profile role contract. Keeps deploy identity explicit and auditable.
- **Alternative solution:** Document the required profile/SSO permission set alongside the modules if provider-level assume-role is not desired. _Effort:_ S. _Cross-pillar impact:_ security + (cross-ref Security 02).

### [Info] TF-F6 — Layout/DRY hygiene
- **Evidence:** Outputs inlined in `main.tf` for ecr/security/roles/observability rather than a dedicated `outputs.tf` (present only in ingestion/runtime); `ingestion/outputs.tf:32-38` (`webhook_function_name`, `worker_function_name`) lack `description`; the `terraform{}`/`required_providers`/`default_tags` boilerplate is repeated across all root modules.
- **Impact:** Cosmetic — no functional risk. Minor deviation from the strict `main/variables/outputs/providers` convention and a small documentation gap.
- **Recommendation:** Split outputs into `outputs.tf` per module, add the two missing descriptions; optionally factor shared version/provider config via a generated `versions.tf`. _Effort:_ S.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| TF-01 | Standard module layout, composable modules | Met | `runtime/{main,variables,data,build,logs,outputs}.tf` split by concern; every module has `main.tf`+`variables.tf`; composed via `terraform_remote_state` (`roles/data.tf:3-19`). Note: outputs inlined in 4 modules (TF-F6) |
| TF-02 | Remote state w/ locking; not committed; segmented | Partial | Remote S3 + per-module keys `security/providers.tf:13-18`; state gitignored `documentation/.gitignore:2-4`. **No locking** (no `dynamodb_table`/`use_lockfile`) in any backend → TF-F1 |
| TF-03 | Version constraints pinned; lock committed | Met | `ecr/providers.tf:2-9` (`>= 1.6.0`, `aws ~> 6.0`); lock files in all 7 modules (`ecr/.terraform.lock.hcl:5-6`) |
| TF-04 | Variables typed, described, validated; sane defaults; no unused | Partial | All typed + mostly described w/ sane defaults (`ingestion/variables.tf`); **no `validation` blocks**; unused absorber vars `bootstrap/variables.tf:20-24` → TF-F4 |
| TF-05 | Outputs documented; secrets `sensitive`; no plaintext secrets | Met | Outputs largely described (`security/main.tf:78-99`); secret values are `REPLACE_ME` placeholders w/ `ignore_changes` (`security/main.tf:28-37`); state gitignored. Minor: 2 outputs undescribed (TF-F6) |
| TF-06 | `fmt` clean & `validate` passes | Met | `terraform fmt -check -recursive` exit 0; `terraform validate` "Success" on all 7 modules |
| TF-07 | No hardcoded account/region/ARN where vars/data fit | Partial | App code uses `data.aws_caller_identity`/vars (`ingestion/data.tf:1`); **backend blocks hardcode account id + region** across 6 modules → TF-F2 |
| TF-08 | DRY via modules/`for_each`; minimal copy-paste; no unmanaged resources | Met | `for_each` over agent map (`runtime/main.tf:4`, `runtime/logs.tf`); no copy-pasted resources. Note: provider boilerplate repeated across root modules (TF-F6); image build via `terraform_data`+local-exec (`runtime/build.tf`) |
| TF-09 | `count`/`for_each` correct; no fragile index addressing | Met | Map-keyed `for_each` (`runtime/data.tf:47-52`); `count` used only as conditional-resource toggle (`observability/cloudtrail.tf:26` `count = var.enable_cloudtrail ? 1 : 0`) |
| TF-10 | Explicit dependencies where needed | Met | `depends_on` in `runtime/build.tf:36`, `runtime/logs.tf:37-40`, `ingestion/main.tf:210`, `observability/cloudtrail.tf` |
| TF-11 | `lifecycle`/`prevent_destroy`/`ignore_changes` deliberate | Partial | `ignore_changes` + `precondition` used well (`security/main.tf:34-36`, `runtime/build.tf:5-10`); **no `prevent_destroy`** on state bucket/secrets/DynamoDB → TF-F3 |
| TF-12 | Tagging via `default_tags`/locals; consistent naming | Met | `default_tags` in 6/7 modules (`runtime/providers.tf:26-33`); consistent `${name}` + `limited-` prefix. Security module intentionally untagged (documented KMS DENY workaround `security/providers.tf:20-22`) |
| TF-13 | Least-privilege provider assume-role; no long-lived creds | Partial | No static creds anywhere (good); **no explicit `assume_role`** — relies on ambient profile/env (`ecr/providers.tf:19`) → TF-F5 |
| TF-14 | CI checks for IaC (if a pipeline exists) | N/A | No CI/CD pipeline exists (no `.github/workflows`, no CodeBuild/buildspec). Conditional not triggered; absence of a pipeline is an Operational-Excellence concern — cross-ref **OpEx (01)** |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Enable state locking on every S3 backend (`use_lockfile = true`, or a DynamoDB lock table) — TF-F1 | S |
| P2 | Add `prevent_destroy` to state bucket, secrets, idempotency table, CloudTrail bucket — TF-F3 | S |
| P2 | Move account id/region out of backend blocks via partial backend config (`-backend-config`) — TF-F2 | S |
| P3 | Add `validation` blocks for key variables; drop unused absorber vars — TF-F4 | S |
| P3 | Wire an explicit least-privilege deployment `assume_role` (or document the profile contract) — TF-F5 | S |
| P4 | Split outputs into `outputs.tf`, add 2 missing output descriptions, factor shared provider boilerplate — TF-F6 | S |

## Notes & assumptions
- **Coverage 95% / confidence high:** all 7 modules read in full; `fmt -check` and
  `validate` executed read-only (validate via isolated `TF_DATA_DIR` to bypass the
  pre-initialized S3 backend, which returned 403 on the shared state — expected in a
  static audit with no state credentials, not a finding).
- **TF-02 severity:** classified Critical per the audit charter ("unlocked shared state
  = Critical"). Real-world likelihood is lowered by state-bucket versioning and the
  single-operator/no-CI POC context, but the locking control is objectively absent.
  This finding triggers the global maturity cap; the orchestrator applies it.
- **TF-14 = N/A** (not Missing): the criterion is conditional on an existing pipeline;
  none exists. Counting it as Missing would penalize this pillar for an
  Operational-Excellence gap that is scored there.
- KMS/CMK omissions, IAM breadth, and public-endpoint exposure are security-content
  concerns owned by **Security (02)**; here they only appear as the documented cause of
  the `security` module's absent `default_tags` (TF-12 note).
