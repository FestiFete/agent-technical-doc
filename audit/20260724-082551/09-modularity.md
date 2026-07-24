# Modularity — Audit

**Score:** 89/100  **Maturity:** 4 (Managed)  **Coverage:** 95%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Decomposition into cohesive, well-bounded, reusable units: cohesion, boundary
clarity, interface quality, encapsulation, DRY, dependency direction/cycles,
separation of concerns (domain vs infra vs I/O). Grounded on cohesion/coupling
theory, SOLID (SRP/ISP), package-by-feature, DRY.

Assessed: the `docagent/` package (18 modules), `agent.py` entrypoint, and the two
Lambda handlers (`webhook-receiver`, `worker-dispatcher`). Terraform module
decomposition is judged only at a design level here (7-module map) and cross-referenced
to **Terraform (08)** for mechanics. Runtime/temporal coupling → **Decoupling (10)**;
whole-system design → **Architecture (07)**.

## Strengths
- **Textbook separation of concerns (domain vs infra vs I/O).** Pure, network-free
  logic (`selection.py`, `drawio.py`, `doc_builder.py`, `paths.py`, `payload.py`,
  `comments.py`, `correlation.py`, `retry.py`) is cleanly split from I/O adapters
  (`github_client.py`, `secrets.py`, `idempotency.py`, `metrics.py`) — _evidence:
  `docagent/selection.py:1-12`, `docagent/analyzer.py:120-160` (pure `select_model` vs I/O `analyze`)_.
- **Dependency injection at the orchestration seam.** `OrchestratorDeps` groups all
  collaborators; real implementations are built lazily in `default_deps()`, so the
  whole run is testable without `boto3`/`strands`/network — _evidence:
  `docagent/orchestrator.py:44-104`_.
- **Deferred heavy imports keep modules importable/testable.** `boto3`, `strands`,
  `pyjwt` imported inside functions — _evidence: `docagent/__init__.py:1-8`,
  `docagent/analyzer.py:161-166`, `docagent/idempotency.py:35-37`_.
- **High per-module cohesion; no god-modules.** Largest file is `orchestrator.py`
  at 270 lines; all others ≤ 208. Each module maps to one pipeline responsibility —
  _evidence: `wc -l docagent/*.py` (max 270)_.
- **Consistent, discoverable conventions.** Uniform `from __future__ import annotations`,
  module + function docstrings, `_`-prefixed privates, custom exceptions per module,
  tests mirroring modules — _evidence: `docagent/repo_reader.py:1-18`, `docagent/paths.py:1-14`_.
- **Centralized security invariant as a single reusable unit.** `paths.normalize_output_path`
  is the one guardrail reused by both `doc_builder` and `committer` — _evidence:
  `docagent/paths.py:24-63`, `docagent/committer.py:16-40`_.
- **Sane dependency direction, no cycles.** `config`/`correlation`/`paths` are stable
  leaves; `orchestrator` is the top-level hub. `doc_builder` imports `drawio` locally
  to avoid load-time coupling — _evidence: `docagent/doc_builder.py:159`, `docagent/config.py` (no intra-package imports)_.

## Weaknesses / Findings

### [Medium] MOD-F1 — Duplicated GitHub HTTP plumbing across two modules
- **Evidence:** `docagent/github_client.py:29-30` (`_USER_AGENT`, `_API_VERSION`),
  `:55-73` (`_http`, `_headers`) vs `docagent/github_auth.py:37-38`, `:42-58`
  (`_default_http`), `:78-88` (`_auth_headers`). Both re-implement the same urllib
  transport, identical `HTTPError`/`URLError` handling, the same User-Agent/API-version
  constants, and near-identical header builders.
- **Impact:** Two copies of GitHub HTTP concerns drift independently (timeouts,
  error mapping, headers). A change to API version or transport behavior must be made
  twice; risk of inconsistent retry/error semantics between auth and data calls.
- **Recommendation:** Extract a tiny internal `_githttp` helper (transport + shared
  constants + header builder) and have both `github_client` and `github_auth` depend
  on it. Keeps `github_auth` free of the retry policy (which is GET-only in the client).
- **Alternative solution:** Fold auth into `GitHubClient` as a token provider strategy
  and share `_http`. _Pros:_ one GitHub module, one transport. _Cons:_ enlarges the
  client, mixes token acquisition with API calls (weaker SRP), harder to unit-test auth
  in isolation. _Effort:_ M. _Cross-pillar impact:_ maintainability +, testability −/+.
  Prefer the extracted-helper option (keeps ISP/SRP).

### [Low] MOD-F2 — Cross-deployment duplication (idempotency / transient errors / secret fetch)
- **Evidence:** conditional-`PutItem` idempotency claim duplicated in
  `docagent/idempotency.py:29-58` and `scripts/lambdas/webhook-receiver/handler.py:168-190`
  (differ only by `status` value); transient-error name lists in `docagent/retry.py:26-40`
  vs `scripts/lambdas/worker-dispatcher/handler.py:26-30`; Secrets Manager fetch+cache in
  `docagent/secrets.py:38-62` vs `webhook-receiver/handler.py:157-165`.
