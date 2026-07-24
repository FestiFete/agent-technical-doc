# Maintainability — Audit

**Score:** 76/100  **Maturity:** 4 (Managed)  **Coverage:** 95%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Ce pilier évalue la **facilité à faire évoluer et corriger le code dans la durée** :
tests automatisés et leur pertinence, lisibilité, complexité, conventions, gestion
d'erreurs, duplication, code mort, épinglage des dépendances, sûreté de typage et
outillage qualité (linter/formatter/CI, exécution des tests).

Hors périmètre (traités ailleurs) : découpage/cohésion des modules (Modularité, pilier 9),
couplage inter-composants (Découplage, pilier 10), structure et bonnes pratiques Terraform
(pilier 8), fiabilité runtime (pilier 3 — dont le drop d'erreur permanente du worker,
REL-F2, ici seulement cross-référencé).

Audit **statique** : le code Python est intégralement lisible ; les suites de tests ont été
exécutées en lecture seule pour corroboration (`python3 -m pytest -q`).

## Strengths
- **Suite de tests fournie, rapide et déterministe** — 107 passés + 2 skips (agent) et
  23 passés (lambdas) = **130 tests en ~0,23 s**, sans réseau (injection de dépendances,
  imports `boto3`/`strands`/`pyjwt` différés). _evidence : exécution `pytest -q` →
  `107 passed, 2 skipped in 0.16s` ; `23 passed in 0.07s` ; `tests/conftest.py:1`_
- **Couverture logique cœur par module** — un fichier de test par module métier
  (orchestrator, github_auth, github_client, repo_reader, selection, doc_builder, drawio,
  committer, metrics, payload, retry…). _evidence : `agents/agent-technical-doc/tests/` (18 fichiers), `lambdas/tests/` (2 fichiers)_
