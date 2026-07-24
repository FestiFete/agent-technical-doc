# Well-Architected & Architecture Audit — agent-technical-doc — 20260724-125543 (UTC)

**Global score :** 83/100  **Global maturity :** 2/5 (plafonnée — sinon 4/5 « Managed »)
**Capping :** OUI — plafonnée à 2/5 par **1 finding Critical ouvert (TF-F1)**.
**Mode :** statique (code/IaC, `live_aws = OFF`)  **Cible :** `/Users/g.mirambeau/Development/AWS/agent-technical-doc`
**Pondérations :** Security ×1.5, Reliability ×1.3, autres ×1.0.

> **Contrainte org intégrée.** Le rôle SSO de déploiement porte des **Deny explicites au
> niveau organisation** sur CloudTrail (`cloudtrail:CreateTrail` **et** `DescribeTrails`),
> `kms:CreateKey` et probablement GuardDuty — services centralisés au niveau org. Le projet
> fournit l'IaC togglable (`observability/cloudtrail.tf`) et désactive correctement le trail
> local (`observability/terraform.tfvars:8` `enable_cloudtrail = false`). **Cette désactivation
> n'est pénalisée nulle part** : les contrôles détectifs/audit et l'absence de CMK sont notés
> `Partial` (gérés/assumés au niveau org, non vérifiables en statique), pas `Missing`.

## Scores par dimension

| # | Dimension | Score | Maturité | Sévérité max | Applicable |
|---|-----------|-------|----------|--------------|------------|
| 1 | Operational Excellence | 64 | 3 (Defined) | High (OPS-F1) | oui |
| 2 | Security | 89 | 4 (Managed) | Medium (SEC-F1) | oui |
| 3 | Reliability | 73 | 3 (Defined) | High (REL-F2) | oui |
| 4 | Performance Efficiency | 80 | 4 (Managed) | Medium (PERF-F1) | oui |
| 5 | Cost Optimization | 85 | 4 (Managed) | Medium (COST-F1) | oui |
| 6 | Sustainability | 98 | 5 (Optimized) | Info (SUS-F1) | oui |
| 7 | Architecture | 93 | 5 (Optimized) | Medium (ARC-F1) | oui |
| 8 | Terraform | 74 | 3 (Defined) | **Critical (TF-F1)** | oui |
| 9 | Modularity | 89 | 4 (Managed) | Medium (MOD-F1) | oui |
| 10 | Decoupling | 86 | 4 (Managed) | Low (DEC-F1) | oui |
| 11 | Scalability | 88 | 4 (Managed) | Medium (SCAL-F1) | oui |
| 12 | Maintainability | 76 | 4 (Managed) | High (MNT-F1) | oui |

**Score global pondéré = 83/100** (maturité 4 « Managed » avant plafonnement).

## Plafonnement (règle Critical-capping)

Un unique finding **Critical** reste ouvert : **TF-F1 — état S3 Terraform partagé sans
verrouillage** (pilier Terraform). Aucun `use_lockfile` ni table de verrou DynamoDB dans les
7 backends `s3` ; deux `apply` concurrents peuvent corrompre l'état. Conformément au barème,
la **maturité globale est plafonnée à 2/5** tant que ce Critical n'est pas résolu — bien que
le score pondéré (83) corresponde à un niveau 4. **Corriger TF-F1 (effort S) restaure
immédiatement la maturité à 4/5.**

## Findings Critical & High (consolidés)

| id | sévérité | pilier | titre | evidence |
|----|----------|--------|-------|----------|
| TF-F1 | **Critical** | Terraform | État S3 partagé sans verrouillage (ni `use_lockfile` ni DynamoDB lock) | `terraform/observability/providers.tf:11-16` ; grep global : aucun `use_lockfile`/`dynamodb_table` de verrou |
| REL-F2 | High | Reliability | Échecs permanents du worker perdus silencieusement (ni DLQ ni métrique) | `scripts/lambdas/worker-dispatcher/handler.py:106` ; `terraform/ingestion/main.tf:232` (pas de `ReportBatchItemFailures`) |
| OPS-F1 | High | Operational Excellence | Aucun pipeline CI/CD ; tests non appliqués comme gate de livraison | absence `.github/workflows` ; `README.md:157` |
| MNT-F1 | High | Maintainability | Aucun linter/formatter configuré ni gate qualité CI | absence `pyproject.toml`/`ruff.toml`/`.github/workflows` |

