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
pip install -r requirements.txt    # boto3, strands-agents[otel], pyjwt[crypto], …
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

### Notes

- **Coût** : chaque exécution consomme des tokens Bedrock. Préférez Haiku.
- **Idempotence / quota** : désactivés en local (pas de DynamoDB).
- Ce runner ne teste **pas** la chaîne d'ingestion (webhook/HMAC/SQS/worker) ni
  l'invocation asynchrone du runtime — c'est l'objet des phases E2E déployées.