- **Gestion d'erreurs explicite et documentée** — aucun `except:` nu ; toutes les captures
  larges sont intentionnelles, annotées `# noqa: BLE001` avec un commentaire de justification
  (observabilité best-effort, garantie d'un commentaire terminal), et journalisées avec
  `exc_info`. _evidence : `docagent/orchestrator.py:148,190,201,249` ; `agent.py:83,89,104` ; `docagent/retry.py:72`_
- **Documentation riche et à jour** — README (226 l.), ARCHITECTURE.md (159 l., 2 diagrammes
  mermaid), AUDIT.md (152 l.), plus `.kiro/specs/agent-technical-doc/{design,requirements,tasks}.md`.
  _evidence : `documentation/README.md`, `documentation/ARCHITECTURE.md:1` (2× ```mermaid), `.kiro/specs/agent-technical-doc/design.md`_
- **Pas de dette de code mort** — aucun `TODO`/`FIXME`/`XXX`/`HACK`, pas de blocs commentés.
  _evidence : `grep -rn "TODO\|FIXME\|XXX\|HACK" docagent lambdas` → aucun résultat_
- **Typage moderne et cohérent** — `from __future__ import annotations` présent dans les 20
  modules, ~73 annotations de retour, dataclasses (`InvocationRequest`). _evidence : `docagent/orchestrator.py:1` ; 20 fichiers avec `from __future__ import annotations`_
- **Faible duplication, responsabilités localisées** — 19 modules focalisés (≤ 270 l.), un rôle
  par module. _evidence : `wc -l docagent/*.py` (max `orchestrator.py` 270 l.)_

## Weaknesses / Findings

### [High] MNT-F1 — Aucun linter/formatter configuré ni gate qualité CI
- **Evidence :** absence de `.github/workflows`, `pyproject.toml`, `ruff.toml`, `.flake8`,
  `mypy.ini`, `setup.cfg`, `tox.ini` (recherche récursive → aucun résultat) ; inventaire
  « Aucun pipeline CI/CD ».
- **Impact :** style/qualité non appliqués automatiquement ; les 130 tests, le typage et le
  formatage reposent sur la discipline manuelle. Aucune barrière ne bloque une PR qui
  casserait les tests ou introduirait une régression de style/typage → dérive de qualité
  probable à mesure que l'équipe grandit. Touche aussi MNT-11 (« & CI ») et MNT-12 (typage
  non vérifié).
- **Recommendation :** ajouter `ruff` (lint+format) + `mypy` + `pytest` dans un workflow
  GitHub Actions, en gate sur PR ; mesurer la couverture (`pytest-cov`) avec un seuil.
- **Alternative solution :** *GitHub Actions avec `ruff check` + `ruff format --check` +
  `mypy` + `pytest --cov`.*
  - **Pros :** gate automatique sur chaque PR ; qualité/typage/tests garantis ; couverture
    mesurée et suivie ; coût nul (runners publics).
  - **Cons :** effort initial de configuration ; premier passage `ruff`/`mypy` révélera des
    corrections à faire ; maintenance du workflow.
  - **Effort :** S–M.
  - **Cross-pillar impact :** operational-excellence + (répétabilité), security + (scan deps
    possible via `pip-audit`/`trivy` dans le même pipeline), reliability + (tests bloquants).
  - _Note : `ruff`/linters ABSENTS de l'environnement d'audit — non installés (consigne) ;
    verdict fondé sur l'absence de fichiers de config dans le dépôt._

### [Medium] MNT-F2 — Dépendances Python non épinglées à l'exact (bornes `>=`), image de base flottante
- **Evidence :** `requirements.txt:1-11` utilise des bornes basses (`bedrock-agentcore>=0.1.0`,
  `strands-agents[otel]>=0.1.0`, `boto3>=1.34.0`, `pyjwt[crypto]>=2.8.0`, `aws-opentelemetry-distro>=0.10.0`) ;
  `requirements-dev.txt:8` `pytest>=8.0` ; aucun lockfile ni hachage ; `Dockerfile:1`
  `FROM ...python:3.11-slim` (tag flottant, pas de digest).
- **Impact :** builds non reproductibles ; une montée de version amont peut changer le
  comportement à l'insu de l'équipe (le contraire d'un déploiement déterministe). Les
  providers Terraform, eux, sont bien verrouillés (`.terraform.lock.hcl` dans les 7 modules)
  — l'écart concerne le stack Python/Docker.
- **Recommendation :** figer les versions exactes (pip-tools/`requirements.lock` avec hachages)
  et épingler l'image de base par digest (`python:3.12-slim@sha256:…`).
- **Alternative solution :** *pip-tools (`requirements.in` → `requirements.txt` compilé,
  `--generate-hashes`).*
  - **Pros :** reproductibilité totale, mises à jour explicites et revues, protection anti-supply-chain (hashes).
  - **Cons :** étape de compilation à maintenir ; PR de bump régulières (Dependabot recommandé).
  - **Effort :** S. **Cross-pillar impact :** security + , reliability + .

### [Low] MNT-F3 — Fonction d'orchestration longue (`_execute`, ~118 lignes)
- **Evidence :** `docagent/orchestrator.py:153` `def _execute(` — ~118 lignes, plusieurs
  niveaux de `try/except` best-effort imbriqués.
- **Impact :** point unique à forte densité logique ; lisibilité correcte grâce aux
  commentaires d'étape et à la délégation (`_resolve_pr_details`, `_build_repo_context`,
  `assemble_document_set`, `commit_documents`), mais dépasse la taille raisonnable.
- **Recommendation :** extraire les phases (garde-fou fork, accusé de réception, idempotence,
  clone+analyse+commit, gestion d'échec terminal) en sous-fonctions nommées.
- **Alternative solution :** None — refactor local à faible risque ; le découpage actuel en
  helpers rend l'extraction directe. **Effort :** S.

### [Low] MNT-F4 — Dérive de version runtime Python (Docker 3.11 vs Lambdas 3.12)
- **Evidence :** `Dockerfile:1` `python:3.11-slim` ; `terraform/ingestion/main.tf:191,221`
  `runtime = "python3.12"` ; inventaire annonce « Python 3.12 » partout.
- **Impact :** incohérence de convention entre le runtime agent (conteneur) et les Lambdas ;
  risque de comportements subtils divergents entre environnements.
- **Recommendation :** aligner l'image de base sur `python:3.12-slim`.
- **Alternative solution :** None — changement d'une ligne. **Effort :** S.

### [Info] MNT-07 — Drop d'erreur permanente du worker (cross-ref REL-F2)
- **Evidence :** `lambdas/worker-dispatcher/handler.py:92-95` — `PermanentError` capturée par
  record, journalisée (`logger.error`) puis consommée sans re-raise ni métrique/DLQ.
- **Note :** l'échec est **journalisé** (donc pas « silencieux » au sens lecture de code),
  mais l'absence de signal durable (métrique/DLQ) est un défaut de **fiabilité** — scoré et
  remédié sous **REL-F2** (pilier 3), simplement cross-référencé ici pour éviter le double
  comptage.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| MNT-01 | Tests automatisés couvrant la logique cœur (poids 2.0) | Met | `pytest -q` → 130 tests verts ; `tests/` (18) + `lambdas/tests/` (2) |
| MNT-02 | Code lisible : nommage, style, tailles de fonctions (poids 1.5) | Met | `docagent/*.py` (docstrings, nommage clair) ; unique bémol `orchestrator.py:153` |
| MNT-03 | Linter/formatter configuré & appliqué (gate CI) (poids 1.0) | Missing | aucun `pyproject.toml`/`ruff.toml`/`.flake8`/`.github/workflows` (MNT-F1) |
| MNT-04 | Docs présentes & à jour (poids 1.0) | Met | `README.md`, `ARCHITECTURE.md:1` (mermaid), `AUDIT.md`, `.kiro/specs/…` |
| MNT-05 | Faible complexité, pas de fonctions énormes/profondes (poids 1.5) | Partial | `orchestrator.py:153` `_execute` ~118 l. (MNT-F3) ; reste ≤ ~24 l. |
| MNT-06 | Dépendances épinglées, maintenues, non vulnérables (poids 1.0) | Partial | `requirements.txt:1-11` bornes `>=` ; `Dockerfile:1` tag flottant (MNT-F2) ; TF lock OK |
| MNT-07 | Erreurs gérées explicitement ; pas d'échec silencieux (poids 1.0) | Met | `orchestrator.py:148,249` ; `retry.py:72` ; drop worker journalisé (cross-ref REL-F2) |
| MNT-08 | Faible duplication ; changements localisés (poids 1.0) | Met | 19 modules focalisés ; `wc -l docagent/*.py` |
| MNT-09 | Conventions de projet cohérentes (poids 1.0) | Met | `from __future__ import annotations` ×20 ; style homogène ; bémol version (MNT-F4) |
| MNT-10 | Pas de code mort / blocs commentés / TODO rot (poids 0.5) | Met | `grep TODO/FIXME/XXX/HACK` → aucun |
| MNT-11 | Tests rapides/déterministes, exécutables en local & CI (poids 1.0) | Partial | rapides (~0,23 s) et locaux OK, mais **aucune CI** ne les exécute (MNT-F1) |
| MNT-12 | Sûreté de typage / analyse statique exploitée (poids 1.0) | Partial | annotations larges (~73 retours) mais **pas de mypy/pyright** ni en config ni en CI |

Calcul : Σ(credit×poids)=10,25 ; Σ(poids)=13,5 → **100 × 10,25 / 13,5 = 76**.

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Pipeline GitHub Actions : `ruff check` + `ruff format --check` + `mypy` + `pytest --cov` en gate PR (MNT-F1) | S–M |
| P1 | Épingler les deps Python à l'exact (+hachages) et l'image de base par digest (MNT-F2) | S |
| P2 | Mesurer la couverture (`pytest-cov`) avec seuil et suivi | S |
| P3 | Extraire les phases de `_execute` en sous-fonctions (MNT-F3) | S |
| P3 | Aligner l'image Docker sur `python:3.12-slim` (MNT-F4) | S |

## Notes & assumptions
- Audit statique ; les 130 tests ont été **réellement exécutés** en lecture seule pour
  corroboration (aucune modification de cible/AWS).
- Outils `ruff`/linters/`mypy` **absents** de l'environnement (non installés, consigne) :
  MNT-03/MNT-12 jugés sur la **présence de configuration dans le dépôt**, pas sur une
  exécution.
- Contrainte org (CloudTrail/KMS/GuardDuty deny) sans effet sur ce pilier (aucune
  pénalisation liée à leur désactivation).
- Couverture 95 % (12/12 critères évalués) ; confiance haute (code intégralement lisible,
  tests exécutés). La seule inconnue est la couverture de test chiffrée (non mesurée dans le
  dépôt) — MNT-01 reste Met sur la base d'un fichier de test par module cœur.
- Dé-duplication : le drop d'erreur permanente du worker est scoré sous REL-F2 (fiabilité),
  seulement cross-référencé ici.
