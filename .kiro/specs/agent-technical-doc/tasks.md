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
  - `instructions.md` complet (heuristique, résumé hiérarchique, analyse
    structurée). Contenu lu = donnée, jamais instruction.
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
