# Modularity — Audit

**Score:** 81/100  **Maturity:** 4 (Managed)  **Coverage:** 90%  **Confidence:** high
**Applicable:** yes

## Charter & scope

Assess how well the system is decomposed into cohesive, well-bounded, reusable units: cohesion, boundary clarity, interface quality, and reuse without duplication. Runtime/temporal coupling is covered by Decoupling (10); whole-system design choices by Architecture (07); Terraform module mechanics by Terraform (08).

Scope examined: the `docagent/` package (18 modules, not counting `__init__.py`: `analyzer`, `comments`, `committer`, `config`, `correlation`, `doc_builder`, `drawio`, `github_auth`, `github_client`, `idempotency`, `metrics`, `orchestrator`, `paths`, `payload`, `repo_reader`, `retry`, `secrets`, `selection`), the AgentCore entrypoint `agent.py`, and the two Lambda handlers (`webhook-receiver/handler.py`, `worker-dispatcher/handler.py`), including the new `verify_origin` addition and their duplication surface against `docagent/`.

## Delta since the prior run (audit/20260721-133806/09-modularity.md, score 81/100)

Independently re-verified, full re-check (not carried forward):

- **`docagent/` package is byte-for-byte unchanged.** Fresh `wc -l docagent/*.py` reproduces the exact same per-file line counts and 2162-line total as the prior run (`orchestrator.py` still the largest at 270 lines; `__init__.py` still 19 lines with the same stale 8-entry `__all__`). Confirmed via `git log --oneline -- .../docagent/` showing no commits since the prior audit touched this directory (context pack §"Everything else" independently corroborated).
- **MOD-F1 (idempotency duplication) — still present, re-verified line-for-line.** `handler.py:160-183` (`_claim_idempotency`) and `docagent/idempotency.py:22-52` (`claim`) still implement the identical DynamoDB item shape (`pk`/`status`/`correlation_id`/`created_at`/`ttl`) and `ConditionExpression="attribute_not_exists(pk)"` in two independently deployed artifacts. No change.
- **MOD-F2 (HTTP transport duplication) — still present, re-verified line-for-line.** `docagent/github_auth.py:41-54` (`_default_http`) and `docagent/github_client.py:58-69` (`_http`) remain near-identical `urllib.request` boilerplate (build `Request`, attach headers, `urlopen(timeout=...)`, catch `HTTPError`/`URLError`). Additionally noted on this pass (not previously called out explicitly): `_auth_headers` (`github_auth.py:68-77`) and `GitHubClient._headers` (`github_client.py:71-77`) build near-identical GitHub auth header dicts (`Authorization`/`Accept`/`User-Agent`/`X-GitHub-Api-Version`) — same root cause as MOD-F2, folded into that finding rather than raised separately since remediation (a shared `docagent/http.py` helper) would naturally absorb both.
- **New: `verify_origin()` in `webhook-receiver/handler.py:59-73`.** This is the one functional addition to the scope since the prior run (SEC-F1, CloudFront origin-verification header check). Assessed for cohesion below — verdict: fits cleanly, no new duplication or coupling introduced.
- **No other changes** in scope for this pillar. The previously-uncommitted `documentation/terraform/ingestion/main.tf` diff noted in `git status` at the start of this session is Terraform-only (out of this pillar's Python-module charter) and is, in any case, already committed at the current `HEAD` (`f89ea51`) with a clean working tree — nothing left uncommitted to assess.

Net: **score unchanged at 81/100.** Both duplication findings persist unaddressed since the last run; the one new addition (`verify_origin`) is well-executed and does not move the score.

## Strengths

- Clean, acyclic intra-package dependency graph: `config` is the stable base with no internal dependencies; pure/deterministic modules (`paths`, `comments`, `doc_builder`, `selection`, `repo_reader`) depend only on `config`/`correlation`; `orchestrator` sits at the top and pulls in I/O-heavy collaborators (`github_auth`, `secrets`, `github_client`, `repo_reader`, `analyzer`, `idempotency`) only via lazily-constructed, injectable closures — re-verified fresh, no cycles found across any of the 18 modules. — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:48-77` (`default_deps`), full grep of `from .` imports across `docagent/*.py`_
- Strong domain-oriented decomposition: each module owns one clearly named responsibility (GitHub auth vs GitHub REST client vs repo extraction vs file selection vs LLM analysis vs doc rendering vs diagram rendering vs git commit vs PR comments vs idempotency vs retry vs metrics), each with a docstring stating its single purpose and any security invariant it enforces. — _evidence: `docagent/idempotency.py:1-6`, `docagent/github_auth.py:1-21`, `docagent/github_client.py:1-11`_
- No god modules: the largest module is `orchestrator.py` at 270 lines (one cohesive workflow — DI wiring, PR resolution, run execution — not a dumping ground); package median ~95 lines; re-measured directly this run with identical results to the prior run. — _evidence: `wc -l docagent/*.py` → range 19–270 lines, total 2162 across 18 files_
- The new `verify_origin()` addition is cleanly cohesive with the existing `verify_signature()`: same section (`# --- Fonctions pures ---`), same signature shape (raw inputs in, `bool` out), same constant-time-comparison discipline (`hmac.compare_digest`), same "no oracle" design note, called first in `lambda_handler` with an explicit ordering comment. It introduces no new duplication (the two functions share only a 1-line comparison idiom, not enough to warrant extraction) and no new coupling (it is a pure function taking `header_value`/`secret` as plain strings, with the same fail-open-when-unconfigured contract documented as its stated test/local-dev escape hatch). — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:59-83` (`verify_origin`/`verify_signature` side by side), `handler.py:242-254` (call order + shared rejection message)_
- Lambda handler keeps its decision logic in pure, dependency-free functions (`verify_signature`, `verify_origin`, `evaluate_comment`, `parse_api_event`) separated from the boto3 I/O helpers (`_get_secret`, `_claim_idempotency`, `_enqueue`, `_increment_repo_counter`) — good internal separation of concerns even though the handler is necessarily a separate deployment unit from `docagent/`. — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:59-142` (pure functions) vs `handler.py:150-233` (I/O helpers)_

## Weaknesses / Findings

### [Medium] MOD-F1 — Idempotency claim logic duplicated between webhook Lambda and docagent (unresolved since prior run)
- **Evidence:** `documentation/scripts/lambdas/webhook-receiver/handler.py:160-183` (`_claim_idempotency`) vs `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py:22-52` (`claim`)
- **Impact:** Both implement the same DynamoDB idempotency contract independently — identical item shape (`pk`/`status`/`correlation_id`/`created_at`/`ttl`) and `ConditionExpression="attribute_not_exists(pk)"` — but ship as different deployment artifacts (Lambda zip vs container image). A future schema change (e.g. GSI, field rename, TTL semantics) applied to one side and not the other would silently break idempotency guarantees for either the webhook-dedup path or the agent-run-dedup path, with no test or type system catching the drift. Confirmed still unaddressed one audit cycle later — no cross-reference comment was added to either file in the interim either.
- **Recommendation:** Factor the DynamoDB item-shape/condition logic into one small shared function set and make both artifacts depend on the same source (Lambda Layer, or a `documentation/scripts/common/` package copied into both build contexts). At minimum, add an explicit cross-reference comment in both files until the refactor happens — this low-cost interim step still has not been taken.
- **Alternative solution:** Extract `documentation/scripts/common/idempotency.py` with pure `build_put_item(key, correlation_id, ttl_days) -> dict` / `is_duplicate(client_error) -> bool` helpers; package as a Lambda Layer attached to `webhook-receiver` and as an installed dependency inside the agent container image.
  - Pros: single source of truth for the idempotency contract, removes drift risk, unit-testable once.
  - Cons: adds a build/packaging step to a project with no CI yet; Lambda Layer and container image use different packaging mechanisms so the "shared" module still needs two build paths.
  - Effort: M. Cross-pillar impact: Terraform (08 — Lambda Layer resource), Operational Excellence (01 — packaging/CI).

### [Low] MOD-F2 — HTTP transport and auth-header construction duplicated between github_auth.py and github_client.py (unresolved since prior run)
- **Evidence:** `docagent/github_auth.py:41-54` (`_default_http`) vs `docagent/github_client.py:58-69` (`GitHubClient._http`); also `docagent/github_auth.py:68-77` (`_auth_headers`) vs `docagent/github_client.py:71-77` (`GitHubClient._headers`)
- **Impact:** Both implement near-identical `urllib.request` boilerplate (build `Request`, attach headers, `urlopen(..., timeout=...)`, catch `HTTPError`/`URLError`) with only the error class and return shape differing, and both build near-identical GitHub API header dicts (`Authorization`/`Accept`/`User-Agent`/`X-GitHub-Api-Version`). A transport-level fix (timeout tuning, redirect handling, retry-after parsing) or a header-level change (e.g. API version bump) applied to one will not automatically apply to the other. Confirmed still unaddressed one audit cycle later.
- **Recommendation:** Extract a shared low-level `_urllib_request(method, url, *, headers, body, timeout) -> (status, headers, body_bytes)` helper and a shared header-builder (e.g. a small `docagent/http.py`), and have `github_auth` and `github_client` wrap it with their own error classes (`GitHubAuthError` / `GitHubError`).
- **Alternative solution:** Same as above — new internal module, each call site keeps its own exception type.
  - Pros: one transport/header implementation to maintain and test; both modules already expose injectable `http`/transport hooks so refactor risk is low.
  - Cons: minor churn to two already-tested modules for a small (~25 line combined) duplication.
  - Effort: S. Cross-pillar impact: none significant.

### [Low] MOD-F3 — `docagent/__init__.py` public surface (`__all__`) is stale relative to the actual package (unresolved since prior run)
- **Evidence:** `docagent/__init__.py:10-19` lists 8 modules (`config`, `correlation`, `repo_reader`, `selection`, `drawio`, `doc_builder`, `github_client`, `secrets`) out of the 18 that exist in the package; missing from `__all__`: `analyzer`, `comments`, `committer`, `github_auth`, `idempotency`, `metrics`, `orchestrator`, `paths`, `payload`, `retry`.
- **Impact:** `__all__` is the package's declared public surface (criterion MOD-10) but under-represents reality — every consumer (e.g. `orchestrator.py:52,58,62,68` via lazy imports) actually imports directly from submodules like `docagent.github_auth`/`docagent.analyzer`, bypassing `__all__` entirely, making the list effectively decorative and misleading to a new contributor. Confirmed byte-identical to the prior run — no change.
- **Recommendation:** Either update `__all__` to reflect all submodules meant to be imported externally, or drop the `__all__` declaration and rely on per-module docstrings (already the primary, accurate documentation of scope) plus normal submodule import paths.
- **Alternative solution:** None — this is a low-cost documentation-consistency fix (S effort), not an architectural change.

## Criteria grid

| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| MOD-01 | High cohesion: each module has one clear responsibility. | Met | `docagent/idempotency.py:1-6`, `docagent/retry.py:1-10` (unchanged, re-verified), `handler.py:59-83` (new `verify_origin` fits cleanly alongside `verify_signature`) |
| MOD-02 | Clear, documented public interfaces; internals encapsulated. | Partial | Strong module docstrings throughout (e.g. `docagent/github_auth.py:1-21`); but `docagent/__init__.py:10-19` `__all__` is stale (MOD-F3, unresolved) |
| MOD-03 | Boundaries by domain/feature, not accidental/technical dumping grounds. | Met | 18 domain-named modules unchanged; new `verify_origin` placed in the correct domain (`handler.py`'s "Fonctions pures" auth/validation section, not a misc/utils dump) |
| MOD-04 | Low duplication: shared logic factored into reusable units (DRY). | Partial | `handler.py:160-183` vs `docagent/idempotency.py:22-52` (MOD-F1, re-verified line-for-line, unchanged); `docagent/github_auth.py:41-77` vs `docagent/github_client.py:58-77` (MOD-F2, re-verified, unchanged plus header-builder duplication now also noted) |
| MOD-05 | No "god" modules/files; sizes reasonable & focused. | Met | `wc -l docagent/*.py`: max 270 (`orchestrator.py`), total 2162/18 files — identical to prior run; `handler.py` grew to 293 lines but remains one cohesive webhook-ingress workflow, not a dumping ground |
| MOD-06 | Dependency direction is sane (stable abstractions; no cycles). | Met | Fresh import graph via grep of `from .` across `docagent/*.py`: `config` still the acyclic base; `orchestrator.py:48-77` (`default_deps`) still inverts dependencies via lazy closures |
| MOD-07 | Reusable units are genuinely reusable (no hidden global coupling). | Met | Pure/testable modules with injectable transport/sleep/http params unchanged: `docagent/github_client.py:49-56`, `docagent/github_auth.py:87-95`; `verify_origin(header_value, secret)` is a pure, dependency-free function — `handler.py:59-73` |
| MOD-08 | Consistent, discoverable module organization across the repo. | Met | Flat, one-file-per-domain `docagent/` package; `tests/` mirrors it 1:1 (`tests/test_github_auth.py`, `tests/test_committer.py`, etc.); `documentation/scripts/lambdas/tests/test_webhook_receiver.py` covers the new `verify_origin` alongside existing handler tests |
| MOD-09 | Clear separation of concerns (domain vs infra vs I/O). | Met | Pure domain modules (`doc_builder.py`, `drawio.py`, `selection.py`, `paths.py`) vs I/O modules (`github_client.py`, `github_auth.py`, `secrets.py`) kept distinct, unchanged; `handler.py` keeps `verify_origin`/`verify_signature`/`evaluate_comment` pure and separate from `_get_secret`/`_claim_idempotency`/`_enqueue` I/O helpers — `handler.py:59-142` vs `150-233` |
| MOD-10 | Public surface is minimal (no leaking internals). | Partial | Consistent `_`-prefixed private helpers throughout (e.g. `handler.py:150,160,186,204`, `docagent/repo_reader.py:27`); but package-level `__all__` is stale (MOD-F3, unresolved), so the declared public surface doesn't match actual usage |

## Prioritized improvements

| priority | action | effort |
|----------|--------|--------|
| P1 | Deduplicate the DynamoDB idempotency item-shape/condition logic between `webhook-receiver/handler.py` and `docagent/idempotency.py` (shared helper + Lambda Layer, or at minimum a documented cross-reference comment as an interim step — neither has happened across two audit cycles) | M |
| P2 | Extract a shared low-level urllib transport + auth-header helper for `github_auth.py`/`github_client.py` | S |
| P3 | Refresh or remove the stale `__all__` list in `docagent/__init__.py` | S |

## Notes & assumptions

- This is a full independent re-audit, not a delta-only pass: every criterion was re-checked against current on-disk code (fresh `wc -l`, fresh import-graph grep, direct file reads of both duplication-finding pairs) rather than trusting the prior run's `path:line` citations at face value. All three prior findings (MOD-F1, MOD-F2, MOD-F3) were reproduced with matching or updated line numbers, confirming they remain live, not stale artifacts of the prior report.
- The one functional change in scope since the prior run — `verify_origin()` in `webhook-receiver/handler.py` — was assessed specifically for cohesion per the task brief and found to integrate cleanly: correct placement, consistent style/contract with its sibling `verify_signature()`, no new duplication, no new global/hidden coupling. It does not move MOD-01/03/07/09 off `Met`.
- The Lambda-vs-`docagent` duplication (MOD-F1) remains partially structurally justified — Lambda zip packages and the agent's container image are genuinely separate deployment units with no existing shared-library mechanism in this CI-less project — but the *logic* duplication is real, unaddressed for a second consecutive audit cycle, and worth tracking; scored as Partial (not Missing) on MOD-04 to reflect that nuance.
- `handler.py` grew from what the prior report implicitly scoped (evidence citations up to line ~170) to 293 lines; the additional ~120 lines are pre-existing per-repo rate-limiting logic (`_window_bucket`, `_rate_key`, `_increment_repo_counter`, `_rate_limited`) that predates the prior modularity audit (introduced in commit `665ea4d`, before the `20260721-133806` baseline) — not new in this delta, and does not change any verdict; it stays a cohesive part of the webhook-ingress workflow.
- Did not deeply review `tests/`/`e2e/` content beyond existence/naming (out of charter scope; used only to support MOD-08).
- Terraform files (including the now-committed `ingestion/main.tf` diff visible in the session's starting `git status`) were not in scope for this pillar (covered by Terraform pillar 08).
