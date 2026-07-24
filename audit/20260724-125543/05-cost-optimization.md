# Cost Optimization — Audit

**Score :** 85/100  **Maturity :** 4 (Managed)  **Coverage :** 95%  **Confidence :** high
**Applicable :** yes

## Charter & scope
Ce pilier évalue l'adéquation coût/valeur de l'architecture : modèle de tarification, dimensionnement,
mise à l'échelle vers zéro, cycles de vie du stockage et des logs, attribution des coûts (tags),
garde-fous budgétaires (budgets/anomalies), coûts de transfert de données et efficience générale.
Il ne couvre PAS la performance brute (voir performance-efficiency) ni la sustainability (voir 06).
Ancrage : AWS Well-Architected Cost Optimization Pillar
([doc](https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html)).

**Contrainte d'environnement (context pack) :** audit statique, aucun appel AWS live (pas de
Cost Explorer / facturation réelle consultable). Le Deny org sur CloudTrail implique qu'un trail
account-local n'est pas déployé ici — ce qui **évite aussi le coût d'un second trail** (S3 + CW Logs)
en doublon du trail org-wide. Cette désactivation n'est pas pénalisée.

## Strengths
- **Architecture 100% serverless, scale-to-zero natif** : Lambda (webhook/worker), SQS+DLQ,
  DynamoDB `PAY_PER_REQUEST`, AgentCore, Bedrock à la demande — aucun coût au repos.
  _evidence : `terraform/security/main.tf:59` (`billing_mode = "PAY_PER_REQUEST"`),
  `terraform/ingestion/main.tf:238-247` (event source mapping SQS→Lambda)._
- **ARM64 partout** (Lambdas + image runtime), ~20% moins cher qu'x86 à performance égale.
  _evidence : `terraform/ingestion/main.tf` (`architectures = ["arm64"]`, webhook + worker)._
- **Tiering de modèle Bedrock coût/qualité** : Haiku 4.5 par défaut (économique), escalade
  Sonnet 4.6 uniquement au-delà de 25 fichiers / 400 Ko de contexte sélectionné.
  _evidence : `docagent/config.py` (`MODEL_ID`, `MODEL_ESCALATION_MAX_FILES=25`, `MODEL_ESCALATION_MAX_BYTES=400000`)._
