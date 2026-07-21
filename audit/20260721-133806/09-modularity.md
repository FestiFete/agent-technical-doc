# Modularity — Audit

**Score:** 81/100  **Maturity:** 4 (Managed)  **Coverage:** 90%  **Confidence:** high
**Applicable:** yes

## Charter & scope

Assess how well the system is decomposed into cohesive, well-bounded, reusable units: cohesion, boundary clarity, interface quality, and reuse without duplication. Runtime/temporal coupling is covered by Decoupling (10); whole-system design choices by Architecture (07); Terraform module mechanics by Terraform (08).

Scope examined: the `docagent/` package (18 modules, not counting `__init__.py`: `analyzer`, `comments`, `committer`, `config`, `correlation`, `doc_builder`, `drawio`, `github_auth`, `github_client`, `idempotency`, `metrics`, `orchestrator`, `paths`, `payload`, `repo_reader`, `retry`, `secrets`, `selection`), the AgentCore entrypoint `agent.py`, and the two Lambda handlers (`webhook-receiver/handler.py`, `worker-dispatcher/handler.py`), including their duplication surface against `docagent/`.

## Strengths

- Clean, acyclic intra-package dependency graph: `config` is the stable base with no internal dependencies; pure/deterministic modules (`paths`, `comments`, `doc_builder`, `selection`, `repo_reader`) depend only on `config`/`correlation`; `orchestrator` sits at the top and pulls in I/O-heavy collaborators (`github_auth`, `secrets`, `github_client`, `repo_reader`, `analyzer`, `idempotency`) only via lazily-constructed, injectable closures — no cycles found across any of the 18 modules. — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:34-91`, grep of all `from .` imports across `docagent/*.py`_
- Strong domain-oriented decomposition: each module owns one clearly named responsibility (GitHub auth vs GitHub REST client vs repo extraction vs file selection vs LLM analysis vs doc rendering vs diagram rendering vs git commit vs PR comments vs idempotency vs retry vs metrics), each with a docstring stating its single purpose and any security invariant it enforces. — _evidence: `docagent/paths.py:1-8`, `docagent/retry.py:1-10`, `docagent/selection.py:1-13`, `docagent/committer.py:1-10`_
- No god modules: the largest module is `orchestrator.py` at 270 lines (and it is one cohesive workflow — DI wiring, PR resolution, run execution — not a dumping ground); the package median is ~95 lines. — _evidence: `wc -l docagent/*.py` → range 19–270 lines, total 2162 across 18 files_
- Dependency-inversion via `OrchestratorDeps` dataclass of `Callable`s lets the orchestrator depend on abstractions rather than concrete boto3/strands/GitHub clients, with real implementations constructed lazily in `default_deps()` — this is precisely the "stable abstractions" pattern the criteria ask for. — _evidence: `docagent/orchestrator.py:34-91`_
- The AgentCore entrypoint (`agent.py`) is a thin, ~120-line adapter that only parses the payload and threads the background run to `docagent.orchestrator.run_documentation` — it contains no business logic of its own. — _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:42-119`_
- Lambda handlers keep their decision logic in pure, dependency-free functions (`verify_signature`, `evaluate_comment`, `parse_api_event`) separated from the boto3 I/O helpers (`_get_secret`, `_claim_idempotency`, `_enqueue`) — good internal separation of concerns even though the handlers are necessarily separate deployment units from `docagent/`. — _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:56-63,76-111,130-170`_

## Weaknesses / Findings

### [Medium] MOD-F1 — Idempotency claim logic duplicated between webhook Lambda and docagent
- **Evidence:** `documentation/scripts/lambdas/webhook-receiver/handler.py:140-163` (`_claim_idempotency`) vs `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py:22-52` (`claim`)
- **Impact:** Both implement the same DynamoDB idempotency contract independently — identical item shape (`pk`/`status`/`correlation_id`/`created_at`/`ttl`) and `ConditionExpression="attribute_not_exists(pk)"` — but in two codebases that ship as different deployment artifacts (Lambda zip vs container image). A future schema change (e.g. adding a GSI, renaming a field, changing TTL semantics) applied to one side and not the other would silently break idempotency guarantees for either the webhook-dedup path or the agent-run-dedup path, without any test or type system catching the drift.
- **Recommendation:** Factor the DynamoDB item-shape/condition logic into one small shared function set and make both artifacts depend on the same source (Lambda Layer, or a `documentation/scripts/common/` package copied into both build contexts by the existing manual deploy process). At minimum, add an explicit cross-reference comment in both files ("schema must stay in sync with docagent/idempotency.py — see ...") until such a refactor happens.
- **Alternative solution:** Extract `documentation/scripts/common/idempotency.py` with pure `build_put_item(key, correlation_id, ttl_days) -> dict` / `is_duplicate(client_error) -> bool` helpers; package it as a Lambda Layer attached to `webhook-receiver` (and `worker-dispatcher` if useful) and as a regular installed dependency inside the agent container image.
  - Pros: single source of truth for the idempotency contract, removes drift risk, unit-testable once.
  - Cons: adds a build/packaging step to a project with no CI yet (README already flags CI as "à faire"); Lambda Layer and container image use different packaging mechanisms so the "shared" module still needs two build paths, not one.
  - Effort: M. Cross-pillar impact: Terraform (08 — Lambda Layer resource), Operational Excellence (01 — packaging/CI).

### [Low] MOD-F2 — HTTP transport logic duplicated between github_auth.py and github_client.py
- **Evidence:** `docagent/github_auth.py:41-54` (`_default_http`) vs `docagent/github_client.py:58-69` (`GitHubClient._http`)
- **Impact:** Both implement near-identical `urllib.request` boilerplate (build `Request`, attach headers, `urlopen(..., timeout=...)`, catch `HTTPError`/`URLError`) with only the error class and return shape differing. A transport-level fix (e.g. connection timeout tuning, redirect handling, retry-after parsing) applied to one will not automatically apply to the other.
- **Recommendation:** Extract a shared low-level `_urllib_request(method, url, *, headers, body, timeout) -> (status, headers, body_bytes)` helper (e.g. a small `docagent/http.py`), and have `github_auth` and `github_client` wrap it with their own error classes (`GitHubAuthError` / `GitHubError`).
- **Alternative solution:** Same as above — new internal module, each call site keeps its own exception type.
  - Pros: one transport implementation to maintain/test; both modules already expose injectable `http`/transport hooks so refactor risk is low.
  - Cons: minor churn to two already-tested modules for a small (~15 line) duplication.
  - Effort: S. Cross-pillar impact: none significant.

### [Low] MOD-F3 — `docagent/__init__.py` public surface (`__all__`) is stale relative to the actual package
- **Evidence:** `docagent/__init__.py:10-19` lists 8 modules (`config`, `correlation`, `repo_reader`, `selection`, `drawio`, `doc_builder`, `github_client`, `secrets`) out of the 18 that exist in the package; missing from `__all__`: `analyzer`, `comments`, `committer`, `github_auth`, `idempotency`, `metrics`, `orchestrator`, `paths`, `payload`, `retry`.
- **Impact:** `__all__` is the package's declared public surface (criterion MOD-10) but it under-represents reality — every consumer in the codebase (e.g. `agent.py:42-44`) actually imports directly from submodules like `docagent.orchestrator` and `docagent.payload`, bypassing `__all__` entirely, which makes the list effectively decorative and misleading to a new contributor trying to understand the package's intended public API.
- **Recommendation:** Either update `__all__` to reflect all submodules meant to be imported externally, or drop the `__all__` declaration and rely on the per-module docstrings (which are already the primary, accurate documentation of scope) plus normal submodule import paths.
- **Alternative solution:** None — this is a low-cost documentation-consistency fix (S effort), not an architectural change.

## Criteria grid

| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| MOD-01 | High cohesion: each module has one clear responsibility. | Met | `docagent/paths.py:1-8`, `docagent/retry.py:1-10`, `docagent/selection.py:1-13`, `docagent/orchestrator.py:1-13` |
| MOD-02 | Clear, documented public interfaces; internals encapsulated. | Partial | Strong module docstrings throughout (e.g. `docagent/committer.py:1-10`); but `docagent/__init__.py:10-19` `__all__` is stale (see MOD-F3) |
| MOD-03 | Boundaries by domain/feature, not accidental/technical dumping grounds. | Met | 18 domain-named modules: `github_auth.py`, `github_client.py`, `repo_reader.py`, `analyzer.py`, `doc_builder.py`, `drawio.py`, `committer.py`, `comments.py` |
| MOD-04 | Low duplication: shared logic factored into reusable units (DRY). | Partial | `documentation/scripts/lambdas/webhook-receiver/handler.py:140-163` vs `docagent/idempotency.py:22-52` (MOD-F1); `docagent/github_auth.py:41-54` vs `docagent/github_client.py:58-69` (MOD-F2) |
| MOD-05 | No "god" modules/files; sizes reasonable & focused. | Met | `wc -l docagent/*.py`: max 270 (`orchestrator.py`), median ~95, total 2162/18 files |
| MOD-06 | Dependency direction is sane (stable abstractions; no cycles). | Met | Import graph via grep of `from .` across `docagent/*.py`: `config` is the acyclic base; `orchestrator.py:34-91` inverts dependencies on I/O collaborators via `OrchestratorDeps` |
| MOD-07 | Reusable units are genuinely reusable (no hidden global coupling). | Met | Pure/testable modules with injectable transport/sleep/http params: `docagent/retry.py:53-61`, `docagent/github_client.py:49-56`, `docagent/github_auth.py:87-95`; module-level caches (`docagent/secrets.py:16`, webhook `handler.py:30`) are intentional, documented, minor |
| MOD-08 | Consistent, discoverable module organization across the repo. | Met | Flat, one-file-per-domain `docagent/` package; `tests/` largely mirrors it 1:1 (`tests/test_committer.py`, `tests/test_doc_builder.py`, etc.) |
| MOD-09 | Clear separation of concerns (domain vs infra vs I/O). | Met | Pure domain modules (`doc_builder.py`, `drawio.py`, `selection.py`, `paths.py`, `comments.py`, `payload.py`) vs I/O modules (`github_client.py`, `github_auth.py`, `secrets.py`, `repo_reader.py`, `analyzer.py`) kept distinct; `orchestrator.py:94-107` builds domain context separately from I/O calls |
| MOD-10 | Public surface is minimal (no leaking internals). | Partial | Consistent `_`-prefixed private helpers throughout (e.g. `docagent/repo_reader.py:27`, `docagent/analyzer.py:77`); but package-level `__all__` is stale (MOD-F3), so the declared public surface doesn't match actual usage |

## Prioritized improvements

| priority | action | effort |
|----------|--------|--------|
| P1 | Deduplicate the DynamoDB idempotency item-shape/condition logic between `webhook-receiver/handler.py` and `docagent/idempotency.py` (shared helper + Lambda Layer, or documented sync requirement as an interim step) | M |
| P2 | Extract a shared low-level urllib transport helper for `github_auth.py`/`github_client.py` | S |
| P3 | Refresh or remove the stale `__all__` list in `docagent/__init__.py` | S |

## Notes & assumptions

- Prior run (`audit/20260720-000000/09-modularity.md`, score 85/100) was independently re-verified against current on-disk code, not taken as ground truth. This run scores 81/100 — close but slightly lower, driven by two concrete duplication findings (idempotency logic, HTTP transport) that were substantiated with `path:line` evidence and were not present/quantified in the prior report as far as could be determined.
- Line counts for all 18 `docagent/*.py` modules were measured directly (`wc -l`) to ground the "no god module" verdict in real numbers rather than impression.
- The Lambda-vs-`docagent` duplication (MOD-F1) is partially structurally justified — Lambda zip packages and the agent's container image are genuinely separate deployment units with no existing shared-library mechanism in this CI-less project — but the *logic* duplication is real and worth tracking; it is scored as Partial (not Missing) on MOD-04 to reflect that nuance.
- Did not deeply review `tests/` or `e2e/` content for this pillar (out of charter scope); only used their existence/naming to support MOD-08.
- `terraform` files were not in scope for this pillar (covered by Terraform pillar 08); the uncommitted `ingestion/main.tf` diff noted in the context pack is unrelated to Python module structure.
