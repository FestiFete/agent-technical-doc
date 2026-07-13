# Tests E2E — agent-technical-doc

## Phase 1 — Runner local « vraies dépendances » (`local_run.py`)

Exécute la **vraie** orchestration contre un dépôt GitHub réel, avec les vraies
dépendances (auth GitHub App/PAT, tarball, Bedrock, draw.io, commit), **sans**
déployer la chaîne AWS (ni API Gateway, ni SQS, ni Lambda, ni runtime AgentCore,
ni Secrets Manager, ni DynamoDB).

Objectif : dérisquer avant tout déploiement les intégrations que les tests
unitaires (injection de dépendances) ne couvrent pas :

- signature JWT **RS256** → token d'installation GitHub App (ou PAT) ;
- `download_tarball` et sa **redirection 302** (`api.github.com` → `codeload`) ;
- **analyse Bedrock** réelle (Strands) + parsing du JSON ;
- assemblage Markdown + validation des `.drawio` ;
- restitution GitHub (commit + commentaire) — en mode `--commit` uniquement.

### Prérequis

1. **Dépendances Python** (dans un venv dédié) :
   ```bash
   pip install -r ../requirements.txt   # boto3, strands-agents[otel], pyjwt[crypto], ...
   ```
2. **Credentials AWS** avec accès Bedrock (`bedrock:InvokeModel`) et **modèle
   activé** dans la région (profils Haiku/Sonnet). Ex. `AWS_PROFILE=sandbox`.
3. **Auth GitHub** via variable d'environnement :
   - GitHub App : `GITHUB_APP_SECRET='{"app_id":"…","private_key":"-----BEGIN…","installation_id":"…"}'`
     (`installation_id` optionnel — résolu par dépôt sinon) ;
   - ou PAT : `GITHUB_TOKEN=ghp_…`.
4. Une **PR ouverte** sur un **dépôt bac-à-sable** (branche du dépôt, pas un fork ;
   l'auteur doit être OWNER/MEMBER/COLLABORATOR).

### Pas à pas complet (dry-run avec aperçu local)

Toutes les commandes sont lancées **depuis** le dossier de l'agent :
`documentation/scripts/agents/agent-technical-doc`.

#### 1. Environnement Python (une fois)

```bash
cd documentation/scripts/agents/agent-technical-doc
python3 -m venv .venv
source .venv/bin/activate          # le prompt doit afficher (.venv)
pip install -r requirements.txt -r requirements-dev.txt   # runtime + pytest
python3 -c "import botocore, boto3, strands; print('deps OK')"
```

#### 2. Variables d'environnement (auth GitHub + AWS Bedrock)

```bash
# Token GitHub saisi SANS le coller dans la commande (invisible, hors historique)
read -rs GITHUB_TOKEN && export GITHUB_TOKEN     # colle le PAT, puis Entrée
#   (⚠️ pas d'espace autour du '=' si tu utilises 'export VAR=valeur')

export AWS_PROFILE=NewSysOps-375039967495        # profil avec accès Bedrock
export BEDROCK_REGION=eu-central-1
```

#### 3. Lancer le runner en dry-run avec `--out`

```bash
python3 e2e/local_run.py \
  --repo FestiFete/RogerVoiceTest \
  --pr 1 \
  --out /tmp/agent-doc-preview \
  -v
```

- `--repo owner/repo` : ton dépôt bac-à-sable (pas un placeholder).
- `--pr N` : numéro d'une **PR ouverte** sur ce dépôt.
- `--out <dir>` : répertoire (chemin **absolu** recommandé) où écrire l'aperçu.
- `-v` : logs détaillés.

#### 4. Lire la sortie

Le run affiche le bloc `RÉSULTAT` puis, si tout s'est bien passé :

```
===== RÉSULTAT =====
{
  "status": "complete",
  "files": ["docs/agent/README.md", "docs/agent/overview.md", ...],
  ...
}

8 fichiers écrits sous /tmp/agent-doc-preview/ (aperçu local, non commités)
OK (DRY-RUN (aucune écriture GitHub)). Fichiers : 8
```

⚠️ La ligne « **N fichiers écrits sous …** » n'apparaît **que** si :
- `--out` est bien passé **et**
- le statut est `complete` (l'aperçu est capturé au moment du « commit » factice).

#### 5. Lire les fichiers générés

```bash
# Lister l'arborescence produite
find /tmp/agent-doc-preview -type f

# Afficher un fichier
cat /tmp/agent-doc-preview/docs/agent/overview.md

# Vue d'ensemble rapide de tous les Markdown
for f in /tmp/agent-doc-preview/docs/agent/*.md; do
  echo "===== $f ====="; cat "$f"; echo
done
```

Arborescence attendue :

```
/tmp/agent-doc-preview/docs/agent/
├── README.md            # index
├── overview.md          # finalité
├── stack.md             # stack technique
├── architecture.md      # patterns & architecture
├── functional.md        # vue fonctionnelle
└── diagrams/
    ├── c4-context.drawio
    ├── c4-container.drawio
    ├── c4-component.drawio
    ├── sequence-main-flows.drawio
    └── data-model-er.drawio   # si un modèle de données est détecté
```

Les `.drawio` s'ouvrent dans [diagrams.net](https://app.diagrams.net) (Fichier →
Ouvrir) ou l'extension Draw.io Integration de VS Code.

#### 6. (optionnel) Commit réel

Une fois l'aperçu validé, pour écrire réellement sur la branche de la PR (dépôt
bac-à-sable uniquement) :