- **Plafonds de lecture bornant les tokens Bedrock** (coût d'entrée) : 40 fichiers sélectionnés,
  80 Ko/fichier, 1,2 Mo total. _evidence : `docagent/config.py` (ReadCaps)._
- **Rétention des logs bornée à 14 j** sur toutes les Lambdas, le runtime et les logs WAF.
  _evidence : `terraform/ingestion/variables.tf:65` (`default = 14`), `terraform/runtime/logs.tf:7`,
  `terraform/ingestion/waf.tf:53`._
- **Cycle de vie ECR** : purge des images non taguées après 1 j + conservation des N dernières
  images taguées. _evidence : `terraform/ecr/main.tf:23-52`._
- **Cycle de vie CloudTrail** (quand activé) : expiration S3 (365 j) + rétention CW Logs (90 j),
  avec `bucket_key_enabled` (réduit les appels KMS). _evidence : `terraform/observability/cloudtrail.tf:51-62`,
  `terraform/observability/variables.tf:74,80`._
- **Purge DynamoDB par TTL** (pas d'accumulation d'items d'idempotence).
  _evidence : `terraform/security/main.tf:63-66` (`ttl { enabled = true }`)._
- **Pas de VPC/NAT Gateway** : runtime en `network_mode = "PUBLIC"`, aucune Lambda en VPC → pas de
  coût NAT (~0,045 $/h + traitement par Go), mono-région → pas de transfert cross-région.
  _evidence : `terraform/runtime/main.tf:18-21`, grep vide sur `aws_nat`/`vpc_config`._
- **HTTP API** (moins chère que REST API) et **scale-to-zero de session** AgentCore (idle 900 s,
  max lifetime 3600 s). _evidence : `terraform/ingestion/main.tf` (`aws_apigatewayv2_api`),
  `terraform/runtime/data.tf:55-56`, `terraform/runtime/main.tf:23-26`._

## Weaknesses / Findings

### [Medium] COST-F1 — Aucun budget ni détection d'anomalie de coût
- **Evidence :** grep vide sur `aws_budgets_budget` / `ce_anomaly_monitor` / `cost_category`
  dans `terraform/**/*.tf` ; confirmé context pack `_context/inventory.md` (« Pas de budgets / cost anomaly »).
- **Impact :** aucune alerte proactive en cas de dérive de coût (ex. boucle d'invocations, escalade
  Sonnet massive, croissance des logs). Le risque de dépense incontrôlée est **atténué** par le quota
  anti-DoS par dépôt (`max_runs_per_repo = 20`/fenêtre 3600 s, `terraform/ingestion/variables.tf`) et
  les plafonds de lecture — d'où une sévérité Medium (pas de risque d'emballement financier majeur),
  mais la visibilité budgétaire reste absente.
- **Recommendation :** ajouter un `aws_budgets_budget` mensuel (montant + seuils 80/100%) notifiant
  le topic SNS d'alarmes déjà présent (`aws_sns_topic.alarms`), et/ou un moniteur AWS Cost Anomaly
  Detection sur le service Bedrock.
- **Alternative solution :** **Cost Anomaly Detection** (détection ML par service) au lieu d'un budget
  à seuil fixe. _Pros :_ s'adapte au trafic variable d'un POC, alerte sur écart relatif ; _Cons :_
  latence de détection (quotidienne), moins prévisible qu'un plafond dur. _Effort : S._
  _Cross-pillar impact : operational-excellence +._

### [Low] COST-F2 — Attribution des coûts par tags incomplète
- **Evidence :** `default_tags { Project = ... }` présent dans bootstrap/ecr/ingestion/roles/runtime/
  observability (`terraform/*/providers.tf`), **mais retiré du module security**
  (`terraform/security/providers.tf:22-24`) et tags explicitement supprimés sur la table DynamoDB
  (`terraform/security/main.tf` — commentaire « tags retirés »).
- **Impact :** les ressources du module security (Secrets Manager, DynamoDB) n'apparaissent pas dans
  la répartition des coûts par tag `Project` → attribution partielle en console de facturation.
- **Recommendation :** appliquer des tags par ressource dans le module security (sans `default_tags`
  pour éviter l'appel `kms:TagResource` bloqué par le Deny org) — Secrets Manager et DynamoDB
  acceptent des tags directs sans droit KMS.
- **Alternative solution :** None — contournement dicté par le garde-fou org (KMS TagResource) ;
  un tagging par ressource ciblé lève la limite sans réintroduire l'appel bloqué. _Effort : S._

### [Low] COST-F3 — Pas de teardown/planification d'environnement éphémère
- **Evidence :** un seul environnement `POC` (`terraform/shared.tfvars:` `environment = "POC"`),
  aucun mécanisme de destruction planifiée ; grep vide sur scheduler/arrêt automatique.
- **Impact :** négligeable — l'architecture 100% serverless n'engendre aucun coût au repos
  (Lambda/SQS/DynamoDB on-demand, AgentCore scale-to-zero). La seule dépense fixe résiduelle est le
  stockage S3 (state, images ECR bornées), marginal.
- **Recommendation :** documenter une procédure `terraform destroy` par module pour les environnements
  jetables ; pas d'automatisation nécessaire vu le coût quasi nul au repos.
- **Alternative solution :** None — le scale-to-zero serverless satisfait déjà l'intention du critère.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| COST-01 | Modèle de tarification adapté à l'usage (serverless/on-demand) | Met | `terraform/security/main.tf:59`, `terraform/ingestion/main.tf:238-247`, `terraform/runtime/main.tf:18-21` |
| COST-02 | Pas de ressources oisives/sur-provisionnées ; right-sizing | Met | `terraform/ingestion/main.tf` (mem 256 Mo, ARM64, timeouts 15/60 s), `docagent/config.py` (ReadCaps) |
| COST-03 | Scale-to-zero / auto-stop non-prod & bursty | Met | serverless (`billing_mode PAY_PER_REQUEST`), `terraform/runtime/data.tf:55-56` (idle 900 s / max 3600 s) |
| COST-04 | Cycles de vie du stockage (tiering/expiry, rétention logs bornée) | Met | `terraform/ecr/main.tf:23-52`, `terraform/observability/cloudtrail.tf:51-62`, `terraform/ingestion/variables.tf:65`, `terraform/security/main.tf:63-66` |
| COST-05 | Tags d'allocation / attribution des coûts | Partial | `terraform/*/providers.tf` (`default_tags Project`) mais `terraform/security/providers.tf:22-24` (retiré) |
| COST-06 | Budgets/alertes ou détection d'anomalie de coût | Missing | grep vide `aws_budgets_budget`/`ce_anomaly_*` ; `_context/inventory.md` |
| COST-07 | Évite les fonctionnalités managées coûteuses quand une option moins chère existe | Met | `docagent/config.py` (tiering Haiku/Sonnet), HTTP API `terraform/ingestion/main.tf`, pas de NAT/CMK |
| COST-08 | Coûts de transfert de données considérés (cross-AZ/région/NAT) | Met | `terraform/runtime/main.tf:18-21` (PUBLIC, pas de VPC/NAT), mono-région `shared.tfvars` |
| COST-09 | Environnements éphémères/dev détruits ou planifiés | Partial | env `POC` unique ; serverless idle-to-zero, pas de teardown explicite |
| COST-10 | Coût d'observabilité borné (rétention logs/métriques, sampling) | Met | rétention 14 j (`terraform/runtime/logs.tf:7`, `ingestion/variables.tf:65`), EMF stdout `docagent/metrics.py` |
| COST-11 | Usage efficient des ressources par unité de valeur | Met | ARM64, batch_size 1 + max_concurrency 5, invocation async, caps de lecture `docagent/config.py` |

Calcul : Σ(crédit×poids)=9,75 ; Σ(poids)=11,5 → 100×9,75/11,5 = 85/100 → maturité 4 (Managed).

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Ajouter un `aws_budgets_budget` mensuel (+ seuils SNS) et/ou Cost Anomaly Detection sur Bedrock (COST-F1) | S |
| P2 | Tagger explicitement Secrets Manager + DynamoDB dans le module security pour compléter l'attribution (COST-F2) | S |
| P3 | Documenter une procédure `terraform destroy` par module pour les environnements jetables (COST-F3) | S |

## Notes & assumptions
- Audit **statique** : le coût réel (Cost Explorer, facturation) n'est pas consultable ; l'évaluation
  repose sur l'IaC et le code applicatif.
- La désactivation locale de CloudTrail (Deny org) **n'est pas pénalisée** et évite en outre le coût
  d'un trail en doublon (S3 + CW Logs) du trail org-wide.
- Le risque de dépense incontrôlée Bedrock est borné par le quota anti-DoS par dépôt et les plafonds
  de lecture → aucun finding Critical/High sur ce pilier.
- Coverage 95% : les 11 critères ont pu être évalués sur preuve IaC/code ; seule l'efficience réelle
  au runtime (coût effectif par run) ne peut être mesurée en statique.
