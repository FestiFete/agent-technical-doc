# Audit technique — agent-technical-doc

> Audit approfondi (qualité, sécurité, performance, scalabilité, coûts, AWS
> Well-Architected). Reflète l'état du code **validé en conditions réelles**
> (déclenchement par commentaire → webhook → SQS → worker → runtime AgentCore →
> commit + commentaire GitHub, avec traçabilité par `correlation_id`).

## 1. Synthèse / verdict

Solution **mûre pour un usage interne à enjeu modéré à élevé**, et à un petit
nombre de chantiers **infra** d'une prod à forts enjeux. Le cœur applicatif est de
très bonne qualité (architecture testable, sécurité par conception, 127 tests,
observabilité). Les écarts restants sont ciblés et documentés (CMK KMS, WAF, CI/CD,
DR), sans dette de code.

| Axe | Note | Commentaire |
|-----|------|-------------|
| Qualité de code | ★★★★★ | DI, fonctions pures, imports différés, 127 tests, doc fidèle |
| Sécurité | ★★★★☆ | Anti-injection, moindre privilège, GitHub App, HMAC, quota ; restent CMK + WAF |
| Fiabilité | ★★★★☆ | Idempotence (relâchée sur échec), retries backoff, SQS/DLQ ; mono-région |
| Performance | ★★★★☆ | Async, ARM64, Haiku, contexte borné ; tarball en mémoire, lectures séquentielles |
| Scalabilité | ★★★★☆ | Serverless scale-to-zero ; plafonds = quota Bedrock + mémoire gros dépôts |
| Coûts | ★★★★★ | Haiku+escalade, caps, worker async, logs 14 j, quota anti-DoS |
| Ops / WA OpsEx | ★★★★☆ | EMF, dashboard, alarmes, runbook ; manque CI/CD |

## 2. Points forts (Pros)

- **Sécurité par conception, pas par prompt** : garde-fou de chemin en dur
  (`paths.normalize_output_path`), cible de commit injectée (jamais dérivée du
  contenu), refus des forks, HMAC en temps constant, extraction tarball
  anti-traversal/anti-symlink, masquage des secrets, LLM sans pouvoir d'écriture.
- **GitHub App** (token d'installation ~1 h, permissions fines) avec repli PAT.
- **Auth webhook** HMAC obligatoire + allowlist + `author_association` + **quota
  anti-DoS** par dépôt/fenêtre.
- **Fiabilité** : idempotence `repo#pr#sha` **relâchée en cas d'échec** (re-run
  possible), **retries backoff** sur transitoire (Bedrock, lectures GitHub GET),
  écritures non rejouées (anti-doublon), SQS + DLQ.
- **Coût maîtrisé** : Claude Haiku par défaut + escalade Sonnet ciblée, contexte
  plafonné (~1,2 Mo / 40 fichiers / 80 Ko), worker async (~1 s facturé), logs 14 j.
- **Qualité & testabilité** : injection de dépendances (`OrchestratorDeps`),
  modules purs, imports boto3/strands/pyjwt différés, **127 tests** sans réseau ;
  harnais E2E (dry-run + événement synthétique signé) + cross-check hors ligne.
- **Observabilité** : métriques EMF par outcome + durée, dashboard, alarmes
  (DLQ/erreurs), `correlation_id` propagé sur les 3 composants.
- **IaC modulaire** (7 modules) : dépendances par remote state, `terraform validate`
  OK, garde-fous de nommage (`limited-`) et precondition (`runtime_arn`).

## 3. Points faibles / risques (Cons)

- **CMK KMS désactivée** (contournement du DENY `kms:CreateKey`) → chiffrement au
  repos par clés gérées AWS. Documenté, mais écart pour une prod à forts enjeux.
- **Endpoint public sans WAF** (seuls HMAC + throttling API GW 10 rps + quota
  applicatif). Pas de protection L7 ni rate-limit par IP.
- **Pas de CI/CD** ; bucket de state **codé en dur** dans chaque `providers.tf` ;
  déploiement multi-module manuel.
- **Tarball chargé entièrement en mémoire** → plafond sur très gros dépôts (session
  2 vCPU/8 Go). Les caps bornent la lecture, pas la taille de l'archive.
- **Lectures de fichiers séquentielles** dans `_build_repo_context`
  (parallélisables).
- **Résumé hiérarchique non implémenté** : les gros dépôts escaladent vers Sonnet
  (plus cher) au lieu d'être résumés par lots.
- **Qualité LLM des schémas** : la séquence/ER peuvent revenir vides (contrat
  durci depuis, mais comportement probabiliste).
- **Mono-région, pas de DR.**
- **Couverture** : l'appel Bedrock réel de l'analyseur n'est pas unit-testé (validé
  via injection + run réel) ; entrypoint async testé, RS256 testé (skip si crypto
  absente).

## 4. AWS Well-Architected — par pilier

