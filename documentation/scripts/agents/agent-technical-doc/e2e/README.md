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

### Utilisation

```bash
# Dry-run (DÉFAUT) : lectures + analyse réelles, écritures GitHub interceptées.
GITHUB_TOKEN=ghp_xxx AWS_PROFILE=sandbox \
  python e2e/local_run.py --repo acme/widget --pr 42 -v

# Commit RÉEL sur la branche de la PR (dépôt bac-à-sable uniquement)
GITHUB_APP_SECRET='{"app_id":"123","private_key":"-----BEGIN…"}' AWS_PROFILE=sandbox \
  python e2e/local_run.py --repo acme/widget --pr 42 --commit

# Forcer un modèle / une région
python e2e/local_run.py --repo acme/widget --pr 42 --model eu.anthropic.claude-haiku-4-5 --region eu-central-1
```

Options : `--commit` (écritures réelles ; défaut = dry-run), `--model`, `--region`,
`-v` (debug).

### Ce que le dry-run n'exerce pas

Les **écritures** GitHub (blob/tree/commit/ref/commentaire) sont neutralisées :
seul `--commit` valide la restitution réelle. En dry-run, le commit renvoyé est
factice (`DRYRUN…`) et le commentaire est journalisé, pas posté.

### Notes

- **Coût** : chaque exécution consomme des tokens Bedrock. Préférez Haiku.
- **Idempotence / quota** : désactivés en local (pas de DynamoDB).
- Ce runner ne teste **pas** la chaîne d'ingestion (webhook/HMAC/SQS/worker) ni
  l'invocation asynchrone du runtime — c'est l'objet des phases E2E déployées.
