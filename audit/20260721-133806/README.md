# Well-Architected & Architecture Audit — agent-technical-doc — 20260721-133806

**Global score:** 76/100  **Global maturity:** 4/5 (Managed)
**Capping:** none — no unresolved Critical finding in any pillar
**Mode:** static  **Profile/Region:** n/a (live_aws OFF)

## Scores by dimension

| # | Dimension | Score | Maturity | Top severity | Applicable |
|---|-----------|-------|----------|--------------|------------|
| 1 | Operational Excellence | 57 | 3 (Defined) | High | yes |
| 2 | Security | 79 | 4 (Managed) | Medium | yes |
| 3 | Reliability | 59 | 3 (Defined) | High | yes |
| 4 | Performance Efficiency | 75 | 4 (Managed) | Medium | yes |
| 5 | Cost Optimization | 82 | 4 (Managed) | Medium | yes |
| 6 | Sustainability | 80 | 4 (Managed) | Low | yes |
| 7 | Architecture | 98 | 5 (Optimized) | Low | yes |
| 8 | Terraform | 77 | 4 (Managed) | High | yes |
| 9 | Modularity | 81 | 4 (Managed) | Medium | yes |
| 10 | Decoupling | 87 | 4 (Managed) | Medium | yes |
| 11 | Scalability | 73 | 3 (Defined) | Medium | yes |
| 12 | Maintainability | 67 | 3 (Defined) | Medium | yes |

Weights applied: Security ×1.5, Reliability ×1.3, all others ×1.0 (default profile, not overridden).
`global_score = Σ(pillar_score × weight) / Σ(weight) = 972.2 / 12.8 ≈ 76`.

## Critical & High findings (consolidated)

No `Critical` findings were raised by any of the 12 pillar agents on the current on-disk state (working tree, including the uncommitted IAM narrowing in `documentation/terraform/ingestion/main.tf`). This is a material change from the predecessor audit (`audit/20260720-000000/`), whose sole Critical (`SEC-F1`, public entrypoint without WAF/CMK) was independently re-verified this run and downgraded to Medium: HMAC verification runs before any processing, all data stores are in fact encrypted at rest (AWS-managed keys), and the missing pieces (WAF, CMK) are hardening gaps rather than exploitable holes.

