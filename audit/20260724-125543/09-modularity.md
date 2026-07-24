# Modularité — Audit

**Score :** 89/100  **Maturité :** 4 (Managed)  **Couverture :** 95%  **Confiance :** high
**Applicable :** oui

## Charte & périmètre

Ce pilier évalue la **structure interne du code** : cohésion (une responsabilité
claire par module), couplage (direction des dépendances, absence de cycles),
interfaces publiques et encapsulation, découpage par domaine/feature (SOLID —
SRP/ISP), DRY, absence de god-objects, séparation domaine / infrastructure / I/O,
et minimalité de la surface publique.

Il **ne couvre pas** : la structure des modules Terraform (pilier Terraform), le
découplage inter-composants runtime — files/événements/frontières de service
(pilier Découplage), ni la maintenabilité au sens tests/lisibilité globale
(pilier Maintainability). Le périmètre analysé est le code Python :
`documentation/scripts/agents/agent-technical-doc/` (agent + package `docagent/`,
18 modules) et `documentation/scripts/lambdas/` (2 handlers).

## Points forts

- **Découpage par responsabilité fine et lisible** — `docagent/` est éclaté en
  ~18 modules à responsabilité unique (auth, secrets, client HTTP, lecture repo,
  sélection, analyse, drawio, assemblage doc, commit, commentaires, idempotence,
  métriques, chemins, payload, retry, corrélation, config) plutôt qu'un fichier
  monolithique. — _evidence : arborescence `docagent/` ; `docagent/orchestrator.py:22-27` (imports ciblés)_
- **Injection de dépendances systématique** — l'orchestrateur reçoit ses
  collaborateurs via `OrchestratorDeps` (dataclass), avec des défauts réels
  construits paresseusement. — _evidence : `docagent/orchestrator.py:38-97`_
- **Imports lourds différés (boto3/strands/pyjwt) dans les fonctions** — la
  logique pure reste importable et testable sans les dépendances. — _evidence :
  `docagent/__init__.py:1-19` ; `docagent/analyzer.py:170-176` ; `docagent/secrets.py:22-24` ; `docagent/github_auth.py:64` (jwt différé)_
- **Séparation nette domaine / infra / I/O** — domaine (`selection.py`,
  `doc_builder.py`, `drawio.py`, `paths.py`, `payload.py`) ; infra
  (`secrets.py`, `idempotency.py`, `github_client.py`, `metrics.py`) ; I/O
  (`repo_reader.py`, `committer.py`) ; câblage via `orchestrator.py`. Le LLM est
  cantonné à un rôle d'analyseur pur, le rendu/commit étant déterministe. —
  _evidence : `docagent/analyzer.py:1-12` ; `docagent/orchestrator.py:118-224`_