- **Impact:** Logic that should evolve together (e.g. what counts as a transient error,
  TTL semantics) lives in three packaging units and can drift. Low severity because these
  are genuinely separate deployment artifacts (agent image vs two Lambdas) with no shared
  library layer today, so some duplication is a deliberate packaging trade-off.
- **Recommendation:** Introduce a small shared internal package (e.g. `common/` layer or
  Lambda layer) for the idempotency claim, transient-error classification, and secret
  cache; or explicitly document the duplication as accepted. _Effort:_ M.
- **Alternative solution:** None required — acceptable for a POC given the deployment-unit
  boundary; revisit if a fourth consumer appears.

### [Info] MOD-F3 — Hidden global coupling via import-time env constants and a module cache
- **Evidence:** `docagent/config.py:71-96` reads `os.environ` into module-level constants
  at import (`MODEL_ID`, `GITHUB_API_BASE`, `BEDROCK_REGION`, thresholds); `docagent/secrets.py:19`
  module-level `_DICT_CACHE` mutable global (with `_reset_cache_for_tests`).
- **Impact:** Modules that read these constants are coupled to import ordering (env must be
  set before first import); the secret cache is process-global shared state. Mitigated by
  DI, `read_caps()` factories, and the test-reset hook, so real reuse risk is low.
- **Recommendation:** Prefer accessor functions over module-level env constants (mirror the
  `read_caps()` pattern already used for `ReadCaps`) so configuration is resolved at call
  time, not import time. _Effort:_ S.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| MOD-01 | High cohesion: one responsibility per module. | Met | `docagent/selection.py:1-12`, `docagent/paths.py:1-14`, `docagent/metrics.py:1-11` — each module single-purpose; only mild bundling in `correlation.py` (id + masking + key) |
| MOD-02 | Clear, documented public interfaces; internals encapsulated. | Met | module+function docstrings & type hints throughout; `_`-prefixed privates e.g. `docagent/analyzer.py:100-118` (`_extract_json`), dataclass contracts `docagent/payload.py:29-64` |
| MOD-03 | Boundaries by domain/feature, not dumping grounds. | Met | pipeline-step modules (auth/client/reader/selection/analyzer/builder/committer/comments); no `utils.py` catch-all; TF 7-module map cohesive (cross-ref 08) |
| MOD-04 | Low duplication (DRY). | Partial | MOD-F1 GitHub HTTP dup `github_client.py:55-73` vs `github_auth.py:42-58`; MOD-F2 cross-unit dup `idempotency.py:29-58` vs `webhook-receiver/handler.py:168-190` |
| MOD-05 | No god modules; sizes reasonable. | Met | max 270 lines (`orchestrator.py`), all others ≤ 208; `wc -l docagent/*.py` |
| MOD-06 | Sane dependency direction; no cycles. | Met | stable leaves `config`/`paths`/`correlation`; `doc_builder.py:159` local import avoids load cycle; orchestrator is top hub |
| MOD-07 | Genuinely reusable units (no hidden global coupling). | Partial | MOD-F3 import-time env constants `config.py:71-96`, module cache `secrets.py:19`; largely mitigated by DI + factories |
| MOD-08 | Consistent, discoverable organization. | Met | uniform conventions `repo_reader.py:1-18`; tests mirror modules; flat 18-module package still navigable |
| MOD-09 | Clear separation domain vs infra vs I/O. | Met | pure `select_model` vs I/O `analyze` `analyzer.py:120-166`; DI seam `orchestrator.py:44-104`; pure `payload.py`/`comments.py`/`drawio.py` |
| MOD-10 | Minimal public surface (no leaking internals). | Met | `__all__` `docagent/__init__.py:11-19`; consistent `_` privates; only intended functions/exceptions public (note: `__all__` lists a subset of modules — harmless) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P2 | Extract a shared `_githttp` helper (transport + constants + header builder) used by `github_client` and `github_auth` (MOD-F1). | M |
| P3 | Introduce a shared internal/Lambda-layer package for idempotency claim, transient-error classification, and secret cache, or document the cross-unit duplication as accepted (MOD-F2). | M |
| P3 | Replace import-time env constants in `config.py` with accessor functions (mirror `read_caps()`) to remove import-order coupling (MOD-F3). | S |

## Notes & assumptions
- Static audit; no runtime introspection. All 18 `docagent` modules, `agent.py`, and both
  Lambda handlers were read in full. Module sizes confirmed via `wc -l`.
- Terraform module **decomposition** (7 modules) was assessed only from the verified module
  map in the shared context pack (single-responsibility modules, layered `remote_state`
  dependency direction), not by reading each `.tf`; TF module **mechanics** are owned by
  Terraform (08). This is the ~5% coverage gap.
- No dependency-graph/lint tooling (e.g. `ruff`, import-linter) is installed; cycle/direction
  analysis is by inspection of intra-package imports. No cycles were found.
- Cross-unit duplication (MOD-F2) is scored `Low`/`Partial` because the agent image and the
  two Lambdas are distinct deployment artifacts without a shared library today — a deliberate,
  if improvable, packaging trade-off rather than accidental copy-paste within one unit.