| id | severity | pillar | title | evidence |
|----|----------|--------|-------|----------|
| OPS-F1 | High | Operational Excellence | No CI/CD pipeline; fully manual deployment | [documentation/README.md:78-95](documentation/README.md#L78-L95) |
| OPS-F2 | High | Operational Excellence | CloudWatch alarms exist but have no notification target wired by default | [documentation/terraform/observability/variables.tf:21-25](documentation/terraform/observability/variables.tf#L21-L25) |
| REL-F1 | High | Reliability | No RTO/RPO defined and no cross-region DR strategy (mono-region) | [documentation/terraform/ingestion/providers.tf:17,24](documentation/terraform/ingestion/providers.tf#L17) |
| TF-F1 | High | Terraform | No state locking configured on any of the 6 S3 Terraform backends | [documentation/terraform/ingestion/providers.tf:12-17](documentation/terraform/ingestion/providers.tf#L12-L17) (+5 other modules) |

Cross-referenced duplicates (same underlying gap, not double-counted): `TF-F3` (Terraform, Medium) and `MNT-F2` (Maintainability, Medium) both restate the "no CI pipeline" gap already scored as `OPS-F1`. `REL-F3` (Reliability, Medium) restates the "alarms with no SNS target" gap already scored as `OPS-F2`. See each pillar's own detail file for the full finding list (Medium/Low/Info findings are numerous and not reproduced here).

## Remediation roadmap

### Quick wins (low effort, high value)
- Add S3 native state locking (`use_lockfile = true`, Terraform ≥1.10 is installed) or a shared DynamoDB lock table to all 6 S3 backends — `TF-F1`.
- Provision an SNS topic + subscription and wire it as the default `alarm_actions` for all CloudWatch alarms — `OPS-F2` / `REL-F3`.
- Attach an AWS WAFv2 WebACL (managed core rule set + rate-based rule) to the public webhook API Gateway stage, as defense-in-depth alongside the existing HMAC check — `SEC-F1`.
- Enable a baseline CloudTrail trail with metric filters/alarms on IAM and Secrets Manager activity — `SEC-F3`.
- Scope the Bedrock `InvokeModel` IAM resource to the two configured model ARNs instead of a wildcard — `SEC-F4`.
- Add `aws_budgets_budget` / Cost Anomaly Detection scoped to the project's cost-allocation tag — `COST-F1`.
- Define a latency SLO and alarm on the existing `DurationMs` p90 EMF metric; add Lambda throttle/concurrency and DynamoDB throttle metrics to the dashboard — `PERF-F1` / `PERF-F2` / `SCAL-F2`.
- Run `terraform fmt -recursive` to clear the one cosmetic diff in `ingestion/main.tf` — `TF-F2`.
- Fix the mismatched `RateLimitQuery` IAM statement (grants a `Query` no code path uses; the real `UpdateItem` access is authorized elsewhere) — `ARC-F1`.
- Add `tests/test_analyzer.py` for the two pure, currently-untested functions (`_extract_json`, `select_model`) — `MNT-F3`.
- Add a linter/formatter + type checker (ruff + mypy) config — `MNT-F1`.
- Pin Python dependencies with a lock file (pip-compile) — `SEC-F5` / `MNT-F5`.

### Structural work
- Stand up a minimal CI/CD pipeline (fmt/validate/pytest/ruff on PR, gated apply on merge) — closes `OPS-F1`, `OPS-F4`, `TF-F3`, `MNT-F2` in one move; the project's own README already flags this as outstanding ("Phase 4 — industrialisation CI").
- Document an explicit RTO/RPO for this workload and decide whether mono-region is an accepted risk or plan a warm-standby DR posture — `REL-F1`.
- Parameterize the Terraform backend per environment and stand up a staging environment — `OPS-F3`.
- Deduplicate the DynamoDB idempotency item-shape/condition logic shared (by convention only, undocumented) between the webhook Lambda and the agent runtime — `MOD-F1` / `DEC-F1`.
- Add a dependency-failure circuit breaker/cooldown and Lambda alias-based safe-rollback for runtime/Lambda deploys — `REL-F2` / `REL-F4`.
- Run an end-to-end synthetic load test before widening the repository allowlist or usage volume, and validate `worker_max_concurrency` against actual Bedrock AgentCore session capacity — `SCAL-F1` / `SCAL-F3`.
- Reintroduce customer-managed KMS keys once the account-level `kms:CreateKey` deny is lifted — `SEC-F2`.

## Method & limitations

- **Mode:** static-only (`live_aws=OFF`); no AWS API calls were made by any sub-agent. No live-AWS corroboration was possible for quota headroom, actual encryption state, or detective-control coverage — these were assessed from Terraform/code only.
- **Target:** repo root `/Users/g.mirambeau/Development/AWS/agent-technical-doc`; the real project is `documentation/` (root-level `terraform/`/`scripts/` are empty legacy stub directories, excluded from scope).
- **Working tree, not last commit:** all 12 pillars evaluated the current on-disk state, which includes one uncommitted change (`documentation/terraform/ingestion/main.tf`, IAM narrowing) on top of `develop` (1 commit ahead of `origin/develop`).
- **Orchestration:** 12 independent sub-agents (general-purpose, one per pillar), each given the same shared context pack (`_context/inventory.md`, a pre-run `terraform fmt -check` scan) plus its own pillar charter/criteria grid/scoring rubric, run in parallel. Each agent read source/IaC directly and cited `path:line` evidence for every verdict and finding; no evidence, no credit.
- **Tools used:** `terraform fmt -check -recursive` (once, shared). `tflint`/`checkov`/`tfsec`/`trivy` were not installed and were not used (noted per-pillar as a coverage limitation, not treated as a finding). Several pillar agents additionally ran the repo's pytest suites directly (read-only, no installs) to verify test-count/pass claims rather than trusting `documentation/README.md`.
- **Prior audit:** `audit/20260720-000000/` (2026-07-20) was available to every sub-agent as an unverified prior claim, explicitly instructed to be independently re-checked rather than carried forward. Deltas of note: Security rose from 68→79 after re-verifying the prior Critical finding was overstated (encryption at rest is in fact present via AWS-managed keys); most other pillars scored somewhat lower than the prior run because this run used a fuller (WAF-aligned) criteria grid with stricter "no evidence = Missing" enforcement, not because the codebase regressed.
- **AWS Documentation MCP:** not confirmed available to sub-agents in this environment; pillar agents were instructed to ground WAF criteria in it where available and otherwise rely on documented AWS Well-Architected Framework knowledge without fabricating doc URLs.
- **De-duplication:** findings raised in more than one pillar for the same underlying gap were scored independently per pillar (per the rubric, each pillar's own criteria grid stands), but are cross-referenced rather than repeated in this synthesis's top-findings table (see above).
- **Coverage:** each pillar reports its own `coverage`/`confidence` in its detail file; typical coverage was 75–95%. No `terraform validate`/`plan` was run against any module (would require `-backend=false` init across 7 chained modules; time-boxed out of this run's scans).
