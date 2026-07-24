# Performance Efficiency — Audit

**Score:** 80/100  **Maturity:** 4 (Managed)  **Coverage:** 95%  **Confidence:** high
**Applicable:** yes

## Charter & scope
Ce pilier évalue l'usage efficient des ressources de calcul et de données pour tenir
les exigences du système : dimensionnement du compute, adéquation du data store aux
patterns d'accès, conception des requêtes/index, mise en cache, traitement
asynchrone/par lots, réglages (timeouts, pooling, tailles de payload), concurrence,
proximité du contenu, cibles de performance (SLI) et leur mesure, tests de charge,
supervision de l'utilisation, et bornage des ressources.

Grounding : AWS Well-Architected — Performance Efficiency pillar
(https://docs.aws.amazon.com/wellarchitected/latest/userguide/waf.html).

Hors périmètre (traités ailleurs) : le coût brut (pilier Cost Optimization), la
scalabilité horizontale/limites d'échelle (pilier Scalability), la résilience/DR
(pilier Reliability). Audit **statique** (code/IaC), sans mesure runtime.

## Strengths
- **ARM64/Graviton partout** — meilleur rapport perf/watt/coût — _evidence: `terraform/ingestion/main.tf` (webhook `architectures = ["arm64"]`, worker `architectures = ["arm64"]`), image agent ARM64 (`.../agent-technical-doc/Dockerfile`, cf. inventory)._
- **Pipeline asynchrone découplé** — SQS + DLQ absorbent les rafales, et l'invocation AgentCore est non bloquante (`add_async_task`/`complete_async_task`, ack `accepted` en ~1 s) : le worker ne consomme pas ses 60 s à attendre le run — _evidence: `documentation/scripts/agents/agent-technical-doc/agent.py:88-116`, `docagent/orchestrator.py`._
- **Data store adapté au pattern d'accès** — DynamoDB on-demand pour l'idempotence + le quota, en accès clé/valeur (`PutItem` conditionnel, `Query` sur `LeadingKeys`) sans scan — _evidence: `terraform/ingestion/main.tf` (`ClaimIdempotency` PutItem/UpdateItem, `RateLimitQuery` Query + condition `dynamodb:LeadingKeys`)._
- **Tiering de modèle LLM déterministe** — Haiku par défaut, escalade vers Sonnet uniquement au-delà de 25 fichiers ou 400 Ko de contexte sélectionné → coût/latence maîtrisés sur la majorité des dépôts — _evidence: `docagent/analyzer.py:130-176` (`select_model`), `docagent/config.py:96-104`, `agents.json`._
- **Ressources bornées de bout en bout** — plafonds de lecture (`MAX_SELECTED_FILES=40`, `MAX_FILE_BYTES=80_000`, `MAX_TOTAL_BYTES=1_200_000`, `MAX_FILES=400`), quota anti-DoS par dépôt, throttling API 10 rps/burst 20, concurrence worker 5, `batch_size=1` — _evidence: `docagent/config.py:82-85`, `terraform/ingestion/main.tf` (stage `throttling_rate_limit=10/burst=20`, `scaling_config.maximum_concurrency`), `terraform/ingestion/variables.tf:66-70`._
- **Timeouts & pooling réglés** — client Bedrock : `read_timeout=900`, `connect_timeout=60`, retries `adaptive` ; visibilité SQS = timeout worker + 60 s ; payloads bornés par les caps de lecture — _evidence: `docagent/analyzer.py:186-195`, `terraform/ingestion/main.tf` (`visibility_timeout_seconds = var.worker_timeout_seconds + 60`)._
- **Observabilité applicative** — métrique EMF `DurationMs` (+ `Runs`, `FilesCommitted`) et dashboard avec moy./p90 de la durée de run par outcome — _evidence: `docagent/metrics.py:24-52`, `terraform/observability/main.tf` (widget « Durée de run — EMF (ms) », stats Average/p90)._

## Weaknesses / Findings

### [Medium] PERF-F1 — Tarball chargé intégralement en mémoire + lectures de fichiers séquentielles
- **Evidence:** `docagent/github_client.py:117-123` (`download_tarball` retourne `resp.body`, archive entière en RAM), `docagent/repo_reader.py:47-72` (`extract_tarball_safely` ouvre `io.BytesIO(tar_bytes)`), `docagent/orchestrator.py:150` (`files = {path: reader.read_file(path) for path in selected}` — lecture séquentielle).
- **Impact:** La taille du tarball téléchargé depuis GitHub n'est **pas bornée avant** l'extraction (seul le contenu *lu* est plafonné). Un dépôt très volumineux gonfle l'empreinte mémoire du conteneur AgentCore et la latence d'extraction. Les lectures de fichiers sont séquentielles ; impact réel faible car ce sont des lectures locales (post-téléchargement) et le facteur dominant du run reste l'appel LLM unique (non parallélisable utilement).
- **Recommendation:** Borner la taille du tarball au streaming (rejeter/tronquer au-delà d'un seuil, ex. 50–100 Mo) et streamer l'extraction depuis le flux HTTP plutôt que de matérialiser tout le corps en mémoire. Conserver les lectures séquentielles (suffisantes).
- **Alternative solution:** Streamer directement `urlopen(...)` dans `tarfile.open(fileobj=resp, mode="r|gz")` (tar en flux) avec un compteur d'octets qui interrompt au plafond. **Pros:** empreinte mémoire ~constante, échec rapide sur dépôt géant, pas de nouveau composant. **Cons:** le mode flux `r|gz` interdit `getmembers()` en amont (revoir la boucle de validation anti-traversal pour la faire au fil de l'eau) ; complexité modérée. **Effort:** M. **Cross-pillar impact:** reliability + (robustesse aux gros dépôts), sustainability + (moins de mémoire), security + (borne d'entrée non fiable).

### [Medium] PERF-F2 — Pas de cible de performance (SLO) définie ni de test de charge
- **Evidence:** `docagent/metrics.py:24-52` (SLI `DurationMs` émis) et `terraform/observability/main.tf` (dashboard affiche moy./p90) mais **aucune alarme/seuil sur la durée** (grep : les alarmes portent sur DLQ, erreurs Lambda, âge de file — pas sur `DurationMs`) ; aucun harnais de charge (dossier `e2e/` = smoke/E2E fonctionnel, pas de charge — cf. inventory).
- **Impact:** La latence de run est mesurée mais aucun objectif n'est formalisé ni surveillé automatiquement ; une dérive de performance (p. ex. escalade Sonnet trop fréquente, gros dépôts) ne déclenche aucun signal. Aucune preuve du comportement sous charge concurrente (au-delà du plafond de concurrence 5).
- **Recommendation:** Définir un SLO explicite (ex. p90 `DurationMs` < N s pour `Outcome=complete`) et poser une alarme CloudWatch dessus ; ajouter un test de charge léger (rafale de N webhooks) validant la tenue de la file et de la concurrence worker.
- **Alternative solution:** Réutiliser le harnais `e2e/` pour un scénario de charge scripté (envoi concurrent) plutôt qu'un outil externe. **Pros:** pas de dépendance nouvelle, réutilise l'existant. **Cons:** couverture de charge modeste (pas de profil réaliste GitHub). **Effort:** S–M. **Cross-pillar impact:** operational-excellence + (SLO/alerting), reliability +.

### [Low] PERF-F3 — Utilisation compute (mémoire/CPU) non supervisée
- **Evidence:** `terraform/observability/main.tf` — le dashboard suit `Invocations`, `Errors`, profondeur SQS, âge de file et `DurationMs`, mais **aucun widget d'utilisation ressource** (pas de `Duration` Lambda vs timeout, pas de mémoire max utilisée, pas de métrique CPU/mémoire conteneur AgentCore au-delà de `RuntimeErrors`).
- **Impact:** Impossible de confirmer que les 256 Mo des Lambdas sont bien dimensionnés (ni sur/ni sous-provisionnés) ni de détecter une pression mémoire côté runtime — le right-sizing repose sur le raisonnement de conception, pas sur la mesure.
- **Recommendation:** Ajouter au dashboard la `Duration` des Lambdas (marge vs timeout) et exploiter les logs `REPORT` (Max Memory Used) ; suivre l'utilisation mémoire/CPU du runtime AgentCore si exposée.
- **Alternative solution:** None — ajout de widgets simple et non structurant ; à intégrer dans le dashboard existant.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| PERF-01 | Compute right-sized & appropriate for workload. | Met | `terraform/ingestion/main.tf` (ARM64, webhook 256MB/15s, worker 256MB/60s), Dockerfile ARM64 (inventory) |
| PERF-02 | Data store fits access patterns. | Met | `terraform/ingestion/main.tf` (DynamoDB on-demand, PutItem/Query clé-valeur), `security/main.tf:57` (table idempotence) |
| PERF-03 | Query/index design avoids N+1/scans/hot partitions. | Met | `terraform/ingestion/main.tf` (`Query` + `dynamodb:LeadingKeys`, pas de Scan), clés `repo#pr#sha`/`repo#pr#comment_id` bien distribuées |
| PERF-04 | Caching where beneficial (CDN/app/DB) with invalidation. | Partial | `docagent/github_auth.py` (token installation ~1h, TTL = invalidation, cf. inventory) ; `terraform/ingestion/waf.tf` CloudFront présent mais non utilisé pour du cache (webhook POST) |
| PERF-05 | Async/batching for expensive/bursty work. | Met | `agent.py:88-116` (async task), `terraform/ingestion/main.tf` (SQS + DLQ) |
| PERF-06 | Timeouts, connection pooling, payload sizes tuned. | Met | `docagent/analyzer.py:186-195` (read/connect timeout, retries adaptive), `docagent/config.py:82-85` (caps payload), `terraform/ingestion/main.tf` (visibility = timeout+60) |
| PERF-07 | Concurrency/parallelism where it helps; no needless serialization. | Partial | `terraform/ingestion/main.tf` (`maximum_concurrency`, `batch_size=1`) ; mais `orchestrator.py:150` lectures séquentielles + `github_client.py:117-123` tarball intégral en RAM (PERF-F1) |
| PERF-08 | Content close to consumers (edge/region). | Met | `terraform/ingestion/waf.tf` (CloudFront edge devant l'HTTP API) |
| PERF-09 | Perf targets defined & measured (SLIs). | Partial | `docagent/metrics.py:24-52` (`DurationMs` mesuré) mais aucun SLO/seuil (PERF-F2) |
| PERF-10 | Load/perf testing evidence. | Missing | Aucun test de charge (inventory : « pas de test de charge dédié ») |
| PERF-11 | Resource utilization monitored. | Partial | `terraform/observability/main.tf` (invocations/erreurs/file/durée) sans utilisation mémoire/CPU (PERF-F3) |
| PERF-12 | Bounded resource use (pagination/limits). | Met | `docagent/config.py:82-85` (caps), `terraform/ingestion/variables.tf:66-70`, `main.tf` (throttling, concurrence) |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Borner la taille du tarball et streamer l'extraction (PERF-F1) | M |
| P2 | Définir un SLO p90 `DurationMs` + alarme, ajouter un test de charge léger (PERF-F2) | S–M |
| P3 | Ajouter au dashboard la `Duration` Lambda et le suivi mémoire (PERF-F3) | S |

## Notes & assumptions
- Audit **statique** : le dimensionnement compute (256 Mo Lambda, ARM64) est jugé
  approprié par raisonnement de conception (handlers légers : le webhook valide/enfile,
  le worker fait un seul `InvokeAgentRuntime` non bloquant), non confirmé par des
  métriques runtime (cf. PERF-F3).
- Le tiering de modèle et les caps de lecture pilotent directement latence et coût ;
  ils sont surchargeables par variables d'environnement (`config.py`).
- La mise en cache (PERF-04) est intrinsèquement peu applicable : chaque run produit un
  résultat unique (analyse d'une PR spécifique) ; le seul cache pertinent (token GitHub
  App ~1h) est présent. CloudFront sert le WAF/TLS edge, pas un cache de réponses.
- Coverage 95 % : tous les critères évaluables en statique ; seule la vérification
  runtime de l'utilisation effective des ressources manque.
