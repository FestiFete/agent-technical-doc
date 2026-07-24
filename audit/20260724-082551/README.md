# Well-Architected & Architecture Audit — agent-technical-doc — 20260724-082551

**Global score:** 81/100  **Global maturity:** 2/5 (Initial/Ad-hoc — **capped**; uncapped would be 4/5 "Managed")
**Capping:** ⚠️ capped at 2/5 due to **1 open Critical finding** (`TF-F1` — unlocked shared Terraform state).
**Mode:** static (code/IaC only, `live_aws = OFF`)  **Weights:** Security ×1.5, Reliability ×1.3, others ×1.0

> The headline maturity (2/5) is a **rubric-mandated cap**, not a reflection of the raw
> quality: the weighted score is 81/100 ("Managed"). A single, **low-effort** fix
> (enable Terraform state locking) removes the cap and restores maturity to **4/5**.
> This is exactly what the capping rule is designed to surface: an otherwise strong
> system carrying one data-loss-class defect on its source of truth.

## Scores by dimension

| # | Dimension | Score | Maturity | Top severity | Applicable |
|---|-----------|-------|----------|--------------|------------|
| 1 | Operational Excellence | 71 | 3 Defined | High (OPS-F1) | yes |
| 2 | Security | 77 | 4 Managed | Medium | yes |
| 3 | Reliability | 56 | 3 Defined¹ | High (REL-F1²) | yes |
| 4 | Performance Efficiency | 79 | 4 Managed | Medium | yes |
| 5 | Cost Optimization | 86 | 4 Managed | Medium | yes |
| 6 | Sustainability | 98 | 5 Optimized | Low | yes |
| 7 | Architecture | 96 | 5 Optimized | Medium | yes |
| 8 | Terraform | 80 | 4 Managed | **Critical (TF-F1)** | yes |
| 9 | Modularity | 89 | 4 Managed | Medium | yes |
| 10 | Decoupling | 92 | 5 Optimized | Medium | yes |
| 11 | Scalability | 78 | 4 Managed | Medium | yes |
| 12 | Maintainability | 81 | 4 Managed | Medium | yes |

**Weighted global = 1038.3 / 12.8 = 81/100 → uncapped maturity 4; capped to 2 by TF-F1.**

¹ The Reliability sub-agent self-capped its pillar maturity to 2 on its own REL-F1
Critical. The orchestrator **reclassified REL-F1 to High** (see Method §Adjudications),
so the pillar maturity returns to its score band (3). ² REL-F1 shown as High post-adjudication.

## Capping notice

Per the scoring rubric, **any unresolved Critical caps global maturity at 2/5**.

