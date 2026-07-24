# Découplage (Decoupling) — Audit

**Score :** 86/100  **Maturité :** 4 (Managed)  **Couverture :** 95 %  **Confiance :** élevée
**Applicable :** oui

## Charte & périmètre
Ce pilier évalue le **degré de couplage lâche** entre composants/services, au runtime
comme au build : contrats stables (vs accès aux internes), découplage asynchrone
(files/événements), inversion de dépendances, isolation des pannes, versionnement des
contrats, déployabilité indépendante, découplage temporel (buffering) et absence de
cycles runtime.

Hors périmètre (traités ailleurs, croisés si besoin) : décomposition/cohésion statique
des modules → **Modularité (09)** ; choix de style architectural global → **Architecture
(07)** ; scalabilité élastique indépendante → **Scalabilité (11)** ; robustesse du
retry/DLQ et perte silencieuse d'erreurs → **Fiabilité (03)**.

## Points forts
- La chaîne d'ingestion est **découplée par une file SQS + DLQ** entre le producteur
  (Lambda webhook) et le consommateur (Lambda worker) : lissage de charge, buffering et
  isolation des pannes intégrés — _preuve : `documentation/terraform/ingestion/main.tf:6-23`, `documentation/scripts/lambdas/webhook-receiver/handler.py:286`_
- L'orchestrateur applique une **inversion de dépendances** explicite : `OrchestratorDeps`
  est un dataclass de `Callable` injectables (`get_token`, `make_client`, `fetch_repo`,
  `analyze`, `claim_idempotency`, `release_idempotency`), les implémentations réelles étant
  câblées paresseusement par `default_deps()`. La logique de haut niveau dépend
  d'abstractions, pas de concrétions (testable sans réseau) — _preuve : `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:35-84`_
- **Contrats de communication explicites et minimaux** : le message SQS et le payload
  `InvokeAgentRuntime` ne transportent que des métadonnées (`repo_full_name`, `pr_number`,
  `comment_id`, `correlation_id`) ; aucun composant ne lit les internes d'un autre — _preuve :
  `documentation/scripts/lambdas/webhook-receiver/handler.py:286-292`, `documentation/scripts/agents/agent-technical-doc/docagent/payload.py:11-33`_
- **Découplage temporel de l'agent** : le run long tourne en tâche de fond
  (`add_async_task`/`complete_async_task`) et le worker reçoit un accusé immédiat ; le slot
  de concurrence est libéré en ~1 s, le worker ne bloque pas — _preuve : `documentation/scripts/agents/agent-technical-doc/agent.py:95-105`_
- **Config & secrets injectés** : toutes les valeurs proviennent de variables
  d'environnement avec défauts sûrs, et le credential GitHub est lu depuis Secrets Manager
  par ARN à l'exécution (jamais embarqué) — _preuve : `documentation/scripts/agents/agent-technical-doc/docagent/config.py:60-100`, `documentation/terraform/ingestion/main.tf:198-214`_
- **Graphe de déploiement acyclique** : les 7 modules Terraform sont câblés uniquement via
  les sorties `terraform_remote_state`, sans cycle (aucun module ne relit un module qui le
  relit) — _preuve : `documentation/terraform/ingestion/data.tf:3-19`, `documentation/terraform/runtime/data.tf:1-32`_
- **Isolation des pannes** : le worker classe les erreurs transitoires (rejeu SQS→DLQ) vs
  permanentes (absorbées, sans tempête de rejeu) et l'orchestrateur garantit un commentaire
  terminal + relâche d'idempotence sur tout échec — un run raté ne casse jamais
  l'infra webhook/worker — _preuve : `documentation/scripts/lambdas/worker-dispatcher/handler.py:25-33,73-95`, `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:249-269`_

## Faiblesses / Findings

### [Low] DEC-F1 — Contrats inter-composants non versionnés
- **Preuve :** `documentation/scripts/lambdas/webhook-receiver/handler.py:286-292` (message SQS
  sans champ de version), `documentation/scripts/agents/agent-technical-doc/docagent/payload.py:83-110`
  (`parse_request` tolérant mais aucun `schema_version`).