> Les findings CI/CD (OPS-F1, MNT-F1) et leurs cross-refs (TF-F5 « pas de CI IaC »,
> SEC-F4 « pas de contrôle sécu CI/CD ») décrivent le **même manque structurel** : un pipeline.
> Ils ne sont pas double-comptés (chacun scoré dans son pilier) et convergent vers une action
> unique dans la feuille de route.

## Feuille de route de remédiation

### Quick wins (effort faible, valeur élevée)
- **P0 — TF-F1 :** activer `use_lockfile = true` + relever `required_version >= 1.10.0` sur les
  7 backends `s3` (poste déjà en TF 1.15.7). **Lève le plafonnement global → maturité 4/5.** (S)
- **P1 — REL-F2 :** activer `function_response_types = ["ReportBatchItemFailures"]` (ou envoi DLQ
  explicite) + métrique EMF `PermanentFailures` → les échecs permanents redeviennent visibles. (S)
- **P1 — SEC-F1 / MNT-F2 :** figer les dépendances Python (`==` + hashes), épingler l'image de base
  par digest, activer `scan_on_push` ECR. (S)
- **P1 — TF-F3 :** `lifecycle { prevent_destroy = true }` sur bucket d'état, table d'idempotence, secrets. (S)
- **P2 — TF-F2 :** externaliser le backend (account id/région) via `-backend-config`. (S)
- **P2 — COST-F1 :** `aws_budgets_budget` mensuel (seuils 80/100 %) notifiant le topic SNS existant. (S)
- **P2 — REL-F3 :** ajouter un jitter au backoff exponentiel. (S)
- **P2 — TF-F4 :** rétablir `default_tags` dans le module `security` (contournement CMK obsolète). (S)

### Travaux structurels
- **OPS-F1 / MNT-F1 / TF-F5 / SEC-F4 — pipeline CI/CD :** GitHub Actions (ou CodePipeline) avec
  `terraform fmt -check` + `validate` + `plan` sur PR, `ruff` + `mypy` + `pytest --cov` en gate,
  scan déps/IaC (pip-audit/trivy/checkov), et `apply` gaté par approbation. (M) — traite 4 findings.
- **ARC-F1 / REL-F4 — posture DR :** documenter RTO/RPO + mono-région assumée pour le POC (S) ;
  pour la prod, PITR + re-déploiement multi-région piloté par IaC (L).
- **PERF-F1 / SCAL-F2 — tarball :** borner la taille de l'archive et streamer l'extraction (arrêt
  aux caps de lecture) pour une empreinte mémoire constante. (M)
- **PERF-F2 / SCAL-F1 / SCAL-F3 :** définir un SLO (p90 `DurationMs`) + alarme, modéliser la capacité
  (runs/h vs quota TPS Bedrock), ajouter un test de charge léger. (S–M)

## Méthode & limites

- **12 sous-agents** (un par pilier) lancés en parallèle sur un **context pack partagé**
  (`_context/inventory.md`) reflétant l'état courant du dépôt (REL-F1 remédié, CloudTrail
  désactivé via tfvars, WAF présent). Chaque finding porte une **evidence `path:line`**.
- **Statique uniquement** : chiffrement effectif, alarmes actives et existence du trail org-wide
  non vérifiables (le rôle de déploiement ne peut même pas lire CloudTrail/GuardDuty — Deny org).
- Outillage : `terraform fmt -check` + `validate -backend=false` exécutés (read-only, 7 modules OK,
  TF 1.15.7) ; 130 tests exécutés en lecture seule (107 agent + 2 skips, 23 lambdas). Scanners
  `tflint`/`checkov`/`tfsec`/`trivy`/`ruff` **absents** (non installés).
- **Dé-duplication** : TF-F1 (impact fiabilité), REL-F2 (impact ops), et les manques CI/CD sont
  scorés une seule fois dans leur pilier le plus pertinent et cross-référencés ailleurs.
- **Évolution vs audit précédent (`20260724-082551`)** : REL-F1 (stall silencieux + notification)
  est désormais **remédié** (topic SNS + alarme `main_queue_stalled` câblés) ; il ne cape plus.
  Le seul Critical restant est TF-F1.