- **Direction des dépendances saine, sans cycle** — le flux va de
  `orchestrator` → modules feuilles ; `retry.py` évite volontairement tout import
  pour ne pas créer de cycle (détection d'erreurs transitoires par duck-typing). —
  _evidence : `docagent/retry.py:38-60` (commentaire « évite les cycles ») ;
  `docagent/github_client.py:20` (seul import interne : `retry`)_
- **Encapsulation propre** — helpers internes préfixés `_`, exceptions dédiées
  (`GitHubError`, `GitHubAuthError`, `PayloadError`, `PathNotAllowedError`,
  `CommitTargetError`, `PermanentError`), dataclasses figées côté domaine. —
  _evidence : `docagent/payload.py:29-70` (`InvocationRequest` frozen) ;
  `docagent/github_client.py:31-38`_
- **Aucun god-object** — le plus gros fichier fait 293 lignes
  (`webhook-receiver/handler.py`), l'orchestrateur 270, tous les autres < 210. —
  _evidence : `wc -l` sur `docagent/*.py` + handlers (max 293)_
- **Contrats publics documentés** — chaque module porte un docstring décrivant
  rôle, invariants et garanties (ex. cible de commit figée sous `docs/agent/`). —
  _evidence : `docagent/paths.py:1-9` ; `docagent/committer.py:1-11`_
- **Fonctions pures testables séparées des effets** — `verify_signature`,
  `verify_origin`, `evaluate_comment`, `parse_api_event` dans le handler webhook
  sont pures et isolées de l'accès AWS (boto3 différé). — _evidence :
  `webhook-receiver/handler.py:64-160`_

## Faiblesses / Findings

### [Medium] MOD-F1 — Duplication de logique d'infra entre les Lambdas et `docagent`

- **Evidence :**
  - Idempotence par PutItem conditionnel dupliquée :
    `webhook-receiver/handler.py:145-161` (`_claim_idempotency`, statut `queued`)
    vs `docagent/idempotency.py:24-58` (`claim`, statut `in_progress`) — même
    schéma d'item (`pk`/`status`/`correlation_id`/`created_at`/`ttl`) et même
    `ConditionExpression="attribute_not_exists(pk)"`.
  - Récupération de secret Secrets Manager avec cache dupliquée :
    `webhook-receiver/handler.py:139-147` (`_get_secret`) vs
    `docagent/secrets.py:41-63` (`get_secret_dict`).
  - Liste des erreurs transitoires dupliquée :
    `worker-dispatcher/handler.py:26-29` (`_TRANSIENT_ERRORS`) vs
    `docagent/retry.py:26-40` (`_TRANSIENT_NAMES`) — recouvrement quasi total des
    codes (`ThrottlingException`, `TooManyRequestsException`, `InternalServerException`…).
- **Impact :** risque de dérive fonctionnelle silencieuse (une correction — p.ex.
  ajout d'un code transitoire ou changement de schéma DynamoDB — appliquée d'un
  côté et pas de l'autre). Coût de maintenance réparti sur plusieurs endroits.
  Impact **modéré** car les définitions sont courtes et actuellement cohérentes.
- **Recommendation :** extraire un petit module partagé (`shared/aws_idempotency.py`,
  `shared/secrets.py`, `shared/transient.py`) empaqueté dans le zip des deux
  Lambdas (layer commun ou copie packagée par le build) et importable par
  `docagent`, avec une source unique de vérité pour le set d'erreurs transitoires
  et le schéma d'item d'idempotence.
- **Alternative solution :** *Assumer la duplication comme frontière de
  déploiement.* Les Lambdas (zip) et l'agent (image conteneur ARM64) sont des
  artefacts indépendants sans package partagé installé ; une micro-lib commune
  introduit un couplage de build et une dépendance de versionnage.
  - *Pros :* zéro couplage inter-artefacts, chaque unité déployable seule,
    surface d'import minimale.
  - *Cons :* la duplication persiste ; nécessite une discipline (test de
    contrat/parité) pour éviter la dérive.
  - *Effort :* S (documenter la duplication + test de parité) vs M (extraction lib).
  - *Cross-pillar impact :* Maintainability + (source unique), Terraform +/−
    (packaging layer/build), Decoupling neutre.

### [Low] MOD-F2 — Couplage global via constantes de config lues à l'import + caches module-level

- **Evidence :** `docagent/config.py:63-99` expose des constantes
  (`DOC_OUTPUT_DIR`, `MODEL_ID`, `GITHUB_TOKEN_SECRET_ARN`, `BEDROCK_REGION`…)
  lues **une seule fois à l'import** et référencées directement par plusieurs
  modules (`docagent/paths.py:16`, `docagent/committer.py:15`,
  `docagent/analyzer.py`). Caches globaux mutables au niveau module :
  `docagent/secrets.py:17` (`_DICT_CACHE`), `webhook-receiver/handler.py:36`
  (`_SECRET_CACHE`).
- **Impact :** couplage caché léger — modifier une variable d'environnement après
  import n'a pas d'effet sur les constantes (contrairement à `ReadCaps` qui
  re-lit via `field(default_factory=...)`), et les caches globaux imposent un
  reset explicite en test. Réutilisabilité d'un module isolé légèrement contrainte.
  Atténué par la présence d'un hook `_reset_cache_for_tests` (`docagent/secrets.py:66`).
- **Recommendation :** privilégier l'accès via `config.X` (référence tardive) ou
  passer la config en paramètre plutôt que d'importer des constantes figées ;
  encapsuler les caches derrière une petite abstraction injectable.
- **Alternative solution :** None — pour un POC mono-runtime, le pattern
  « constantes de config + `default_factory` là où le re-read compte » est un
  compromis raisonnable ; la remédiation est optionnelle et de faible valeur.

## Grille de critères

| id | critère | verdict | evidence |
|----|---------|---------|----------|
| MOD-01 | Forte cohésion : une responsabilité claire par module. | Met | `docagent/paths.py:1-9`, `docagent/idempotency.py:1-12`, `docagent/metrics.py:1-8`, `docagent/committer.py:1-11` |
| MOD-02 | Interfaces publiques documentées ; internes encapsulés. | Met | `docagent/payload.py:29-70`, `docagent/github_client.py:31-38`, docstrings de module partout |
| MOD-03 | Frontières par domaine/feature, pas de fourre-tout. | Met | arborescence `docagent/` (package-by-feature) ; pas de `utils.py` fourre-tout |
| MOD-04 | Faible duplication ; logique partagée factorisée (DRY). | Partial | MOD-F1 : `webhook-receiver/handler.py:145-161` vs `docagent/idempotency.py:24-58` ; `worker-dispatcher/handler.py:26-29` vs `docagent/retry.py:26-40` |
| MOD-05 | Pas de god-module ; tailles raisonnables. | Met | max 293 l. (`webhook-receiver/handler.py`), orchestrateur 270 l. |
| MOD-06 | Direction des dépendances saine ; pas de cycle. | Met | `docagent/retry.py:38-60` (évite import → pas de cycle) ; `docagent/orchestrator.py:22-27` |
| MOD-07 | Unités réutilisables sans couplage global caché. | Partial | MOD-F2 : constantes import-time `docagent/config.py:63-99` ; caches `docagent/secrets.py:17`, `webhook-receiver/handler.py:36` |
| MOD-08 | Organisation cohérente et découvrable. | Met | nommage/structure homogènes ; helpers `_`-préfixés cohérents |
| MOD-09 | Séparation nette domaine / infra / I/O. | Met | `docagent/analyzer.py:1-12` (LLM = analyseur pur) ; `docagent/orchestrator.py:118-224` (câblage) |
| MOD-10 | Surface publique minimale. | Met | `docagent/__init__.py:11-19` (`__all__` restreint) ; méthodes publiques ciblées `docagent/github_client.py` |

Calcul : Σ(crédit×poids) = 10,25 ; Σ(poids) = 11,5 → **89/100** → maturité **4**.

## Améliorations priorisées

| priorité | action | effort |
|----------|--------|--------|
| P2 | Factoriser la source unique du set d'erreurs transitoires et du schéma d'idempotence (lib partagée ou test de parité) — MOD-F1 | S–M |
| P3 | Référencer la config via `config.X` (lecture tardive) et encapsuler les caches derrière une abstraction injectable — MOD-F2 | S |
| P3 | Compléter/aligner `docagent/__init__.__all__` avec les modules d'entrée réellement exposés (`orchestrator`, `payload`) ou documenter le sous-ensemble volontaire | S |

## Notes & hypothèses

- Audit **statique** : cohésion, couplage, tailles et duplication mesurés sur le
  code lu ; les 12 modules `docagent` principaux, l'entrypoint `agent.py` et les 2
  handlers Lambda ont été lus intégralement (couverture ~95% ; non relus en détail :
  `doc_builder.py`, `drawio.py`, `repo_reader.py`, `selection.py`, `comments.py`,
  dont les tailles et docstrings ont néanmoins été vérifiés).
- **Aucun god-object ni cycle de dépendances** détecté — d'où l'absence de finding
  High/Critical sur ce pilier (les cycles/god-objects seraient typiquement High).
- La duplication Lambdas ↔ `docagent` relève en partie d'une **frontière de
  déploiement légitime** (zip vs image conteneur, sans package partagé) : elle est
  cotée Medium et non High.
- La contrainte org (Deny CloudTrail/KMS/GuardDuty) est sans effet sur la
  modularité du code : non pénalisée.