```bash
python3 e2e/local_run.py --repo FestiFete/RogerVoiceTest --pr 1 --commit -v
```

### Options

| Option | Effet |
|--------|-------|
| `--repo owner/repo` | Dépôt cible (**requis**) |
| `--pr N` | Numéro de PR ouverte (**requis**) |
| `--out <dir>` | Écrit l'aperçu local des fichiers générés (dry-run) |
| `--commit` | Écritures **réelles** (commit + commentaire). Défaut : dry-run |
| `--model <id>` | Override `MODEL_ID` (ex. forcer Haiku) |
| `--region <r>` | Override `BEDROCK_REGION` |
| `-v` | Logs détaillés |

Contrôle du coût (rester sur Haiku malgré un gros dépôt) :

```bash
MODEL_ESCALATION_MAX_FILES=100000 MODEL_ESCALATION_MAX_BYTES=100000000 \
  python3 e2e/local_run.py --repo FestiFete/RogerVoiceTest --pr 1 --out /tmp/agent-doc-preview -v
```

### Ce que le dry-run n'exerce pas

Les **écritures** GitHub (blob/tree/commit/ref/commentaire) sont neutralisées :
seul `--commit` valide la restitution réelle. En dry-run, le commit renvoyé est
factice (`DRYRUN…`) et le commentaire est journalisé, pas posté.

## Phase 2 — Déploiement sandbox + smoke manuel

Objectif : déployer la chaîne complète sur un compte AWS bac-à-sable, brancher une
GitHub App + un webhook, puis déclencher un run **de bout en bout** en commentant
sur une PR, et vérifier le résultat.

> ⚠️ Ces étapes créent des ressources AWS (coût) et nécessitent des droits de
> déploiement. À faire sur un **compte sandbox**.

### 1. Pré-requis

- Terraform >= 1.6, Docker (buildx ARM64), AWS CLI configuré (`AWS_PROFILE`).
- Accès Bedrock activé (Model access : Haiku + Sonnet) dans la région.
- Une **GitHub App** (Contents R/W, Pull requests R/W, événement *Issue comments*)
  installée sur le dépôt de test ; App ID + clé privée PEM.
- Un secret HMAC aléatoire pour le webhook.

### 2. Déploiement (depuis `documentation/terraform/`)

