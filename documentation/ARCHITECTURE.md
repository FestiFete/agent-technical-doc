# Architecture — agent-technical-doc

Schémas détaillés de bout en bout : la chaîne d'ingestion (GitHub → AWS), le
pipeline interne de l'agent, et l'inventaire des composants avec leur config.

> Vue synthétique et invariants de sécurité : voir aussi
> `.kiro/specs/agent-technical-doc/design.md`. Audit complet : [`AUDIT.md`](AUDIT.md).

## 1. Vue d'ensemble — chaîne complète

```mermaid
flowchart TB
    subgraph GH["GitHub"]
        DEV["Developpeur\n(OWNER/MEMBER/COLLABORATOR)"]
        PR["Pull Request\n+ commentaire @agent-technical-doc"]
        WHK["Webhook GitHub\n(event: issue_comment)"]
        API_GH["API GitHub\napi.github.com"]
        CODELOAD["codeload.github.com\n(tarball, via redirect 302)"]
        BRANCH["Branche head de la PR\n(commit docs/agent/** + commentaire)"]
        DEV --> PR --> WHK
    end

    subgraph AWS["AWS - compte 375039967495 / eu-central-1"]

        subgraph ING["Module ingestion"]
            APIGW["API Gateway HTTP API\nPOST /webhook · stage default\nthrottle 10 rps / burst 20"]
            LWEB["Lambda webhook-receiver\nPython 3.12 · arm64 · 256 Mo · 15 s\nHMAC->filtre->authz->dedup->quota->enqueue"]
            SQS["SQS file principale\nSSE · visibility 120 s · retention 4 j"]
            DLQ["SQS DLQ\nretention 14 j · maxReceive 2"]
            LWORK["Lambda worker-dispatcher\narm64 · 256 Mo · 60 s\nESM batch=1 · concurrence 5"]
            APIGW --> LWEB
            LWEB -->|SendMessage| SQS
            SQS -.redrive.-> DLQ
            SQS -->|event source mapping| LWORK
        end

        subgraph SEC["Module security"]
            SM_TOKEN["Secrets Manager\ngithub-token (App/PAT)"]
            SM_HMAC["Secrets Manager\nwebhook-hmac"]
            DDB["DynamoDB idempotency\npk · TTL\n(cles repo#pr#* + ratelimit#*)"]
        end

        subgraph ROLES["Module roles (IAM, limited-*)"]
            R_WEB["role webhook\nGetSecret(hmac) · PutItem/UpdateItem · SendMessage"]
            R_WORK["role worker\nReceive/Delete SQS · InvokeAgentRuntime(ARN)"]
            R_RUN["role runtime execution\nECR pull · InvokeModel · Logs · EMF\nGetSecret(token) · DynamoDB(table)"]
        end

        subgraph RT["Module runtime"]
            ECR["ECR\nimage agent (arm64, par digest)"]
            AGENT["AgentCore Runtime\nnetwork PUBLIC · idle 900 s · max_lifetime 3600 s\nenv: MODEL_ID, caps, secret ARN, table…"]
            RLOG["CloudWatch Log Group runtime\n/aws/bedrock-agentcore/runtime/…"]
            ECR -->|image| AGENT
            AGENT --> RLOG
        end

        BR["Amazon Bedrock\nHaiku 4.5 (defaut) / Sonnet 4.6 (escalade)\ninference profiles eu.*"]

        subgraph OBS["Module observability"]
            DASH["CloudWatch Dashboard\ntechnical-doc-POC-overview"]
            ALM["Alarmes\nDLQ / erreurs webhook·worker·runtime"]
            EMF["Metriques EMF\nns AgentTechnicalDoc\nRuns·DurationMs·FilesCommitted"]
        end
    end

    WHK -->|"1. POST signe HMAC (HTTPS)"| APIGW
    LWEB -->|"2. GetSecretValue"| SM_HMAC
    LWEB -->|"3. PutItem dedup + quota"| DDB
    LWEB -->|"4. 202 accepte"| WHK
    LWORK -->|"5. InvokeAgentRuntime (scope ARN)"| AGENT
    AGENT -->|"6. GetSecretValue token"| SM_TOKEN
    AGENT -->|"7. claim/release idempotence"| DDB
    AGENT -->|"8. get PR / tarball"| API_GH
    API_GH -.->|redirect| CODELOAD
    AGENT -->|"9. InvokeModel"| BR
    AGENT -->|"10. commit + commentaire"| BRANCH
    AGENT -.->|EMF + logs| EMF
    LWEB -.-> EMF
    LWORK -.-> EMF
    R_WEB -.applique a.-> LWEB
    R_WORK -.applique a.-> LWORK
    R_RUN -.applique a.-> AGENT
```

### Légende des flux
1. webhook signé HMAC → 2. lecture secret HMAC → 3. dedup + quota DynamoDB →
4. 202 à GitHub → 5. worker invoque le runtime (ARN scopé) → 6. token GitHub →
7. idempotence (claim/release) → 8. PR + tarball (redirect codeload) →
9. Bedrock (InvokeModel) → 10. commit `docs/agent/**` + commentaire.
Pointillés = logs/métriques EMF + application des rôles IAM.

## 2. Pipeline interne de l'agent (`docagent`)

