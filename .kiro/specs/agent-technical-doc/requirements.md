# Requirements — agent-technical-doc

Agent de documentation technique headless sur AWS Bedrock AgentCore. Déclenché
par un `@mention` dans un commentaire de Pull Request GitHub, il clone le dépôt,
l'analyse statiquement et produit une documentation versionnée (Markdown + schémas
`.drawio`) commitée sur la branche de la PR, avec un commentaire récapitulatif.

Ce document fige les décisions validées avec le porteur du besoin (POC).

## Décisions validées

| # | Sujet | Décision |
|---|-------|----------|
| 1 | Déclenchement + restitution | Webhook GitHub → API Gateway → Lambda (validation signature HMAC + filtrage du `@mention`) → `InvokeAgentRuntime` asynchrone. Restitution par **commit direct sur la branche de la PR** + commentaire récapitulatif. |
| 2 | Sandbox / exécution | **Analyse statique uniquement.** Aucune exécution du code du dépôt. Isolation par session AgentCore Runtime (microVM). |
| 3 | Cible SCM | **GitHub** uniquement pour le POC (GitLab hors périmètre). |
| 4 | Écriture des livrables | **Commit direct sur la branche head de la PR** d'origine (mise à jour de la même PR). |
| 5 | Schémas | Suite **C4 (Context / Container / Component) + Séquence + Modèle de données (ER)** si détecté, au format `.drawio` (XML mxGraph), **sans rendu image**. |
| 6 | Découverte stack/patterns/archi | **Raisonnement LLM** sur les fichiers lus via tools maison de lecture, sans parsing spécialisé. |
| 7 | Authentification GitHub | **PAT / token de service** stocké dans AWS Secrets Manager. |
| 8 | Parallélisme / conflits | **Isolation par session + idempotence** (`repo#pr#sha`) + **file SQS** (lissage/retry). **Un commit par run.** |
| 9 | Industrialisation | Socle Terraform existant + **observabilité renforcée** (OTEL/CloudWatch, métriques, alarmes, dashboard). |
| 10 | Gros dépôts | **Sélection heuristique + résumé hiérarchique** avec plafonds de fichiers/octets lus. Pas de Knowledge Base. |
| 11 | Génération `.drawio` | Le LLM génère directement le **XML mxGraph** (`.drawio`), un fichier par diagramme, versionné. Pas de rendu PNG/SVG. |
| 12 | État conversationnel | **Sans état.** Pas d'AgentCore Memory, pas de Knowledge Base. Chaque `@mention` déclenche une génération complète. |

## Exigences fonctionnelles (EARS)

- **EF-1** — QUAND un commentaire contenant le handle `@<agent>` est créé sur une
  Pull Request d'un dépôt autorisé, LE système DÉCLENCHE une génération de
  documentation pour le commit head de cette PR.
- **EF-2** — LE système DOIT valider la signature HMAC (`X-Hub-Signature-256`) de
  chaque webhook et rejeter tout payload non signé ou mal signé.
- **EF-3** — LE système NE DOIT déclencher QUE si l'auteur du commentaire a une
  `author_association` autorisée (`OWNER`, `MEMBER`, `COLLABORATOR`) ET si le dépôt
  figure dans l'allowlist.
- **EF-4** — LE système DOIT ignorer (avec message explicatif) les PR issues de
  **forks** pour le POC.
- **EF-5** — L'agent DOIT cloner le dépôt en lecture seule (clone shallow de la ref
  head), sans jamais exécuter le code du dépôt.
- **EF-6** — L'agent DOIT produire une documentation Markdown (finalité, stack,
  patterns, architecture, fonctionnel) sous `docs/agent/**`.
- **EF-7** — L'agent DOIT produire des schémas `.drawio` : C4 Context, Container,
  Component, un diagramme de Séquence des flux principaux, et un diagramme ER si un
  modèle de données est détecté.