```bash
# 0. Bucket de state (une fois, backend local)
cd terraform/bootstrap
terraform init && terraform apply -var-file=../shared.tfvars
#   → reporter le nom du bucket dans shared.tfvars ET le backend "s3" de chaque providers.tf

# 1. Activer l'agent avant le module runtime
#   scripts/agents/agents.json : "enabled": true

# 2. Modules dans l'ordre
for m in ecr security roles runtime ingestion observability; do
  cd ../$m && terraform init && terraform apply -var-file=../shared.tfvars
done
#   ingestion prend aussi -var-file=terraform.tfvars (allowlist, mention, assocs)
```

### 3. Configuration post-déploiement

```bash
# Secret GitHub App (voir README racine ; PAT accepté en repli)
export APP_SECRET=$(python3 -c 'import json;print(json.dumps({"app_id":"123456","installation_id":"7654321","private_key":open("app.pem").read()}))')
aws secretsmanager put-secret-value --secret-id technical-doc-POC-github-token --secret-string "$APP_SECRET"

# Secret HMAC du webhook (même valeur qu'on mettra côté GitHub)
aws secretsmanager put-secret-value --secret-id technical-doc-POC-webhook-hmac --secret-string 'un-secret-aleatoire-long'

# URL du webhook
cd terraform/ingestion && terraform output webhook_url
```

- Côté GitHub (org ou dépôt) : **Webhooks → Add** → Payload URL = sortie
  `webhook_url`, Content type `application/json`, Secret = le même HMAC, événement
  **Issue comments** uniquement.
- Renseigner l'allowlist dans `terraform/ingestion/terraform.tfvars`
  (`allowed_repositories = ["FestiFete/RogerVoiceTest"]`) puis réappliquer `ingestion`.

### 4. Déclencher le smoke

Sur une **PR ouverte** du dépôt autorisé, poster un commentaire :

```
@agent-technical-doc peux-tu générer la documentation technique ?
```

Attendu : réaction 👀 immédiate, puis (quelques minutes) un commit sous
`docs/agent/` sur la branche de la PR + un commentaire récapitulatif.

### 5. Vérifier automatiquement le résultat

```bash
cd scripts/agents/agent-technical-doc
read -rs GITHUB_TOKEN && export GITHUB_TOKEN     # ou GITHUB_APP_SECRET
python3 e2e/smoke_check.py --repo FestiFete/RogerVoiceTest --pr 1 --timeout 300
```

- `PASS` : `docs/agent/` présent sur la branche head **et** commentaire de succès.
- `FAIL` : commentaire d'échec/fork détecté (le corps est affiché).
- `TIMEOUT` : rien de terminal dans le délai → tracer via les logs (étape 6).

### 6. Tracer un run (observabilité)

Récupérer le `X-GitHub-Delivery` (onglet *Recent Deliveries* du webhook GitHub),
puis chercher ce `correlation_id` dans les 3 groupes de logs :

```bash
aws logs filter-log-events --log-group-name /aws/lambda/technical-doc-POC-webhook  --filter-pattern '"<delivery-id>"'
aws logs filter-log-events --log-group-name /aws/lambda/technical-doc-POC-worker   --filter-pattern '"<delivery-id>"'
aws logs filter-log-events --log-group-name /aws/bedrock-agentcore/runtime/agent-technical-doc-POC --filter-pattern '"<delivery-id>"'
```

Dashboard : `technical-doc-POC-overview` (invocations, erreurs, SQS/DLQ, durée de
run EMF, runs par outcome). Alarmes : DLQ non vide, erreurs webhook/worker/runtime.

### 7. Teardown

```bash
# Ordre inverse du déploiement
for m in observability ingestion runtime roles security ecr; do
  cd terraform/$m && terraform destroy -var-file=../shared.tfvars; cd -
done
# bootstrap (bucket de state) : vider puis détruire si le sandbox est jetable.
```

### Dépannage rapide