- **`TF-F1` (Terraform, Critical) — Remote S3 state without locking.** No
  `dynamodb_table` and no `use_lockfile = true` in any of the 6 `backend "s3"` blocks
  (`ecr/providers.tf:11`, `security/providers.tf:13`, `roles/providers.tf:13`,
  `runtime/providers.tf:18`, `ingestion/providers.tf:23`, `observability/providers.tf:13`).
  The Terraform pillar charter classifies unlocked shared state as Critical (state
  corruption / data-loss risk on the stack's source of truth). Likelihood is reduced
  by state-bucket versioning + single-operator/no-CI POC context, but the control is
  objectively absent. **Fix: add `use_lockfile = true` to each backend (one line) →
  cap released, maturity → 4/5.**

## Critical & High findings (consolidated)

| id | severity | pillar | title | evidence |
|----|----------|--------|-------|----------|
| TF-F1 | **Critical** | Terraform | Remote S3 state without locking (no lock table / no use_lockfile) | `*/providers.tf` backend blocks |
| REL-F1 | High² | Reliability | No alarm detects a silent full-pipeline stall; `alarm_actions=[]` (no SNS target) | `observability/main.tf:24-70`, `observability/variables.tf:21-25`, `ingestion/main.tf:238-247` |
| REL-F2 | High | Reliability | Permanent worker errors dropped without DLQ/metric (no `ReportBatchItemFailures`) | `worker-dispatcher/handler.py:88-96`, `ingestion/main.tf:238-247` |
| REL-F3 | High | Reliability | No blast-radius containment / safe-change for shared worker role + in-place runtime deploy | `ingestion/main.tf:112-169`, `runtime/main.tf:11-16` |
| OPS-F1 | High | Operational Excellence | No CI/CD pipeline; 127+ tests never run as an enforced gate | no `.github/workflows`; `README.md` manual apply loop |

_De-duplication:_ the CI/CD gap surfaces as OPS-F1 (pipeline), MNT-F1 (quality gate),
SEC-F5 (supply-chain gate) and TF-14 (N/A) — scored once per distinct facet, primary =
OPS-F1. The `alarm_actions=[]` notification gap is shared by REL-F1 / OPS-F2 (primary
REL-F1). Dependency-pinning = MNT-F2 (primary) / SEC-F4. Tarball-in-memory = PERF-F2 /
SCAL-F3. `design.md` drift = ARC-F1 / cross-ref Maintainability.

## Remediation roadmap

### Quick wins (low effort, high value)
1. **[Critical] Enable Terraform state locking** — `use_lockfile = true` in every
   `backend "s3"` block (or a DynamoDB lock table), `init -reconfigure`. Removes the
   global cap. _(TF-F1, effort S)_
2. **[High] Wire an SNS topic to `alarm_actions`** + add a **main-queue
   `ApproximateAgeOfOldestMessage` alarm** — closes the silent-stall blind spot and
   gives alarms a destination. _(REL-F1/OPS-F2, effort S)_
3. **[High] Enable `ReportBatchItemFailures`** (or emit a `PermanentErrors` EMF metric
   + alarm) so dropped messages are visible. _(REL-F2, effort S–M)_
4. **[Medium] `prevent_destroy`** on state bucket, secrets, idempotency table,
   CloudTrail bucket. _(TF-F3, effort S)_
5. **[Medium] AWS Budgets + Cost Anomaly Detection** scoped to project tags.
   _(COST-F1, effort S)_
6. **[Medium] Reconcile `design.md`** with the 7-module layout / Python 3.12 (point to
   `ARCHITECTURE.md` as source of truth). _(ARC-F1, effort S)_

### Structural work
7. **[High] CI/CD pipeline** — pytest (both suites) + `terraform fmt/validate` + `ruff`
   + `pip-audit` as a required gate, then build/push + ordered apply; add a post-apply
   ingestion smoke test (also addresses REL-F3 safe-change). _(OPS-F1/MNT-F1/REL-F3, effort M)_
8. **[Medium] Restore SSE-KMS CMKs** (Secrets Manager, DynamoDB, SQS) with rotation
   once `kms:CreateKey` is available; automate HMAC rotation; drop PAT fallback for
   prod. _(SEC-F1/SEC-F3, effort M)_
9. **[Medium] Add/reference detective baseline** (GuardDuty, Config, Security Hub —
   CloudTrail already present). _(SEC-F2, effort M)_
10. **[Medium] Hash-pin Python deps** (`requirements.lock`) + `pip-audit`. _(MNT-F2/SEC-F4, effort S–M)_
11. **[Medium] Prompt caching** on the stable system-prompt prefix. _(PERF-F1, effort S)_
12. **[Medium] Capacity model** for `worker_max_concurrency` (derive from Bedrock TPS /
    AgentCore session quotas) + shard/justify the per-repo rate counter. _(SCAL-F1/F2, effort M)_
13. **[Medium] Partial backend config** to remove hardcoded account id/region from
    `providers.tf`; enables multi-env. _(TF-F2, effort S)_
14. **[Medium] `schema_version`** on the SQS/runtime payloads. _(DEC-F1, effort S)_
15. **[Medium] Extract shared GitHub HTTP helper** (`github_client`/`github_auth` dup).
    _(MOD-F1, effort M)_

## Method & limitations

- **Static audit** (`live_aws = OFF`): no AWS API calls. Controls verifiable only at
  runtime (effective encryption, live alarm state, active detective services) are
  judged on IaC, not deployed state. Tooling present: `terraform` (used: `fmt -check`,
  `validate -backend=false`) and `aws`; **absent**: tflint/checkov/tfsec/trivy/ruff
  (not installed; not auto-installed) — pillars relied on code analysis + read-only
  `terraform validate` (passes on all 7 modules) and both `pytest` suites (130 passing).
- **Context-pack staleness corrected mid-audit.** The initial inventory (built from
  session memory) missed `terraform/ingestion/waf.tf` (CloudFront + WAFv2 +
  `X-Origin-Verify`) and `terraform/observability/cloudtrail.tf`, both of which **exist**
  in the current code. The pack was corrected and pillars 07–12 were told WAF + CloudTrail
  are PRESENT. Consequently the earlier "public API without WAF" Critical from prior
  audits is **remediated** (Security scored accordingly).
- **Adjudications by the orchestrator (transparent):**
  1. **REL-F1 reclassified Critical → High.** The evidence (missing main-queue age
     alarm, `alarm_actions=[]`, no `ReportBatchItemFailures`) proves a serious
     detection/notification gap, but not an imminent-failure or data-loss defect per
     the rubric's Critical definition; the sub-agent's "occurred in production" basis is
     not supported by any evidence in the repo/context pack. Reliability pillar maturity
     therefore returns to its score band (3), and REL-F1 does not contribute to capping.
  2. **Security SEC-10 / SEC-F2 partly overstated.** The Security sub-agent scored
     detective controls "Missing" without seeing `observability/cloudtrail.tf` (confirmed
     present). CloudTrail IS present → SEC-10 should be **Partial** (GuardDuty/Config/
     Security Hub still absent) and SEC-F2 is a Medium gap, not a full absence. The true
     Security score is marginally higher (~79); the reported 77 is kept (conservative)
     with this note.
  3. **TF-F1 kept Critical** per the Terraform charter's explicit rule ("unlocked shared
     state = Critical") → global cap applied.
- **Coverage/confidence:** per-pillar 90–100%, confidence medium–high. Deployed-state
  facts unverifiable statically are the main uncertainty. Every finding carries code/IaC
  evidence (`path:line`); no live ARNs asserted.
- **Read-only guarantee honored:** the only writes are the audit deliverables under this
  directory. No target file or AWS resource was modified.

## Deliverables in this directory
- `README.md` (this file) — executive synthesis.
- `NN-<pillar>.md` ×12 — per-pillar detail (charter, strengths, findings, criteria grid).
- `summary.json` — machine-readable aggregate (embeds the 12 pillar JSON objects).
- `_context/inventory.md` — shared context pack (with the CORRECTION/REFRESH section).
