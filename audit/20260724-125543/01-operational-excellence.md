# Operational Excellence — Audit

**Score:** 64/100  **Maturity:** 3 (Defined)  **Coverage:** 95%  **Confidence:** medium
**Applicable:** yes

## Charter & scope
Ce pilier évalue la capacité à exploiter et faire évoluer le système : infrastructure et
opérations décrites en code, chaîne de livraison (CI/CD, déploiements réversibles),
observabilité (logs structurés, métriques golden signals, tracing, alarmes actionnables,
dashboards), documentation d'exploitation (runbooks), health checks, gestion de
configuration/parité d'environnements, tests comme garde-fou de livraison, boucle de
retour post-incident et stratégie de tags de propriété opérationnelle.

Hors périmètre (traités ailleurs) : le verrouillage du state Terraform et la structure des
modules (pilier Terraform), le contenu des contrôles de sécurité détectifs (pilier
Security), la robustesse du pipeline SQS→worker et la gestion des échecs par batch
(pilier Reliability, finding REL-F2).

**Contrainte organisationnelle prise en compte :** CloudTrail est désactivé dans ce compte
(`terraform/observability/terraform.tfvars:1` `enable_cloudtrail = false`) car un Deny org
explicite couvre tout le namespace `cloudtrail:` et un trail org-wide couvre déjà le compte.
L'IaC du trail existe et est togglable (`terraform/observability/cloudtrail.tf`). Cette
désactivation n'est **pas** pénalisée ; les contrôles détectifs/audit sont traités comme
org-managed (non vérifiables en statique), pas comme absents.

## Strengths
- Infrastructure entièrement en Terraform (7 modules), aucune dérive console assumée : build/push
  d'image et runtime inclus — _evidence: `terraform/observability/providers.tf:1`, `terraform/runtime/logs.tf:7`_
- Métriques EMF sur stdout (sans PutMetricData) couvrant les 4 golden signals via le dashboard —
  _evidence: `scripts/agents/agent-technical-doc/docagent/metrics.py:29`, `terraform/observability/main.tf:150`_
- `correlation_id` (= `X-GitHub-Delivery`) propagé de bout en bout sur les 3 composants
  (webhook → SQS → worker → runtime) — _evidence: `scripts/agents/agent-technical-doc/docagent/correlation.py:16`_
- Alarmes actionnables reliées à un vrai topic SNS (REL-F1 remédié) avec abonnement email optionnel
  et sortie `alarm_topic_arn` — _evidence: `terraform/observability/main.tf:21`, `terraform/observability/main.tf:34`, `terraform/observability/main.tf:104`_
- Alarme dédiée au « stall silencieux » (âge du plus vieux message de la file) que ni les erreurs
  worker ni la DLQ ne couvrent — _evidence: `terraform/observability/main.tf:104`_
- Runbook d'exploitation concret (DLQ, traçage par correlation_id, rotation des identifiants,
  allowlist, quota, faux positifs) — _evidence: `documentation/README.md:186`_
- Dashboard CloudWatch agrégé à 8 widgets pour la visibilité opérationnelle —
  _evidence: `terraform/observability/main.tf:129`_
- Health check natif : l'entrypoint AgentCore reste non bloquant, le travail lourd tourne en tâche
  asynchrone qui bascule `/ping` en `HealthyBusy` pour survivre à un run long —
  _evidence: `scripts/agents/agent-technical-doc/agent.py:32`, `scripts/agents/agent-technical-doc/agent.py:93`_
- Secrets masqués avant journalisation (défense en profondeur) — _evidence: `scripts/agents/agent-technical-doc/docagent/correlation.py:41`_
- `terraform fmt -check -recursive` passe sur le module observability (hygiène du code) — _evidence: `terraform fmt -check` exit 0_

## Weaknesses / Findings

### [High] OPS-F1 — Aucun pipeline CI/CD ; tests non appliqués comme garde-fou de livraison
- **Evidence:** absence de `.github/workflows` (recherche vide), absence de CodeBuild/CodePipeline ;
  `documentation/README.md:157` (« Phase 4 — industrialisation CI : ⏳ à faire »)