| Symptôme | Piste |
|----------|-------|
| Pas de réaction 👀 | Webhook non reçu (URL/HMAC) ou dépôt hors allowlist / auteur non autorisé |
| 401 côté webhook | Secret HMAC GitHub ≠ `technical-doc-POC-webhook-hmac` |
| Commentaire d'échec « fork » | PR issue d'un fork (non supporté) |
| Échec auth GitHub | Secret App mal formé, App non installée sur le dépôt |
| `AccessDeniedException` Bedrock | Modèle non activé dans la région / rôle runtime |
| DLQ non vide | Inspecter le message, tracer par `correlation_id`, corriger, redrive |

## Phase 3 — Harnais E2E automatisé

Déclenche la chaîne **déployée** via un événement `issue_comment` **synthétique
signé HMAC**, posté directement sur l'API Gateway (sans dépendre de la livraison
webhook de GitHub), puis vérifie automatiquement le résultat.

Deux niveaux, selon ce qui est disponible :

### a) Hors ligne (toujours joué, dans la suite normale)

`tests/test_harness.py` valide — **sans stack ni réseau** — que l'événement et la
signature produits par `e2e/harness.py` seraient **acceptés par la vraie logique
du webhook** (`verify_signature` + `evaluate_comment`, importés par chemin). C'est
le garde-fou qui garantit que le harnais reste cohérent avec le webhook.

### b) Bout-en-bout (stack déployée requise)

`tests/test_e2e_webhook.py` (marqueur `e2e`) : **skippé** si l'environnement d'une
stack déployée n'est pas fourni. Sinon il POST l'événement signé, attend un
`202`, puis sonde via `smoke_check` jusqu'au `PASS`.

```bash
cd scripts/agents/agent-technical-doc
export E2E_API_URL="$(cd ../../../terraform/ingestion && terraform output -raw webhook_url)"
export E2E_WEBHOOK_SECRET='le-meme-secret-hmac'
export E2E_REPO='FestiFete/RogerVoiceTest'
export E2E_PR='1'
read -rs GITHUB_TOKEN && export GITHUB_TOKEN     # ou GITHUB_APP_SECRET
# optionnel : export E2E_TIMEOUT=420  E2E_MENTION='@agent-technical-doc'

python3 -m pytest tests/test_e2e_webhook.py -m e2e -v
```

Options utiles : `-m e2e` pour ne cibler que le test E2E ; le lancer avec
`E2E_*` non défini le **skippe** proprement (utile en CI hors ligne).

### Précautions (idempotence, quota, coût)

- **Idempotence** `repo#pr#sha` : si le head de la PR n'a pas changé depuis un run
  réussi, l'agent renvoie `skipped_duplicate`. Le test reste `PASS` (doc + commentaire
  de succès déjà présents), mais pour valider un **nouveau** run, pousse un commit
  sur la branche de la PR (nouveau sha) ou supprime la clé DynamoDB.
- **Quota anti-DoS** : en env de test, mettre `MAX_RUNS_PER_REPO=0` (désactivé) ou
  purger les compteurs `ratelimit#…` entre deux campagnes.
- **comment_id** : le harnais en génère un unique par run → pas de dédup webhook.
- **Coût / durée** : chaque run consomme des tokens Bedrock et prend quelques
  minutes ; réserver ce test au **on-demand / nightly**, pas à chaque commit.
- **Nettoyage** : le harnais ne supprime pas le commit de doc produit (artefact
  attendu). Prévoir un teardown si le dépôt de test doit rester propre.

### Prochaines étapes (Phase 4)

Industrialisation : stack éphémère (`apply` → E2E → `destroy`) ou sandbox
long-vécu, assertions d'observabilité (métriques EMF par `correlation_id`), job CI
nightly.

### Notes

- **Coût** : chaque exécution consomme des tokens Bedrock. Préférez Haiku.
- **Idempotence / quota** : désactivés en local (pas de DynamoDB).
- Ce runner ne teste **pas** la chaîne d'ingestion (webhook/HMAC/SQS/worker) ni
  l'invocation asynchrone du runtime — c'est l'objet des phases E2E déployées.