- **EF-8** — L'agent DOIT écrire tous les livrables en **un seul commit** sur la
  branche head de la PR, puis poster un **commentaire terminal** (succès ou échec).
- **EF-9** — LE système DOIT être idempotent sur la clé `repo#pr#sha` : une même
  combinaison ne produit qu'un seul run/commit, même en cas de re-livraison ou de
  demandes parallèles.

## Exigences non fonctionnelles

- **ENF-Sécurité-1** — Le contenu du dépôt est traité comme **donnée non fiable** ;
  il n'est jamais interprété comme instruction (anti prompt-injection). Garde-fous
  imposés au niveau **code des tools + IAM**, pas seulement le prompt.
- **ENF-Sécurité-2** — Le tool de commit ne peut écrire que sous `docs/agent/**`,
  sur la branche head de la PR déclenchante (repo/branche/sha injectés par
  l'appelant, jamais dérivés du contenu lu).
- **ENF-Sécurité-3** — Moindre privilège strict, un rôle IAM par composant. Le
  worker n'a que `InvokeAgentRuntime` scopé à l'ARN du runtime. Secrets chiffrés KMS,
  jamais journalisés.
- **ENF-Fiabilité-1** — SQS + DLQ + redrive ; classification des erreurs
  transitoires (retry) vs permanentes (DLQ direct) ; commentaire terminal garanti.
- **ENF-Observabilité-1** — Un identifiant de corrélation (`X-GitHub-Delivery` →
  message SQS → `sessionId` runtime) est propagé et journalisé dans les 3 composants.
  Métriques (runs, succès, échecs, durée, tokens), alarmes, dashboard.
- **ENF-Coût-1** — Bornage du contexte (sélection + résumé + plafonds), tout
  serverless scale-to-zero, DynamoDB on-demand + TTL, rétention de logs bornée.
- **ENF-Portabilité-1** — Tout le code, les specs et le Terraform de l'agent vivent
  dans le répertoire autonome `/documentation`, extractible tel quel vers un dépôt
  dédié.

## Hors périmètre (POC)

- GitLab et instances self-hosted (GitHub Enterprise Server / GitLab self-managed).
- GitHub App (recommandée post-POC, en remplacement du PAT).
- PR issues de forks.
- Rendu image (PNG/SVG) des schémas.
- Exécution dynamique / build / tests du dépôt analysé.

## État d'implémentation (mises à jour post-POC)

Cette section trace les écarts entre les décisions figées ci-dessus et le code
actuel (les décisions d'origine sont conservées telles quelles pour l'historique).

- **GitHub App implémentée** (décision #7 / hors périmètre) : auth par token
  d'installation court (~1 h) via JWT RS256, avec **repli PAT** pour la migration.
- **Invocation asynchrone native** (décision #1) : l'agent lance le run en tâche
  de fond (`add_async_task`/`HealthyBusy`) et rend la main immédiatement ; le worker
  ne bloque plus.
- **Sélection de modèle à deux niveaux** : Claude **Haiku** par défaut, escalade
  **Sonnet** pour les dépôts volumineux/complexes.
- **Décision #10 (gros dépôts)** : à ce jour, **sélection heuristique par score +
  troncature + plafonds** (le *résumé hiérarchique* n'est pas encore implémenté).
- **Fiabilité** : idempotence `repo#pr#sha` **relâchée en cas d'échec** (re-run
  possible) ; **retries internes avec backoff** sur erreurs transitoires (Bedrock,
  lectures GitHub) ; les écritures GitHub ne sont pas rejouées (anti-doublon).
- **Garde-fou anti-DoS** : quota de runs par dépôt et par fenêtre glissante (webhook).
- **Chiffrement au repos (POC)** : clés gérées AWS (`aws/secretsmanager`, SSE-SQS,
  clé par défaut DynamoDB). Les **CMK KMS** (ENF-Sécurité-3) restent à rétablir
  avant une mise en production à forts enjeux.