- **Impact :** Le message SQS et le payload `InvokeAgentRuntime` n'embarquent pas de champ
  de version de schéma. Le parsing tolérant (champs optionnels résolus plus tard) offre une
  compat ascendante *de facto*, mais un changement incompatible du contrat (renommage/typage
  d'un champ requis) ne serait détecté qu'à l'exécution, sans possibilité de router/rejeter
  proprement les anciens messages en vol lors d'un déploiement mixte.
- **Recommandation :** Ajouter un champ `schema_version` au message SQS et au payload
  d'invocation ; brancher/rejeter explicitement sur version inconnue côté worker et agent.
- **Solution alternative :** Formaliser le contrat via un schéma versionné (JSON Schema /
  dataclass partagée) validé en entrée des deux consommateurs.
  - *Pros :* évolutions de contrat sûres ; rejet explicite des messages obsolètes ; contrat
    documenté et testable.
  - *Cons :* léger surcoût de maintenance ; nécessite une discipline de bump de version.
  - *Effort :* S. *Impact cross-pilier :* Maintenabilité + / Fiabilité + (moins de surprises
    au déploiement mixte).

### [Low] DEC-F2 — Couplage au build via `remote_state` + bucket de state figé
- **Preuve :** `documentation/terraform/ingestion/data.tf:3-19,25-31` (lecture des sorties des
  modules `security` et `runtime` via `terraform_remote_state`), `documentation/terraform/ingestion/providers.tf:20`
  (`bucket = "amzn-agent-technical-doc-statetf-375039967495-eu-central-1"` en dur dans le bloc
  `backend "s3"`).
- **Impact :** Les modules sont déployables séparément (chacun son `key` d'état), mais un
  **ordre d'apply strict** est imposé et tout changement de *forme* d'une sortie amont casse
  les modules avals. Le bucket d'état est codé en dur dans le backend (le nom du compte y est
  incrusté), ce qui gêne la réutilisation multi-compte/multi-région. Couplage au build, pas au
  runtime — faible sévérité (cœur : **Terraform (08)** / **Modularité (09)**, croisé ici).
- **Recommandation :** Conserver l'usage explicite des sorties, mais envisager de publier les
  valeurs inter-modules dans **SSM Parameter Store** (consommées par `data.aws_ssm_parameter`)
  plutôt que via `terraform_remote_state`, et paramétrer le bucket de backend.
- **Solution alternative :** Découplage par SSM Parameter Store (ou variables d'entrée
  explicites) pour les valeurs partagées entre modules.
  - *Pros :* réduit le couplage direct à l'état d'un autre module ; propriétés de modules
    potentiellement gérées par des équipes distinctes ; backend paramétrable.
  - *Cons :* composant supplémentaire (paramètres SSM à gérer) ; latence/ordre de publication
    à orchestrer.
  - *Effort :* M. *Impact cross-pilier :* Terraform + / Modularité + / Opérabilité +/-.

### [Info] DEC-F3 — DynamoDB partagée entre webhook et agent (coordination, pas bus caché)
- **Preuve :** `documentation/terraform/security/main.tf:57` (table unique), écritures webhook
  `documentation/scripts/lambdas/webhook-receiver/handler.py:145` (dédup `repo#pr#comment_id`)
  et `:172-183` (compteurs `ratelimit#…`), écriture agent
  `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py` (`claim` `repo#pr#sha`).
- **Impact :** La table DynamoDB est partagée par le webhook (idempotence de livraison +
  compteurs de quota) et l'agent (idempotence forte `repo#pr#sha`). Les **espaces de clés sont
  disjoints** et la table sert de coordination (idempotence/rate-limit), **pas** de canal
  d'échange de messages : la communication réelle passe par SQS puis `InvokeAgentRuntime`. Ce
  n'est donc pas un « bus d'intégration caché ». Reste un léger couplage implicite par schéma
  partagé (`pk`, `ttl`, `status`). Cœur : **Architecture ARC-03** (croisé ici) → DEC-04 noté
  `Partial` de ce fait.
- **Recommandation :** Documenter explicitement la convention de partitionnement des clés
  (préfixes `repo#…` vs `ratelimit#…`) comme contrat interne ; à terme, isoler éventuellement
  les compteurs de rate-limit dans une table dédiée si la propriété doit diverger.
- **Solution alternative :** None — l'usage (idempotence + quota) est légitime et le
  partitionnement par préfixe évite toute collision ; scinder la table serait prématuré pour
  ce POC.

## Grille de critères
| id | critère | verdict | preuve |
|----|---------|---------|--------|
| DEC-01 | Communication par contrats stables, pas par les internes. | Met | `documentation/scripts/lambdas/webhook-receiver/handler.py:286-292`, `documentation/scripts/agents/agent-technical-doc/docagent/payload.py:11-33` |
| DEC-02 | Découplage asynchrone (files/événements) là où le sync est risqué. | Met | `documentation/terraform/ingestion/main.tf:6-23`, `documentation/scripts/agents/agent-technical-doc/agent.py:95-105` |
| DEC-03 | Inversion de dépendances : le haut niveau dépend d'abstractions. | Met | `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:35-84` |
| DEC-04 | Pas d'état mutable partagé / DB partagée en bus d'intégration caché. | Partial | `documentation/terraform/security/main.tf:57`, `documentation/scripts/lambdas/webhook-receiver/handler.py:145,172-183`, `documentation/scripts/agents/agent-technical-doc/docagent/idempotency.py` |
| DEC-05 | Config & secrets injectés, pas de références croisées en dur. | Met | `documentation/scripts/agents/agent-technical-doc/docagent/config.py:60-100`, `documentation/terraform/ingestion/main.tf:198-214,230-234` |
| DEC-06 | Isolation des pannes : pas de cascade synchrone. | Met | `documentation/scripts/lambdas/worker-dispatcher/handler.py:25-33,73-95`, `documentation/scripts/agents/agent-technical-doc/docagent/orchestrator.py:249-269` |
| DEC-07 | Contrats versionnés / rétro-compatibles. | Partial | `documentation/scripts/agents/agent-technical-doc/docagent/payload.py:83-110` (parsing tolérant, aucun champ de version) |
| DEC-08 | Déployabilité indépendante. | Partial | `documentation/terraform/ingestion/data.tf:3-31`, `documentation/terraform/ingestion/providers.tf:20` (ordre strict + bucket figé) |
| DEC-09 | Découplage temporel (buffering) pour producteurs/consommateurs en rafale. | Met | `documentation/terraform/ingestion/main.tf:6-23,238-247` |
| DEC-10 | Pas de dépendances circulaires au runtime. | Met | `documentation/scripts/agents/agent-technical-doc/agent.py:95-105`, `documentation/terraform/ingestion/data.tf:3-19` |

Calcul : Σ(crédit×poids) = 10,75 ; Σ(poids applicables) = 12,5 → **86/100** → maturité **4**.

## Améliorations priorisées
| priorité | action | effort |
|----------|--------|--------|
| P2 | Ajouter un champ `schema_version` au message SQS et au payload `InvokeAgentRuntime` ; brancher/rejeter sur version inconnue (DEC-F1). | S |
| P3 | Réduire le couplage au build en sourçant les valeurs inter-modules depuis SSM Parameter Store et en paramétrant le bucket de backend (DEC-F2, croisé Modularité/Terraform). | M |
| P4 | Documenter la convention de partitionnement des clés DynamoDB comme contrat interne (DEC-F3, croisé Architecture ARC-03). | S |

## Notes & hypothèses
- **Statique uniquement** (`live_aws = OFF`) : le comportement asynchrone (accusé immédiat,
  survie de session `HealthyBusy`) et la sémantique fire-and-forget de `InvokeAgentRuntime`
  sont **inférés du code** (`agent.py` `add_async_task`/`complete_async_task`), non observés en
  live. Aucune invocation AWS réelle.
- Le code cœur des frontières de communication (handlers webhook/worker, orchestrateur,
  `payload`, `config`, `idempotency`, retry) et le graphe complet `terraform_remote_state` ont
  été lus en intégralité ; couverture 95 % (les corps de ressources Terraform non liés au
  découplage n'ont pas été relus en profondeur).
- **Croisements (pas de double comptage)** : la perte silencieuse des erreurs *permanentes* du
  worker (absence de `function_response_types = ["ReportBatchItemFailures"]` sur l'event source
  mapping, `terraform/ingestion/main.tf:238`) est un défaut réel mais compté en **Fiabilité
  (03, REL-F2)** ; du point de vue découplage, l'absorption des erreurs permanentes *renforce*
  au contraire l'isolation (pas de tempête de rejeu), d'où DEC-06 `Met`.
- **Contrainte org** (CloudTrail/KMS/GuardDuty en Deny org) : sans effet sur ce pilier ; non
  pénalisée.
- Aucun finding `Critical`/`High` → **pas de capping** déclenché par ce pilier.