- **Impact:** déploiement Terraform manuel, multi-module et ordonné (bootstrap → ecr → security →
  roles → runtime → ingestion → observability), secrets posés à la main. Les 130 tests (verts) ne
  sont exécutés qu'à la discrétion de l'opérateur : rien ne garantit qu'un changement testé, formaté
  et validé passe avant `apply`. Risque d'erreur humaine, de dérive et de régression non détectée en
  livraison.
- **Recommendation:** ajouter un pipeline (GitHub Actions) : lint/format (`terraform fmt -check`),
  `terraform validate -backend=false`, `pytest` (agent + lambdas), puis `plan` sur PR et `apply`
  gaté par environnement/approbation. Faire des tests un gate obligatoire.
- **Alternative solution:** exécuter les mêmes étapes via CodePipeline + CodeBuild (natif AWS,
  auth par rôle IAM sans secret externe) plutôt que GitHub Actions.
  - _Pros :_ pas d'identifiants AWS à exporter vers GitHub, traçabilité dans le compte, intégration
    IAM native.
  - _Cons :_ plus d'infrastructure à gérer et à décrire en Terraform, boucle de feedback moins
    proche de la PR que GitHub Actions, courbe de mise en place plus lourde pour un POC.
  - _Effort :_ M
  - _Cross-pillar impact :_ reliability + (moins d'erreurs de déploiement), security + (moins de
    manipulation manuelle de secrets), cost +/- (minutes de build).

### [Medium] OPS-F2 — Logs applicatifs non structurés (texte, pas JSON)
- **Evidence:** `scripts/agents/agent-technical-doc/scripts/lambdas/webhook-receiver/handler.py`
  n'existe pas ; journalisation par `logging` avec format `%`-interpolé —
  `documentation/scripts/lambdas/webhook-receiver/handler.py:29`, `documentation/scripts/lambdas/webhook-receiver/handler.py:292`
- **Impact:** le `correlation_id` est bien présent mais noyé dans une chaîne texte
  (`... delivery=%s`), pas dans un champ JSON indexable. Les requêtes CloudWatch Logs Insights et la
  corrélation par champ sont plus fragiles ; seules les métriques (EMF) sont structurées.
- **Recommendation:** émettre des logs JSON avec des champs stables (`correlation_id`, `event`,
  `outcome`, `repo`) via un petit helper ou une lib (ex. structuration manuelle `json.dumps` déjà
  utilisée pour EMF). Faible effort, gros gain d'exploitabilité.
- **Alternative solution:** None — l'amélioration est directe (réutiliser le pattern EMF/JSON déjà
  en place) et n'implique aucun arbitrage d'architecture.

### [Low] OPS-F3 — Pas de tag de propriété opérationnelle
- **Evidence:** `terraform/observability/providers.tf:21` et pairs — `default_tags` ne portent que
  `Project`/`Env`/`Module` ; `terraform/security/providers.tf:20` n'a aucun `default_tags`
  (contournement `kms:TagResource`).
- **Impact:** pas de tag `Owner`/`Team`/`CostCenter` pour router incidents/coûts vers un
  responsable ; le module security n'est pas taggé du tout.
- **Recommendation:** ajouter un tag `Owner`/`Team` aux `default_tags` communs ; pour security,
  appliquer des tags par ressource là où `TagResource` est permis afin de ne pas régresser sur la
  contrainte KMS.
- **Alternative solution:** None — ajustement d'hygiène.

### [Low] OPS-F4 — Pas de mécanisme formalisé de retour post-incident
- **Evidence:** aucune trace de rétro/post-incident/feedback dans la doc (recherche vide sur
  `post-incident|rétro|feedback|lessons`).
- **Impact:** les incidents (DLQ, stall) sont détectés et diagnosticables (runbook), mais aucune
  boucle d'apprentissage documentée n'est prévue pour capitaliser.
- **Recommendation:** ajouter un gabarit léger de post-mortem (déclencheur, chronologie via
  `correlation_id`, cause racine, actions) au runbook.
- **Alternative solution:** None — pratique documentaire, pas de choix technique.