### Sécurité (★★★★☆)
- Forts : moindre privilège par composant (worker `InvokeAgentRuntime` scopé ARN ;
  runtime `GetSecretValue` scopé secret, `dynamodb` scopé table, `bedrock:InvokeModel`
  scopé foundation-model + inference-profile) ; anti prompt-injection au niveau code ;
  HMAC ; GitHub App ; secrets jamais journalisés.
- Écarts : **CMK KMS** à rétablir ; **WAF** absent ; endpoint public.

### Fiabilité (★★★★☆)
- Forts : SQS + DLQ + redrive (maxReceiveCount 2) ; visibility ≥ timeout worker ;
  idempotence forte (claim/release) ; retries transitoires classifiés
  (worker) + backoff interne (agent) ; commentaire terminal garanti.
- Écarts : **mono-région / pas de DR** ; le run async ne bénéficie plus du retry SQS
  (compensé par retries internes + relâche d'idempotence pour re-run manuel).

### Efficacité des performances (★★★★☆)
- Forts : **ARM64/Graviton** partout, **invocation asynchrone** (worker non
  bloquant), **Haiku** par défaut, contexte borné, un seul appel LLM par run.
- Écarts : tarball en mémoire ; lectures séquentielles ; pas de prompt caching.

### Optimisation des coûts (★★★★★)
- Forts : tout serverless scale-to-zero ; Haiku + escalade ciblée ; caps resserrés ;
  worker ~1 s ; DynamoDB on-demand + TTL ; logs 14 j ; **quota anti-DoS** borne le
  coût déclenchable par dépôt.
- À faire : prompt caching Bedrock ; résumé hiérarchique ; AWS Budgets.

### Excellence opérationnelle (★★★★☆)
- Forts : EMF (Runs/DurationMs/FilesCommitted par Outcome), dashboard, alarmes,
  `correlation_id` de bout en bout, runbook, docs alignées.
- Écarts : **pas de CI/CD** ; secrets posés manuellement ; pas de log d'accès API GW.

### Durabilité (★★★★☆)
- Graviton, scale-to-zero, lectures bornées, rétention limitée.

## 5. Qualité de code

- Séparation nette : `docagent/` (logique pure, testable) vs intégrations (boto3,
  strands, urllib, pyjwt) importées **paresseusement**.
- **Injection de dépendances** de bout en bout (`OrchestratorDeps`) → tests sans
  réseau, dry-run local, harnais E2E.
- **127 tests** (107 agent + 20 lambdas), dont cross-check du harnais contre la vraie
  logique webhook. 2 skips intentionnels (RS256 sans crypto, E2E sans stack).
- Dead code retiré ; docstrings précises ; conventions cohérentes.

## 6. Coûts (modèle)

- **Poste dominant : Bedrock** (tokens d'entrée). Le reste (Lambda async, SQS, API GW,
  DynamoDB on-demand, Secrets ~0,80 $/mois, ECR, logs 14 j) est négligeable ; au
  repos, quasi zéro.
- Leviers restants : prompt caching, résumé hiérarchique, alarme AWS Budgets, suivi
  coût/run via l'EMF `DurationMs`/`Runs`.

## 7. Axes d'amélioration (priorisés)

1. **Sécurité prod** : rétablir les **CMK KMS** (+ rotation) et ajouter un **WAF**
   (règles managées + rate-based) devant l'API Gateway.
2. **Industrialisation** : **CI/CD** (lint + tests + `terraform validate`, déploiement
   ordonné) et **paramétrer le backend S3** (retirer le bucket codé en dur).
3. **Robustesse gros dépôts** : **streamer le tarball** (lever le plafond mémoire) +
   **paralléliser les lectures** de fichiers.
4. **Coût/qualité analyse** : **prompt caching** + **résumé hiérarchique** (réduire
   les tokens plutôt qu'escalader vers Sonnet).
5. **Qualité des schémas** : fiabiliser séquence/ER (contrat durci ; envisager un
   repli déterministe depuis `components` si le LLM renvoie vide).
6. **Résilience** : DR/multi-région selon l'exigence de disponibilité.

## 8. Reste à faire (chantiers structurants)

Voir aussi `.kiro/specs/agent-technical-doc/tasks.md` (section « Chantiers
structurants restants » et « Tests E2E »).

- [ ] **CMK KMS** (secrets, SQS, DynamoDB, logs) + rotation — requiert `kms:CreateKey`.
- [ ] **WAF** associé à l'API Gateway.
- [ ] **CI/CD** + backend state paramétré.
- [ ] **DR / multi-région**.
- [ ] **E2E Phase 4** : pipeline nightly `pytest -m e2e` (stack éphémère apply→E2E→destroy,
      fixtures PR + teardown idempotence/quota, assertions d'observabilité EMF).
- [ ] _(code)_ Streaming du tarball + parallélisation des lectures.
- [ ] _(code)_ Prompt caching + résumé hiérarchique.
- [ ] _(GitHub App)_ Migration complète du PAT vers l'App en production.

---
_Dernière mise à jour : audit approfondi post-validation E2E en conditions réelles._
