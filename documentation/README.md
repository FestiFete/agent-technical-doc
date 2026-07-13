# agent-technical-doc

Agent de **documentation technique** headless sur AWS Bedrock AgentCore. Déclenché
par un `@mention` dans un commentaire de Pull Request GitHub, il clone le dépôt en
lecture seule, l'analyse statiquement (finalité, stack, patterns, architecture,
fonctionnel) et commite une documentation versionnée (Markdown + schémas
`.drawio` : C4 Context/Container/Component, Séquence, ER) sur la branche de la PR,
puis poste un commentaire récapitulatif.

Ce répertoire regroupe le code de l'agent, les Lambdas d'ingestion et le
Terraform. Il peut être extrait tel quel vers un dépôt dédié. Les specs
(requirements, design, tasks) vivent dans `.kiro/specs/agent-technical-doc/`.

## Arborescence

```
documentation/
├── scripts/
│   ├── agents/
│   │   ├── agents.json        # source de vérité (discovery + env)
│   │   └── agent-technical-doc/
│   │       ├── agent.py        # entrypoint BedrockAgentCoreApp
│   │       ├── instructions.md # prompt système durci (anti prompt-injection)
│   │       ├── Dockerfile      # image ARM64
│   │       ├── requirements.txt
│   │       ├── docagent/       # logique métier (testable sans boto3/strands)
│   │       └── tests/          # tests unitaires/intégration (sans réseau)
│   └── lambdas/
│       ├── webhook-receiver/   # HMAC + filtrage + autorisation + dedup + enqueue
│       ├── worker-dispatcher/  # SQS → InvokeAgentRuntime
│       └── tests/              # tests unitaires (sans réseau)
└── terraform/
    ├── shared.tfvars
    ├── bootstrap/     # bucket S3 du state
    ├── ecr/           # repository d'images
    ├── security/      # secrets (GitHub App/PAT, HMAC) + DynamoDB idempotence
    ├── roles/         # rôle d'exécution runtime (moindre privilège)
    ├── runtime/       # build/push ARM64 + runtime AgentCore + logs
    ├── ingestion/     # API Gateway + Lambdas + SQS/DLQ
    └── observability/ # dashboard + alarmes
```

## Architecture (résumé)

```
Commentaire PR @agent
  → API Gateway (HTTPS)
  → Lambda webhook (HMAC + mention + allowlist + author_association + dedup + quota anti-DoS + ack 👀)
  → SQS (+ DLQ)
  → Lambda worker (InvokeAgentRuntime scopé à l'ARN ; invocation asynchrone → se libère en ~1 s)
  → AgentCore Runtime (session isolée, tâche de fond) :
       Secrets Manager → auth GitHub App (token d'installation ~1 h) / repli PAT
       résolution PR + refus des forks → idempotence repo#pr#sha
       clone shallow (lecture seule) → sélection bornée → analyse LLM (Haiku, escalade Sonnet ; retries sur transitoire)
       → rendu Markdown + .drawio → commit unique docs/agent/** → commentaire terminal
```

Détails dans `.kiro/specs/agent-technical-doc/design.md` (diagramme, invariants de
sécurité, analyse Well-Architected par pilier).

## Prérequis

- Compte AWS + droits de déploiement (IAM, KMS, Lambda, SQS, DynamoDB, API GW,
  Bedrock AgentCore, ECR, S3, CloudWatch).
- Terraform >= 1.6, Docker (buildx pour ARM64), AWS CLI configuré.
- Accès aux modèles Bedrock configurés : modèle primaire économique
  (`MODEL_ID`, défaut `eu.anthropic.claude-haiku-4-5`) et modèle d'escalade
  (`MODEL_ID_ESCALATION`, défaut `eu.anthropic.claude-sonnet-4-6`) utilisé
  automatiquement pour les dépôts volumineux/complexes.
- Une **GitHub App** de service (permissions minimales : `contents:write`,
  `pull_requests:write`), installée sur les dépôts autorisés, et un secret HMAC
  pour le webhook. Un PAT reste accepté en repli (voir ci-dessous).

## Déploiement (ordre)

Chaque module a un backend S3 (`providers.tf`). Avant tout : créez le bucket de
state via `bootstrap`, puis reportez son nom dans `shared.tfvars` **et** dans le
bloc `backend "s3"` de chaque `providers.tf` (ou via `-backend-config`).

```bash
# 0. State bucket (backend local, une seule fois)
cd terraform/bootstrap
terraform init && terraform apply -var-file=../shared.tfvars

# 1..N. Modules (backend S3), dans l'ordre :
for m in ecr security roles runtime ingestion observability; do
  cd ../$m
  terraform init
  terraform apply -var-file=../shared.tfvars
done
```

- `ingestion` prend aussi `-var-file=terraform.tfvars` (allowlist de dépôts,
  handle mentionné, associations d'auteur).
- `runtime` construit et pousse l'image Docker (ARM64) puis crée le runtime.
  Activez l'agent dans `scripts/agents/agents.json` (`"enabled": true`) avant
  d'appliquer `runtime`.

### Après déploiement

1. **Renseigner les secrets** (valeurs non gérées par Terraform) :
   ```bash
   # GitHub App (recommandé) : app_id + private_key PEM (+ installation_id optionnel).
   # Le token d'installation (~1 h) est généré automatiquement par l'agent.
   aws secretsmanager put-secret-value --secret-id technical-doc-POC-github-token \
     --secret-string '{"app_id":"123456","installation_id":"7654321","private_key":"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"}'
   # Repli PAT (migration) : {"token":"ghp_xxx"} est aussi accepté.
   aws secretsmanager put-secret-value --secret-id technical-doc-POC-webhook-hmac \
     --secret-string 'un-secret-aleatoire-long'
   ```
   `installation_id` est optionnel : s'il est absent, l'agent le résout par dépôt
   via l'API GitHub (nécessite que l'App soit installée sur le dépôt).
