# Tasks — agent-technical-doc

Plan d'implémentation en incréments testables (TDD, agile). Chaque tâche produit
un incrément démontrable et s'appuie sur la précédente. Statut mis à jour au fil
de l'exécution.

- [x] **Task 1 — Squelette agent + spike invocation AgentCore**
  - `agent.py` (entrypoint `BedrockAgentCoreApp` renvoyant un statut structuré),
    `instructions.md` (stub), `Dockerfile` ARM64, `requirements.txt` ; entrée
    `agents.json` (`enabled:false`). Note de décision sur le mode d'invocation.
  - Test : `invoke()` renvoie `status`, `sessionId`, `correlation_id`.
  - Demo : agent invocable en local renvoyant un statut structuré.

- [x] **Task 2 — Tools d'accès dépôt (clone + lecture bornée) + Secrets Manager**
  - `clone_repository` (shallow, ref précise), `list_repository_tree`,
    `read_repository_file` avec plafonds (octets/nombre), skip binaires + dossiers
    vendored. Token via Secrets Manager (client mockable). Contenu non fiable, token
    jamais loggé.
  - Tests : plafonds/exclusions respectés ; token via mock ; aucun secret dans les
    logs.
  - Demo : clone + lecture d'un ensemble borné de fichiers.

- [x] **Task 3 — Sélection heuristique + analyse + anti prompt-injection**
  - `instructions.md` complet (heuristique, analyse structurée). Contenu lu =
    donnée, jamais instruction. _NB : le **résumé hiérarchique** initialement prévu
    n'est pas implémenté ; à ce jour sélection par score + troncature + plafonds._
  - Tests : stack/framework identifiés depuis le manifeste ; **cas
    prompt-injection** neutralisé (un fichier hostile ne modifie ni la cible ni le
    comportement).
  - Demo : analyse structurée correcte, insensible au fichier piégé.

- [x] **Task 4 — Génération documentation Markdown**
  - Jeu de `.md` sous `docs/agent/**` (overview, stack, architecture, functional),
    sections normalisées, contenu issu de l'analyse.
  - Tests : sections présentes, chemins déterministes.
  - Demo : contenu Markdown complet pour un dépôt exemple.

- [x] **Task 5 — Génération schémas draw.io (C4 + Séquence + ER)**
  - `write_drawio_diagram` produisant du XML mxGraph valide (un fichier/diagramme) ;
    ER si modèle détecté ; validation de bonne-formation XML.
  - Tests : XML parse et contient les nœuds attendus ; ER omis si non détecté.
  - Demo : `.drawio` ouvrables dans diagrams.net.

- [x] **Task 6 — Restitution GitHub : commit unique contraint + commentaire terminal**
  - `commit_documentation` via Git Data API (tree→commit→update ref), un seul
    commit, cible contrainte (`docs/agent/**`, branche head, repo/sha injectés) ;
    `post_pr_comment` ; commentaire terminal succès/échec ; idempotence.
  - Tests : commit unique tous fichiers + un commentaire ; **rejet chemin hors
    `docs/agent/**`** ; **rejet cible fork/branche autre** ; re-run même sha sans
    duplication.
  - Demo : bout-en-bout contre un dépôt de test ; tentative hors périmètre refusée.

- [x] **Task 7 — Orchestration entrypoint**
  - Enchaînement clone→sélection→analyse→génération→commit→commentaire ; refus
    fork ; gestion d'erreur → commentaire terminal ; `correlation_id` propagé.
  - Tests d'intégration `invoke()` (mocks) : nominal, fork refusé, échec → commentaire.
  - Demo : un payload documente entièrement une PR de test.

- [x] **Task 8 — Terraform : rôle IAM strict + KMS + build/push + runtime**
  - Rôle runtime scopé (`bedrock`, `secretsmanager` scopé, `dynamodb` scopé, logs) ;
    KMS CMK ; agents.json `enabled` ; injection env. `terraform validate`.
    _NB : les **CMK KMS** ont été retirées en POC (DENY `kms:CreateKey`) → clés
    gérées AWS ; à rétablir avant prod._
  - Demo : runtime déployé ; `InvokeAgentRuntime` manuel documente un dépôt de test.

- [x] **Task 9 — Terraform : ingestion webhook→API GW→SQS→worker**
  - Module `ingestion` : API GW HTTPS, Lambda webhook (HMAC, allowlist,
    author_association, anti-fork, dedup, ack, enqueue), SQS+DLQ chiffrés, Lambda
    worker (`InvokeAgentRuntime` scopé ARN), DynamoDB idempotence (TTL), rôles
    séparés.
  - Tests unitaires Lambda : HMAC valide/invalide, mention, allowlist,
    author_association, fork rejeté, dedup, enqueue.
  - Demo : commenter `@agent` sur une PR déclenche la chaîne et produit la doc.

- [x] **Task 10 — Robustesse concurrence & résilience**
  - Visibility timeout ≥ durée max run ; DLQ + redrive ; concurrence worker limitée ;
    classification transitoire/permanente + backoff ; un commit/(repo,pr,sha).
  - Tests : doublons/parallèles → un seul run ; erreur permanente → DLQ ;
    transitoire → retry.
  - Demo : plusieurs `@mention` simultanés, aucun conflit ni doublon.