```mermaid
flowchart TB
    START["invoke(payload, context)\nagent.py @entrypoint"] --> PARSE["payload.parse_request\n(repo, pr, comment_id, correlation_id)"]
    PARSE -->|payload invalide| INVALID["status invalid_request"]
    PARSE --> ASYNC["app.add_async_task\n(/ping HealthyBusy)\n-> ack 'accepted' immediat"]
    ASYNC --> BG["thread de fond: run_documentation"]

    subgraph ORCH["orchestrator.run_documentation (deps injectees)"]
        TOK["github_auth.resolve_token\nsecrets.get_secret_dict\n(App JWT RS256 -> token instal. / PAT)"]
        CLI["github_client.GitHubClient\n(urllib, retry GET)"]
        RESOLVE["resout PR (head sha/ref, fork?)"]
        FORK{"fork ?"}
        CLAIM["idempotency.claim\nDynamoDB PutItem repo#pr#sha"]
        DUP{"deja traite ?"}
        FETCH["repo_reader: download_tarball\n+ extract_tarball_safely (anti-traversal)"]
        CTX["selection.select_files\n(+ stack_hints, data_model_likely)\ncaps: 40 fichiers / 80 Ko / 1,2 Mo"]
        ANALYZE["analyzer.BedrockAnalyzer\nselect_model (Haiku/escalade Sonnet)\nretry backoff sur transitoire"]
        BUILD["doc_builder.assemble_document_set\n+ drawio.build_drawio (valide)"]
        COMMIT["committer.commit_documents\n(tree->commit->update ref, 1 commit)\npaths.normalize_output_path (docs/agent/**)"]
        NOTE["comments.success/failure\n-> post_issue_comment"]
        METRIC["metrics.emit_run (EMF)"]
    end

    BG --> TOK --> CLI --> RESOLVE --> FORK
    FORK -->|oui| SKIPF["skipped_fork + commentaire"]
    FORK -->|non| CLAIM --> DUP
    DUP -->|oui| SKIPD["skipped_duplicate"]
    DUP -->|non| FETCH --> CTX --> ANALYZE --> BUILD --> COMMIT --> NOTE --> METRIC
    ANALYZE -.echec.-> FAIL["failure_comment + release idempotence"]
    BG --> DONE["app.complete_async_task\n(/ping Healthy)"]
```

## 3. Inventaire des composants (config exacte)

| Groupe | Composant | Sous-composants / config |
|--------|-----------|--------------------------|
| **GitHub** | Webhook | event `issue_comment`, Payload URL = API GW, secret HMAC |
| | API GitHub | `api.github.com` (PR, git data, comments), `codeload` (tarball, redirect 302) |
| **Ingestion** | API Gateway | HTTP API, route `POST /webhook`, stage `$default`, throttle 10 rps / burst 20 |
| | Lambda webhook-receiver | Py 3.12 arm64, 256 Mo, 15 s ; `verify_signature`, `evaluate_comment`, `_claim_idempotency`, `_rate_limited`, `_enqueue` |
| | SQS principale | SSE-SQS, visibility 120 s, rétention 4 j, redrive→DLQ (maxReceive 2) |
| | SQS DLQ | rétention 14 j |
| | Lambda worker-dispatcher | arm64, 256 Mo, 60 s, ESM batch=1, concurrence 5 ; classif. transitoire/permanent |
| **Security** | Secrets Manager | `technical-doc-POC-github-token`, `-webhook-hmac` (clés gérées AWS, CMK à venir) |
| | DynamoDB | table idempotence `pk` + TTL ; sert aussi les compteurs `ratelimit#…` |
| **Roles (IAM)** | 3 rôles `limited-*` | webhook / worker / runtime execution — moindre privilège scopé |
| **Runtime** | ECR | image arm64, référencée par digest |
| | AgentCore Runtime | network PUBLIC, idle 900 s, max_lifetime 3600 s, env (MODEL_ID, caps, ARNs) |
| | Log group runtime | `/aws/bedrock-agentcore/runtime/agent-technical-doc-POC` (rétention 14 j) |
| | `docagent` (17 modules) | orchestrator, github_auth, secrets, github_client, repo_reader, selection, analyzer, drawio, doc_builder, committer, comments, idempotency, metrics, paths, payload, retry, config |
| **Bedrock** | Modèles | Haiku 4.5 (défaut) / Sonnet 4.6 (escalade >25 fichiers ou >400 Ko) |
| **Observability** | Dashboard | invocations/erreurs Lambda, SQS vs DLQ, durée de run EMF, runs par outcome |
| | Alarmes | DLQ non vide, erreurs webhook/worker/runtime |
| | EMF | ns `AgentTechnicalDoc` : Runs, DurationMs, FilesCommitted (dim. Agent+Outcome) |

## 4. Invariants clés

- **L'agent ne touche jamais SQS** : SQS relie uniquement webhook-receiver (producteur)
  et worker-dispatcher (consommateur, via event source mapping). L'agent est invoqué
  par `InvokeAgentRuntime` (appel API direct).
- **Le webhook n'a pas le token GitHub** (moindre privilège) : la résolution de PR,
  le clone et la restitution sont faits par l'agent (rôle runtime).
- **Invocation asynchrone** : le worker reçoit un ack immédiat (~1 s) ; l'agent
  travaille en tâche de fond (`add_async_task`/`HealthyBusy`) jusqu'à `max_lifetime`.
- **Cible de commit figée** : `docs/agent/**` sur la branche head, dépôt/sha injectés,
  jamais dérivés du contenu (anti prompt-injection, appliqué par le code).