2. **Configurer le webhook GitHub** (org ou dépôt) : Payload URL = sortie
   `ingestion.webhook_url`, Content type `application/json`, Secret = le même que
   `webhook-hmac`, événement **Issue comments** uniquement.
3. **Renseigner l'allowlist** dans `terraform/ingestion/terraform.tfvars`
   (`allowed_repositories`) et réappliquer `ingestion`.

## Utilisation

Sur une PR d'un dépôt autorisé, commenter par exemple :

```
@agent-technical-doc peux-tu générer la documentation technique ?
```

L'agent pose une réaction 👀, génère la doc sous `docs/agent/`, la commite sur la
branche de la PR et poste un commentaire récapitulatif.

## Tests

```bash
# Logique de l'agent
cd scripts/agents/agent-technical-doc && python3 -m pytest -q
# Lambdas d'ingestion
cd ../../lambdas && python3 -m pytest -q
```

## Sécurité (points clés)

- **Endpoint public authentifié par HMAC** (`X-Hub-Signature-256`) ; rejet des
  payloads non signés.
- **Contenu du dépôt = donnée non fiable** : jamais exécuté, jamais interprété
  comme instruction. Le LLM n'est qu'un **analyseur** ; le rendu, la validation
  des schémas, le commit et le commentaire sont faits par du code déterministe.
- **Cible de commit codée en dur** : `docs/agent/**` sur la branche head de la PR
  (repo/branche/sha injectés, jamais dérivés du contenu). Chemins hors périmètre
  refusés par le code (`paths.normalize_output_path`).
- **PR de fork refusées** (contenu non maîtrisé, non poussable).
- **Autorisation du déclencheur** : allowlist de dépôts + `author_association`.
- **Authentification GitHub App** : token d'installation court (~1 h), permissions
  fines (repli PAT). Signature JWT RS256 côté agent ; token régénéré par run.
- **Moindre privilège** : rôles séparés ; worker `InvokeAgentRuntime` scopé à
  l'ARN ; runtime `GetSecretValue` scopé au secret, `dynamodb` scopé à la table.
- **Chiffrement au repos** : POC = clés gérées AWS (`aws/secretsmanager`, SSE-SQS,
  clé par défaut DynamoDB/logs). **CMK KMS à rétablir avant une prod à forts
  enjeux.** Secrets jamais journalisés (masquage `correlation.mask_secrets`).
- **Garde-fou anti-DoS** : quota de runs par dépôt et par fenêtre glissante (webhook).
- **Résilience** : idempotence `repo#pr#sha` (agent) + `repo#pr#comment_id`
  (webhook) — un seul run/commit malgré rejeux et parallélisme ; **relâchée en cas
  d'échec** (re-run possible) ; **retries backoff** sur erreurs transitoires
  (Bedrock, lectures GitHub), écritures non rejouées (anti-doublon).

## Runbook (exploitation)

- **DLQ non vide** (alarme `*-dlq-not-empty`) : inspecter les messages
  (`aws sqs receive-message --queue-url <dlq_url>`), identifier la cause via le
  `correlation_id` dans les logs, corriger, puis rejouer (redrive) vers la file
  principale.
- **Tracer un run** : chercher le `correlation_id` (= `X-GitHub-Delivery`) dans
  les logs des 3 composants (`/aws/lambda/technical-doc-POC-webhook`,
  `-worker`, `/aws/bedrock-agentcore/runtime/agent-technical-doc-POC`).
- **Rotation des identifiants GitHub** : `put-secret-value` sur `*-github-token`
  (clé privée de la GitHub App, ou PAT en repli). Le token d'installation est
  régénéré à chaque run ; le secret App est mis en cache par session, donc les
  nouvelles sessions prennent la nouvelle valeur.
- **Mettre à jour l'allowlist** : éditer `ingestion/terraform.tfvars` + réappliquer.
- **Quota anti-DoS (HTTP 429)** : un dépôt qui atteint `MAX_RUNS_PER_REPO` sur la
  fenêtre `RATE_WINDOW_SECONDS` est temporairement bloqué. Ajuster ces variables
  (`ingestion`) puis réappliquer ; les compteurs `ratelimit#…` expirent par TTL.
- **Faux positif fork / doublon** : vérifier le statut dans la table DynamoDB
  d'idempotence (`pk = owner/repo#pr#sha`).

## Limites POC & évolutions

- GitHub uniquement (GitLab / self-hosted hors périmètre).
- **GitHub App** (recommandée) : tokens d'installation courts (~1 h), permissions
  fines, multi-repo. Repli **PAT** conservé pour la migration (secret `{"token":...}`).
- Forks non pris en charge.
- Schémas `.drawio` sans rendu image (source éditable versionnée).
- Invocation **asynchrone native** AgentCore : l'agent lance le run en tâche de
  fond (`add_async_task`/`HealthyBusy`) et rend la main immédiatement ; le worker
  ne bloque plus (timeout court, pas de plafond 15 min synchrone). Vérifier que
  `max_lifetime_in_seconds` du runtime couvre la durée d'un run complet.
- **Sélection de modèle à deux niveaux** : Haiku par défaut, escalade Sonnet pour
  les gros dépôts. Le **résumé hiérarchique** (réduction des tokens sur très gros
  dépôts) n'est **pas encore implémenté** (sélection par score + troncature).
- **Chiffrement CMK KMS** à rétablir avant une prod à forts enjeux (POC : clés
  gérées AWS). Autres chantiers prod : WAF devant l'API Gateway, CI/CD + backend
  state paramétré, DR/multi-région.