## Criteria grid
| id | criterion | verdict | evidence |
|----|-----------|---------|----------|
| OPS-01 | Infra & ops as code (no manual console drift) | Met | `terraform/observability/providers.tf:1`, `terraform/runtime/logs.tf:7`, `terraform/ecr/main.tf:40` |
| OPS-02 | CI/CD pipeline with automated build/test/deploy | Missing | absence `.github/workflows` (grep vide) ; `documentation/README.md:157` |
| OPS-03 | Small reversible deployments; rollback strategy | Partial | modules Terraform indépendants ; rétention d'images ECR permettant un retour arrière — `terraform/ecr/main.tf:40` |
| OPS-04 | Structured centralized logging (correlation ids, no secrets) | Partial | correlation_id + masquage OK, mais logs texte non JSON — `docagent/correlation.py:16`, `docagent/correlation.py:41`, `scripts/lambdas/webhook-receiver/handler.py:292` |
| OPS-05 | Metrics on golden signals (latency, traffic, errors, saturation) | Met | `docagent/metrics.py:29` (DurationMs), `terraform/observability/main.tf:150` (durée p90), `terraform/observability/main.tf:129` (invocations/erreurs/SQS/âge) |
| OPS-06 | Distributed tracing / request correlation | Partial | correlation_id de bout en bout + ADOT/OTEL pour le runtime AgentCore, mais pas de tracing X-Ray sur les Lambdas — `docagent/correlation.py:16`, `scripts/agents/agent-technical-doc/requirements.txt:8` |
| OPS-07 | Actionable alarms tied to SLIs; notification path defined | Met | `terraform/observability/main.tf:21`, `terraform/observability/main.tf:34`, `terraform/observability/main.tf:104` |
| OPS-08 | Runbooks / operational docs | Met | `documentation/README.md:186`, `documentation/AUDIT.md:24` |
| OPS-09 | Health checks & readiness/liveness | Met | `scripts/agents/agent-technical-doc/agent.py:32`, `scripts/agents/agent-technical-doc/agent.py:93` |
| OPS-10 | Config management & environment parity | Partial | config par env (12-factor) + tfvars, mais un seul environnement `POC` (pas de parité dev/prod) — `docagent/config.py:1`, `terraform/shared.tfvars` (`environment = "POC"`) |
| OPS-11 | Automated tests as a release gate | Partial | 130 tests verts mais non gatés par un pipeline — `documentation/README.md:157` |
| OPS-12 | Post-incident/feedback mechanism | Missing | aucune trace (grep vide) |
| OPS-13 | Tagging strategy for operational ownership | Partial | `default_tags` Project/Env/Module — `terraform/observability/providers.tf:21` ; pas d'Owner ; security sans tags — `terraform/security/providers.tf:20` |
| OPS-14 | Dashboards for operational visibility | Met | `terraform/observability/main.tf:129` |

## Prioritized improvements
| priority | action | effort |
|----------|--------|--------|
| P1 | Mettre en place un pipeline CI/CD (lint/format, validate, pytest gate, plan sur PR, apply gaté) — OPS-F1 | M |
| P2 | Passer les logs applicatifs en JSON structuré avec champs stables (correlation_id, event, outcome) — OPS-F2 | S |
| P3 | Ajouter un tag `Owner`/`Team` aux default_tags (et tags par ressource dans security) — OPS-F3 | S |
| P3 | Ajouter un gabarit de post-mortem au runbook — OPS-F4 | S |
| P3 | Documenter/outiller une parité d'environnements (dev/prod) au-delà du POC unique — OPS-10 | M |

## Notes & assumptions
- Audit **statique** (live_aws = OFF) : l'existence effective des alarmes/dashboard/métriques est
  jugée sur l'IaC et le code, pas sur l'état déployé.
- CloudTrail désactivé localement = contrainte org (Deny explicite), IaC togglable présente
  (`terraform/observability/cloudtrail.tf`) — non pénalisé, aucun finding sur cette désactivation.
- Coverage 95% : tous les critères ont pu être évalués sur le code/IaC ; la seule zone
  partiellement non vérifiable en statique est l'activation réelle du tracing ADOT côté runtime
  (dépendance présente, câblage runtime confirmé par la conception AgentCore Observability).
- Le finding Critical du pilier Terraform (state S3 non verrouillé, TF-F1) n'est pas recompté ici ;
  il impacte le capping global de maturité au niveau orchestrateur, pas le score de ce pilier.
