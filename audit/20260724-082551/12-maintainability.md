# Maintainability — Audit

**Score:** 81/100  **Maturity:** 4 (Managed)  **Coverage:** 100%  **Confidence:** high
**Applicable:** yes

## Charter & scope
How easily the codebase can be understood, changed, tested and evolved:
readability, testing, documentation, consistency, complexity, dependency health,
error handling and change friction.

Does **not** cover operational running/monitoring (→ Operational Excellence 01) or
decomposition/boundaries (→ Modularity 09). Verdicts here are grounded on the code
and tests actually read, plus a local run of both test suites.

**Method note:** static audit. Both suites were executed read-only and
deterministically:
- agent: `107 passed, 2 skipped in 0.17s`
- lambdas: `23 passed in 0.08s`

(130 passing — slightly higher than the inventory's "127"; the webhook test file
grew — `documentation/scripts/lambdas/tests/test_webhook_receiver.py`.)

## Strengths
- Core logic covered by fast, network-free tests with dependency injection — orchestrator nominal/fork/failure/idempotency-claim/release/duplicate/PR-resolution paths all exercised — _evidence: `documentation/scripts/agents/agent-technical-doc/tests/test_orchestrator.py:96` (`test_nominal_run_commits_and_comments`), `:170` (`test_failure_releases_idempotency`)_
- Highly readable, thoroughly docstring'd modules with clear domain naming and small functions — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/paths.py:1`, `documentation/scripts/agents/agent-technical-doc/docagent/retry.py:1`_
- Rich, current documentation set — `README.md` (12 KB), `ARCHITECTURE.md`, `AUDIT.md`, plus a 14.8 KB E2E guide and `.kiro/specs` (design/requirements/tasks) — _evidence: `documentation/README.md`, `documentation/ARCHITECTURE.md`, `documentation/scripts/agents/agent-technical-doc/e2e/README.md`_
- Explicit, consistent error handling: transient-vs-permanent classification, guaranteed terminal PR comment, secret masking; zero bare `except:` — _evidence: `documentation/scripts/lambdas/worker-dispatcher/handler.py:22` (`_TRANSIENT_ERRORS`), `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:224` (failure path posts terminal comment), `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:41` (`mask_secrets`)_
- Zero TODO/FIXME/HACK markers and zero commented-out code blocks across the Python sources (grep: 0 / 0) — _evidence: `grep -rn "TODO|FIXME|XXX|HACK" documentation/scripts --include=*.py` → 0_
- Pervasive type hints (`from __future__ import annotations` in 24/45 files, dataclasses, `Callable` signatures) — _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:38` (`OrchestratorDeps` dataclass), `documentation/scripts/agents/agent-technical-doc/docagent/payload.py:31` (`InvocationRequest`)_

## Weaknesses / Findings

### [Medium] MNT-F1 — No linter/formatter config and no CI gate to enforce tests/style on change
- **Evidence:** no `.github/workflows` (absent), no `pyproject.toml`/`ruff.toml`/`setup.cfg`/`.flake8`/`.pre-commit-config.yaml` found under `documentation/` (config-file search returned nothing); tests run only manually via `python3 -m pytest`.
- **Impact:** an excellent test suite exists but nothing prevents a regression, style drift, or a broken test from being merged. Quality currently depends on developer discipline. Change friction rises as the project grows or gains contributors.
- **Recommendation:** add a CI workflow (GitHub Actions) running `pytest` for both suites plus `ruff check`/`ruff format --check`; make it a required status check. Add a `ruff`/formatter config so style is machine-enforced.
- **Alternative solution:** pre-commit hooks (`pre-commit` with ruff + pytest-on-changed) as a lighter first step. Pros: instant local feedback, no CI infra; Cons: bypassable (`--no-verify`), not authoritative. Effort: S–M. Cross-pillar impact: Operational Excellence + (repeatable quality gate), Security + (enables `pip-audit` in the same pipeline).

### [Medium] MNT-F2 — Python dependencies pinned by floor only; no lockfile or vulnerability scan
- **Evidence:** `documentation/scripts/agents/agent-technical-doc/requirements.txt:1` uses `>=` for every dependency (`bedrock-agentcore>=0.1.0`, `strands-agents[otel]>=0.1.0`, `boto3>=1.34.0`, `pyjwt[crypto]>=2.8.0`, …); `requirements-dev.txt:11` `pytest>=8.0`. No `requirements*.lock`/hash-pinning and no `pip-audit` in evidence.
- **Impact:** builds are non-reproducible (a rebuild can silently pull newer, untested transitive versions), and there is no automated check for known-vulnerable dependencies. Debugging "works-on-my-image" drift becomes harder over time.
- **Recommendation:** produce a hash-pinned lock (`pip-compile`/`uv pip compile` → `requirements.lock`) used by the Dockerfile, and run `pip-audit` in CI.
- **Alternative solution:** exact-pin (`==`) directly in `requirements.txt`. Pros: trivial, no new tooling; Cons: no transitive-dependency locking, manual bumps. Effort: S. Cross-pillar impact: Security + (supply-chain), Reliability + (reproducible runtime image).

### [Low] MNT-F3 — Type hints not enforced by a static type checker
- **Evidence:** type hints are used throughout (e.g. `documentation/scripts/agents/agent-technical-doc/docagent/payload.py:31`, `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:38`) but no `mypy`/`pyright` config or invocation is present.
- **Impact:** the annotations document intent and aid readability but cannot catch type regressions; their value is only partly realized.
- **Recommendation:** add `mypy` (or `pyright`) to the CI gate from MNT-F1, starting in non-strict mode over `docagent/`.
- **Alternative solution:** None strictly required beyond MNT-F1 — folding a type check into the same pipeline is the natural home. Effort: S.

### [Info] MNT-N1 — Minor duplication across deployment boundaries
- **Evidence:** the transient-error name set is defined twice (`documentation/scripts/agents/agent-technical-doc/docagent/retry.py:17` `_TRANSIENT_NAMES` vs `documentation/scripts/lambdas/worker-dispatcher/handler.py:22` `_TRANSIENT_ERRORS`); the conditional-`PutItem` idempotency claim exists in both `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py:23` and `documentation/scripts/lambdas/webhook-receiver/handler.py:157`.
- **Impact:** low — the agent runtime and the Lambdas are separate deployable units that cannot share a common library without extra packaging, so the duplication is a reasonable trade-off. Noted so a future shared layer is considered if the lists diverge.
- **Recommendation:** no action required now; revisit if a shared internal package is introduced.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| MNT-01 | Automated tests with meaningful coverage of core logic | Met | `tests/test_orchestrator.py:96,170`; `lambdas/tests/test_webhook_receiver.py`; run: 107+2skip / 23 pass |
| MNT-02 | Readable code: naming, consistent style, function sizes | Met | `docagent/paths.py:1`; `docagent/retry.py:1`; `docagent/committer.py:1` |
| MNT-03 | Linter/formatter configured & enforced (CI gate) | Missing | no `.github/workflows`, no ruff/pyproject config found (MNT-F1) |
| MNT-04 | Documentation present & current | Met | `README.md`, `ARCHITECTURE.md`, `AUDIT.md`, `e2e/README.md`, `.kiro/specs` |
| MNT-05 | Low complexity (no deep nesting / huge functions) | Met | largest module `orchestrator.py` 270 lines; functions small & linear (`docagent/orchestrator.py:180` `_execute`) |
| MNT-06 | Dependencies pinned, maintained, not outdated/vulnerable | Partial | floor-only `>=` pins, no lock / pip-audit — `requirements.txt:1` (MNT-F2) |
| MNT-07 | Errors handled explicitly & consistently; no silent failures | Met | `worker-dispatcher/handler.py:22`; `orchestrator.py:224`; 0 bare `except:`; broad excepts all logged + `noqa: BLE001` |
| MNT-08 | Low duplication; changes localized | Met | well-factored modules; only cross-unit duplication (MNT-N1) |
| MNT-09 | Consistent project conventions | Met | uniform DI + deferred-import + docstring pattern; tests mirror modules — `docagent/__init__.py:1` |
| MNT-10 | No dead code / commented-out blocks / TODO rot | Met | grep TODO/FIXME/XXX/HACK = 0; commented-out code = 0 |
| MNT-11 | Tests fast/deterministic & runnable locally & in CI | Partial | 0.17s/0.08s, network-free, deterministic & local — but no CI exists to run them |
| MNT-12 | Type safety / static analysis leveraged | Partial | hints pervasive (`from __future__ import annotations` ×24) but no mypy/pyright (MNT-F3) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Add a CI pipeline (GitHub Actions) running both pytest suites + `ruff check`/format as a required gate | M |
| P2 | Hash-pin dependencies (`requirements.lock`) and run `pip-audit` in CI | M |
| P3 | Add a `ruff` config to enforce style/lint locally and in CI | S |
| P3 | Add `mypy`/`pyright` to the CI gate (non-strict over `docagent/` first) | S |

## Notes & assumptions
- Coverage of the grid: 12/12 criteria assessed → 100%. Confidence high (modules read
  directly; both suites executed read-only).
- Test **coverage percentage is not measured** (no `pytest-cov`/coverage gate).
  MNT-01 is scored `Met` on the basis of the *breadth of core-logic paths actually
  exercised* (orchestration, idempotency claim/release, retry, committer, path
  guard, webhook signature/origin/authz/rate-limit, worker error classification),
  not on a measured percentage — this caveat is intentional and surfaced here.
- The 2 intentional skips (RS256-without-crypto, E2E-without-stack) are legitimate
  environment guards, not coverage gaps.
- No Critical finding in this pillar → no contribution to global maturity capping.
- MNT-F1 overlaps with Operational Excellence (CI/CD absence) — scored here for the
  quality-gate dimension; cross-reference the OpEx pillar for the deploy-pipeline angle.
