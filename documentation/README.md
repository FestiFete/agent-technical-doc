# agent-technical-doc

Agent de **documentation technique** headless sur AWS Bedrock AgentCore. Déclenché
par un `@mention` dans un commentaire de Pull Request GitHub, il clone le dépôt en
lecture seule, l'analyse statiquement (finalité, stack, patterns, architecture,
fonctionnel) et commite une documentation versionnée (Markdown + schémas
`.drawio` : C4 Context/Container/Component, Séquence, ER) sur la branche de la PR,
puis poste un commentaire récapitulatif.

Ce répertoire est **autonome** : il contient les specs, le code de l'agent, les
Lambdas d'ingestion et le Terraform. Il peut être extrait tel quel vers un dépôt
dédié.

## Arborescence

```
documentation/
├── specs/                     # requirements, design (Well-Architected), tasks, plan
├── scripts/
│   ├── agents/
│   │   ├── agents.json        # source de vérité (discovery + env)
│   │   └── agent-technical-doc/
│   │       ├── agent.py        # entrypoint BedrockAgentCoreApp
│   │       ├── instructions.md # prompt système durci (anti prompt-injection)
│   │       ├── Dockerfile      # image ARM64
│   │       ├── requirements.txt
│   │       ├── docagent/       # logique métier (testable sans boto3/strands)
│   │       └── tests/          # 67 tests unitaires/intégration
│   └── lambdas/
│       ├── webhook-receiver/   # HMAC + filtrage + autorisation + dedup + enqueue
│       ├── worker-dispatcher/  # SQS → InvokeAgentRuntime
│       └── tests/              # 15 tests unitaires
└── terraform/
    ├── shared.tfvars
    ├── bootstrap/     # bucket S3 du state
    ├── ecr/           # repository d'images
    ├── security/      # KMS CMK + secrets (token GitHub, HMAC) + DynamoDB idempotence
    ├── roles/         # rôle d'exécution runtime (moindre privilège)
    ├── runtime/       # build/push ARM64 + runtime AgentCore + logs
    ├── ingestion/     # API Gateway + Lambdas + SQS/DLQ
    └── observability/ # dashboard + alarmes
```

## Architecture (résumé)

```
Commentaire PR @agent
  → API Gateway (HTTPS)
  → Lambda webhook (HMAC + mention + allowlist + author_association + dedup + ack 👀)
  → SQS (+ DLQ)
  → Lambda worker (InvokeAgentRuntime, scopé à l'ARN)
  → AgentCore Runtime (session isolée) :
       Secrets Manager → token GitHub
       clone shallow (lecture seule) → sélection bornée → analyse LLM (Bedrock)
       → rendu Markdown + .drawio → commit unique docs/agent/** → commentaire terminal
```

Détails dans `specs/design.md` (diagramme, invariants de sécurité, analyse
Well-Architected par pilier).

## Prérequis

- Compte AWS + droits de déploiement (IAM, KMS, Lambda, SQS, DynamoDB, API GW,
  Bedrock AgentCore, ECR, S3, CloudWatch).
- Terraform >= 1.6, Docker (buildx pour ARM64), AWS CLI configuré.
- Accès aux modèles Bedrock configurés : modèle primaire économique
  (`MODEL_ID`, défaut `eu.anthropic.claude-haiku-4-5`) et modèle d'escalade
  (`MODEL_ID_ESCALATION`, défaut `eu.anthropic.claude-sonnet-4-6`) utilisé
  automatiquement pour les dépôts volumineux/complexes.
- Un PAT GitHub de service (permissions minimales : `contents:write`,
  `pull_requests:write`) et un secret HMAC pour le webhook.

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
   aws secretsmanager put-secret-value --secret-id technical-doc-POC-github-token \
     --secret-string '{"token":"ghp_xxx"}'
   aws secretsmanager put-secret-value --secret-id technical-doc-POC-webhook-hmac \
     --secret-string 'un-secret-aleatoire-long'
   ```
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
# Logique de l'agent (67 tests)
cd scripts/agents/agent-technical-doc && python3 -m pytest -q
# Lambdas d'ingestion (15 tests)
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
- **Moindre privilège** : rôles séparés ; worker `InvokeAgentRuntime` scopé à
  l'ARN ; runtime `GetSecretValue` scopé au secret, `dynamodb` scopé à la table.
- **Chiffrement KMS** (secrets, SQS, DynamoDB, logs) ; token jamais journalisé
  (masquage `correlation.mask_secrets`).
- **Idempotence** `repo#pr#sha` (agent) + `repo#pr#comment_id` (webhook) : un seul
  run/commit malgré rejeux et parallélisme.

## Runbook (exploitation)

- **DLQ non vide** (alarme `*-dlq-not-empty`) : inspecter les messages
  (`aws sqs receive-message --queue-url <dlq_url>`), identifier la cause via le
  `correlation_id` dans les logs, corriger, puis rejouer (redrive) vers la file
  principale.
- **Tracer un run** : chercher le `correlation_id` (= `X-GitHub-Delivery`) dans
  les logs des 3 composants (`/aws/lambda/technical-doc-POC-webhook`,
  `-worker`, `/aws/bedrock-agentcore/runtime/agent-technical-doc-POC`).
- **Rotation du token GitHub** : `put-secret-value` sur `*-github-token` (le cache
  du runtime est par-session ; les nouvelles sessions prennent la nouvelle valeur).
- **Mettre à jour l'allowlist** : éditer `ingestion/terraform.tfvars` + réappliquer.
- **Faux positif fork / doublon** : vérifier le statut dans la table DynamoDB
  d'idempotence (`pk = owner/repo#pr#sha`).

## Limites POC & évolutions

- GitHub uniquement (GitLab / self-hosted hors périmètre).
- PAT de service (évolution recommandée : **GitHub App** — tokens d'installation
  courts, permissions fines, multi-repo ; le code des tools reste compatible).
- Forks non pris en charge.
- Schémas `.drawio` sans rendu image (source éditable versionnée).
- Invocation **asynchrone native** AgentCore : l'agent lance le run en tâche de
  fond (`add_async_task`/`HealthyBusy`) et rend la main immédiatement ; le worker
  ne bloque plus (timeout court, pas de plafond 15 min synchrone). Vérifier que
  `max_lifetime_in_seconds` du runtime couvre la durée d'un run complet.