- [x] **Task 11 — Observabilité : corrélation, métriques, alarmes, dashboard**
  - `correlation_id` propagé (delivery→SQS→session) dans les logs des 3 composants ;
    métriques EMF (runs, succès, échecs, durée, tokens) ; alarmes (DLQ, taux
    d'erreur, latence) ; dashboard ; rétention logs bornée.
  - Demo : suivre un run par son `correlation_id` ; dashboard + alarme fonctionnels.

- [x] **Task 12 — Documentation, runbook, guide de déploiement**
  - README agent (fonctionnement, ordre de déploiement, config, variables d'env),
    notes de sécurité, runbook exploitation, évolution GitHub App.
  - Demo : un nouvel ingénieur déploie l'ensemble en suivant le guide.

## Compléments post-POC (livrés)

Améliorations réalisées au-delà du plan initial (voir aussi la section « État
d'implémentation » de `requirements.md`).

- [x] **Sélection de modèle à deux niveaux** — Haiku par défaut, escalade Sonnet
  pour les dépôts volumineux/complexes (`analyzer.select_model`). Tests unitaires.
- [x] **Bornage du contexte resserré** — plafonds abaissés (≈1,2 Mo, 40 fichiers,
  80 Ko/fichier) sous la fenêtre de contexte (coût + fiabilité).
- [x] **Invocation asynchrone** — entrypoint non bloquant
  (`add_async_task`/`complete_async_task`), worker « fire-and-forget » (timeout court).
- [x] **Résilience du run** — idempotence relâchée en cas d'échec ; retries backoff
  sur erreurs transitoires (Bedrock, lectures GitHub GET) ; écritures non rejouées.
  Module `retry.py` + tests.
- [x] **Authentification GitHub App** — token d'installation (~1 h) via JWT RS256,
  repli PAT. Module `github_auth.py` + tests.
- [x] **Garde-fou anti-DoS** — quota de runs par dépôt et par fenêtre (webhook) +
  IAM `UpdateItem`. Tests.
- [x] **Observabilité** — dashboard recâblé sur la durée de run EMF (moy./p90/échecs).
- [x] **Rétention logs** — 30 → 14 jours.
- [x] **Nettoyage & doc** — dead code retiré, docs (README/design/requirements)
  alignées sur le code.

## Chantiers structurants restants (hors code applicatif)

- [ ] **CMK KMS** — rétablir le chiffrement par clés gérées client (secrets, SQS,
  DynamoDB, logs) + rotation (nécessite droits `kms:CreateKey`).
- [ ] **WAF** — associer un AWS WAF (rate-based + règles managées) à l'API Gateway.
- [ ] **CI/CD** — pipeline de build/test/déploiement ; **paramétrer le backend S3**
  (retirer le bucket de state codé en dur dans chaque `providers.tf`).
- [ ] **DR / multi-région** — stratégie de reprise selon la cible de disponibilité.
- [ ] _(code, optionnel)_ **Résumé hiérarchique** des gros dépôts (réduction tokens
  vs escalade Sonnet).
- [ ] _(code, optionnel)_ **Parallélisation des lectures** de fichiers + **streaming
  du tarball** (lève le plafond mémoire sur très gros dépôts).
- [x] _(code)_ Tests de l'**entrypoint async** (`agent.py`, faux SDK injecté) et de
  la **signature RS256 réelle** (skip si `cryptography`/PyJWT absents ; validée en
  venv). Extraction tarball déjà couverte par `test_repo_reader.py`.

## Tests E2E (progression)

- [x] **Phase 0 — Contrats locaux** : tests RS256 réel + entrypoint async + tarball
  (fermeture des angles morts de l'injection de dépendances).
- [x] **Phase 1 — Runner « vraies dépendances »** (`e2e/local_run.py`) : exécute la
  vraie orchestration (App/PAT, tarball 302, Bedrock, draw.io, commit) sans chaîne
  AWS. Dry-run par défaut (écritures GitHub neutralisées), `--commit` pour le réel.
  Guardé par `tests/test_local_run.py`. _Nécessite creds AWS Bedrock + GitHub pour
  une exécution réelle (non jouée en CI hors ligne)._
- [ ] **Phase 2 — Déploiement sandbox + smoke manuel** (PR → `@mention` → doc).
  Runbook + helper `e2e/smoke_check.py` (vérifie doc `docs/agent/` + commentaire
  terminal, verdict PASS/FAIL/TIMEOUT) livrés ; **exécution du déploiement à faire
  côté sandbox** (droits AWS + GitHub App/webhook requis).
- [ ] **Phase 3 — Harnais E2E automatisé** : événement synthétique signé HMAC →
  chaîne AWS complète ; fixtures PR/branche, polling async, assertions structurelles,
  teardown (idempotence + quota). Livré : `e2e/harness.py` + cross-check hors ligne
  `tests/test_harness.py` (événement/signature acceptés par la vraie logique webhook)
  + test gated `tests/test_e2e_webhook.py` (marqueur `e2e`, skippé sans stack).
  **Exécution bout-en-bout à faire sur stack déployée.**
- [ ] **Phase 4 — Industrialisation CI** (⏳ **à faire — non démarrée**) : pipeline
  nightly/on-demand `pytest -m e2e` ; stack éphémère (apply→E2E→destroy) ou sandbox
  long-vécu ; fixtures PR auto + teardown (idempotence + quota) ; assertions
  d'observabilité (EMF par `correlation_id`) ; secrets CI à moindre privilège.
  Prérequis : backend state paramétré (retirer le bucket codé en dur). Détail dans
  `e2e/README.md` (section Phase 4).
