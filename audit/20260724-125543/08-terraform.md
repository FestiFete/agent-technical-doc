# Terraform — structure & bonnes pratiques — Audit

**Score :** 74/100  **Maturité :** 3 (Defined) — _plafonnée à 2/5 au niveau **global** par la Critique TF-F1 (voir §Findings)_
**Coverage :** 95 %  **Confidence :** high
**Applicable :** oui

## Charter & périmètre

Ce pilier évalue la **structure et l'hygiène du code Terraform** : disposition des
modules, gestion de l'état distant et de son verrouillage, épinglage des versions,
qualité des variables/outputs, propreté `fmt`/`validate`, absence de valeurs codées
en dur, DRY, `count`/`for_each`, dépendances explicites, `lifecycle`, tagging, identité
de déploiement et intégration continue IaC.

Il **ne** juge **pas** la posture de sécurité applicative (voir pilier Sécurité), la
fiabilité runtime (voir Fiabilité — REL-F2 sur l'event source mapping y est traité), ni
l'architecture cible (voir Architecture). Le chiffrement effectif, l'existence réelle du
trail org et l'état des alarmes ne sont pas vérifiables en statique.

Périmètre : `documentation/terraform/` — 7 modules racines segmentés par cycle de vie
(`bootstrap`, `ecr`, `security`, `roles`, `runtime`, `ingestion`, `observability`),
câblés entre eux via `terraform_remote_state`. Terraform local disponible : v1.15.7.

## Points forts

- **Segmentation de l'état par cycle de vie** — 7 états S3 distincts (`key` par module),
  câblage explicite par `terraform_remote_state`. Découplage propre bootstrap → ecr/security
  → roles → runtime → ingestion → observability — _evidence : `documentation/terraform/roles/data.tf:3`, `documentation/terraform/observability/main.tf:1`._
- **Versions épinglées + lock committé** — `required_version >= 1.6.0`, `aws ~> 6.0`,
  `awscc ~> 1.0`, `archive ~> 2.0`, `random ~> 3.6` ; les 7 `.terraform.lock.hcl` sont suivis
  par git (aws figé à `6.53.0`) — _evidence : `documentation/terraform/observability/providers.tf:1-9`, `documentation/terraform/ingestion/providers.tf:1-24`._
- **`fmt` propre & `validate` OK sur les 7 modules** — `terraform fmt -check -recursive` = 0 ;
  `terraform validate -backend=false` = « Success » pour chaque module — _evidence : exécution locale (init `-backend=false` en `TF_DATA_DIR` temporaire, read-only)._
- **`for_each` piloté par la donnée** — runtime/logs instanciés par agent depuis `agents.json`
  (clés stables), pas d'indexation fragile — _evidence : `documentation/terraform/runtime/main.tf:4`, `documentation/terraform/runtime/logs.tf:3`._
- **État non committé + `.gitignore` correct** — aucun `*.tfstate` suivi ; `**/.terraform/*`,
  `*.tfstate*`, `*.tfplan`, `terraform/**/build/` ignorés — _evidence : `documentation/.gitignore:1-7`._
- **`ignore_changes` délibéré** sur les valeurs de secrets gérées hors IaC, et `count`
  garde-fou cohérent (`[0]` toujours protégé par la même condition, splat `[*]`) — _evidence :
  `documentation/terraform/security/main.tf:38`, `documentation/terraform/observability/main.tf:21`._
- **Dépendances explicites** là où nécessaire (chaînage des `awscc_logs_delivery`, `depends_on`
  Lambda→log group→policy, `precondition`) — _evidence : `documentation/terraform/ingestion/main.tf` (Lambda `depends_on`), `documentation/terraform/runtime/build.tf:3`._
- **`default_tags` + nommage cohérent** via `local.name = "${project}-${env}"` et
  `role_name_prefix` (guardrail org) sur 6 modules — _evidence : `documentation/terraform/ecr/providers.tf:20-27`._

## Faiblesses / Findings

### [Critical] TF-F1 — État S3 partagé **sans verrouillage**
- **Evidence :** blocs `backend "s3"` sans `use_lockfile` ni `dynamodb_table` dans les 7 modules,
  ex. `documentation/terraform/observability/providers.tf:11-16` ; le seul `aws_dynamodb_table`
  du projet est la table d'idempotence applicative `documentation/terraform/security/main.tf:57`
  (clé `pk`, TTL) — **ce n'est pas un verrou d'état**. Grep global : aucun `use_lockfile`,
  aucun `dynamodb_table`.
- **Impact :** deux `apply` concurrents (2 opérateurs, ou opérateur + futur pipeline) sur le
  même état peuvent écrire simultanément et **corrompre l'état** ou provoquer des écrasements
  silencieux (last-writer-wins). Pas de garde-fou `terraform force-unlock`, pas de détection de
  contention. Sur un socle multi-module déployé manuellement, le risque est réel dès qu'une
  deuxième personne (ou la CI future) intervient. Verrouillage explicitement exigé par le
  critère TF-02 et par les [pratiques recommandées HashiCorp pour le backend S3](https://developer.hashicorp.com/terraform/language/backend/s3).
- **Recommendation :** activer le verrouillage sur tous les backends `s3` avant tout usage
  partagé/CI.
- **Alternative solution :**
  - **Option A — verrouillage natif S3 (`use_lockfile = true`).** Ajouter `use_lockfile = true`
    dans chaque bloc `backend "s3"` ; Terraform pose un objet `.tflock` à côté de l'état,
    aucune infra supplémentaire.
    - _Pros :_ zéro ressource additionnelle (pas de table DynamoDB à créer/facturer/gérer) ;
      une seule ligne par module ; aligné sur la direction officielle HashiCorp (DynamoDB locking
      déprécié).
    - _Cons :_ **nécessite Terraform ≥ 1.10** ; or `required_version = ">= 1.6.0"` autorise
      encore des exécutants 1.6–1.9 qui ignoreraient silencieusement le verrou → il faut
      **relever `required_version` à `>= 1.10.0`** dans les 7 modules (le poste local est déjà en
      1.15.7, donc sans impact opérationnel ici).
    - _Effort :_ S (7 blocs backend + 7 `required_version`, puis `terraform init -reconfigure`).
    - _Impact cross-pilier :_ Fiabilité + (plus de corruption concurrente) ; Coût neutre.
  - **Option B — verrou DynamoDB classique.** Créer une table de verrou dédiée (clé `LockID`)
    dans `bootstrap`, puis `dynamodb_table = "<table>"` dans chaque backend.
    - _Pros :_ compatible dès Terraform 1.6 (pas de bump de version requis) ; pattern éprouvé,
      largement documenté.
    - _Cons :_ une ressource à provisionner/facturer (PAY_PER_REQUEST, coût négligeable mais non
      nul) ; la table doit exister **avant** `init` des autres modules (ordre bootstrap) ;
      approche que HashiCorp pousse désormais à remplacer par `use_lockfile`.
    - _Effort :_ M (table + policy S3/Dynamo côté rôle de déploiement + 7 backends).
    - _Impact cross-pilier :_ Fiabilité + ; Coût +/− (une table de plus) ; Opérabilité − (ordre
      de bootstrap plus contraint).
  - _Reco :_ **Option A** (le poste est déjà ≥ 1.10 ; solution la plus légère et pérenne), en
    relevant `required_version`.

### [Medium] TF-F2 — Nom du bucket d'état (avec account id + région) codé en dur dans 7 `providers.tf`
- **Evidence :** `bucket = "amzn-agent-technical-doc-statetf-375039967495-eu-central-1"` répété
  dans chaque backend, ex. `documentation/terraform/observability/providers.tf:12`,
  `documentation/terraform/ecr/providers.tf:13` ; `region = "eu-central-1"` codé en dur également.
- **Impact :** le compte `375039967495` et la région sont figés dans 7 fichiers versionnés.
  Un changement de compte/région impose une édition manuelle multi-fichiers (le fait est documenté
  dans `documentation/terraform/shared.tfvars:5-9`). Les blocs `backend` **ne peuvent pas**
  référencer de variables — c'est une contrainte Terraform, d'où une atténuation partielle — mais
  la [configuration partielle de backend](https://developer.hashicorp.com/terraform/language/backend#partial-configuration)
  (`terraform init -backend-config=...`) permet précisément d'externaliser ces valeurs.
- **Recommendation :** vider les valeurs des blocs `backend "s3"` et les fournir via
  `-backend-config=backend.hcl` (ou variables d'env `TF_...`), un fichier par compte/région.
  Ailleurs le code est propre : `account_id` vient de `data.aws_caller_identity` et la région de
  `var.aws_region` (ex. `documentation/terraform/roles/data.tf`, `bootstrap/main.tf:31`), et
  `us-east-1` pour le WAF CLOUDFRONT est une contrainte AWS légitime (`ingestion/waf.tf`).
- **Alternative solution :** _None — le backend partiel est la bonne pratique standard ; pas
  d'alternative structurelle nécessaire, effort S._

### [Medium] TF-F3 — Aucun `prevent_destroy` sur les ressources à état critique
- **Evidence :** grep global `prevent_destroy` = 0 occurrence. Ressources concernées : bucket
  d'état `documentation/terraform/bootstrap/main.tf` (`aws_s3_bucket.state`), table d'idempotence
  `documentation/terraform/security/main.tf:57`, secrets `documentation/terraform/security/main.tf:19,44`.
- **Impact :** un `terraform destroy` mal ciblé (ou un remplacement forcé) sur `bootstrap`
  détruirait le **bucket d'état de tout le socle** ; sur `security`, la table d'idempotence
  (dédup des runs) et les secrets. Pas de garde-fou déclaratif. `point_in_time_recovery` est
  activé sur la table (`security/main.tf`), ce qui limite la perte de données, mais pas la
  suppression accidentelle de la ressource.
- **Recommendation :** ajouter `lifecycle { prevent_destroy = true }` sur le bucket d'état, la
  table d'idempotence et les secrets. Assumé pour un POC, mais bon marché et à haute valeur.
- **Alternative solution :** _None — garde-fou déclaratif standard, effort S._

### [Low] TF-F4 — Module `security` sans `default_tags` : secrets et DynamoDB non tagués
- **Evidence :** `documentation/terraform/security/providers.tf:20-24` — bloc `default_tags`
  retiré ; commentaire justifiant par `kms:TagResource` sur la **CMK**… or la CMK a été retirée
  (`security/main.tf` — clés gérées AWS). Le contournement est donc **obsolète** et laisse les
  secrets + la table d'idempotence sans aucun tag `Project/Env/Module`.
- **Impact :** incohérence de tagging (6 modules tagués, 1 non) → FinOps/inventaire/traçabilité
  dégradés sur des ressources sensibles. Faible mais réel.
- **Recommendation :** ré-introduire `default_tags` dans `security/providers.tf` (la CMK n'existant
  plus, l'appel `kms:TagResource` problématique n'a plus lieu ; vérifier que le rôle porte
  `secretsmanager:TagResource` / tag DynamoDB — a priori oui).
- **Alternative solution :** _None — effort S._

### [Low] TF-F5 — Aucune CI IaC (fmt/validate/plan, tflint/checkov) ni pre-commit
- **Evidence :** aucun `.github/workflows`, CodeBuild/CodePipeline ni hook pre-commit
  (recherche `find` sur le repo : aucun fichier de workflow/CI). Déploiement Terraform manuel
  multi-module (`shared.tfvars`, `-var-file`).
- **Impact :** `fmt`/`validate` passent aujourd'hui manuellement mais rien ne les **garantit** à
  chaque changement ; pas de scan sécurité IaC (tflint/checkov/tfsec absents du poste également).
  Régressions de style/validité/sécurité possibles sans détection.
- **Recommendation :** ajouter un workflow CI minimal (`fmt -check`, `validate -backend=false`
  par module, `plan` en lecture seule) et idéalement `tflint`/`checkov` ; à défaut, un
  `.pre-commit-config` local.
- **Alternative solution :** _None (P2) — le critère est conditionné à l'existence d'un pipeline ;
  ici l'absence de tout gate automatisé est le point à corriger, effort M._

### [Low] TF-F6 — Variables sans `validation`, quelques descriptions manquantes
- **Evidence :** grep global `validation {` = 0. Variables `state_bucket` sans `description`
  (défaut `null`, absorbantes) dans `bootstrap/variables.tf`, `ecr/variables.tf`,
  `security/variables.tf`. Outputs `webhook_function_name` / `worker_function_name` sans
  `description` (`documentation/terraform/ingestion/outputs.tf`).
- **Impact :** hygiène. Typage et defaults sont solides, la plupart des variables/outputs sont
  richement documentés ; mais aucune `validation` d'entrée (ex. format `allowed_repositories`,
  bornes de timeouts) et quelques métadonnées manquent.
- **Recommendation :** ajouter des blocs `validation` sur les entrées à risque (listes de dépôts,
  seuils numériques) et compléter les `description` manquantes.
- **Alternative solution :** _None — effort S._

### [Low] TF-F7 — Pas d'`assume_role` de déploiement à moindre privilège au niveau provider
- **Evidence :** les blocs `provider "aws"` ne configurent que `region` + `default_tags`, sans
  `assume_role` (grep `assume_role` sur les `providers.tf` = 0) ; le déploiement s'appuie sur
  l'identité ambiante (SSO `AWSReservedSSO_NewSysOps`, rôle large).
- **Impact :** **aucun credential longue durée** dans le code (bon point — SSO éphémère), mais
  l'identité de déploiement n'est pas contrainte au niveau IaC ; toute personne portant le rôle
  SSO large peut appliquer. Séparation des privilèges de déploiement non matérialisée.
- **Recommendation :** définir un rôle de déploiement dédié à moindre privilège et
  `provider "aws" { assume_role { role_arn = ... } }` (paramétrable par `var`), sans introduire de
  clés statiques.
- **Alternative solution :** _None — effort M ; dépend de la gouvernance IAM org._

## Grille de critères
| id | critère | verdict | evidence |
|----|---------|---------|----------|
| TF-01 | Disposition standard des modules, composable | Met | `documentation/terraform/roles/data.tf:3`, `documentation/terraform/runtime/main.tf:4` |
| TF-02 | État distant **AVEC verrouillage** ; non committé ; segmentation | Partial | `documentation/terraform/observability/providers.tf:11-16` (remote+encrypt+segmenté, **pas de lock**), `documentation/.gitignore:1-7` |
| TF-03 | Contraintes de version épinglées ; lock committé | Met | `documentation/terraform/observability/providers.tf:1-9`, 7×`.terraform.lock.hcl` suivis |
| TF-04 | Variables typées/décrites/validées ; defaults sains ; pas d'inutilisées | Partial | `documentation/terraform/observability/variables.tf` (typées/décrites), **aucun `validation {}`**, `bootstrap/variables.tf:18` (state_bucket sans desc) |
| TF-05 | Outputs documentés ; secrets `sensitive` ; pas de secret en clair | Met | `documentation/terraform/security/main.tf:70-95` (ARN only), `ingestion/outputs.tf` (2 outputs sans desc — mineur) |
| TF-06 | `terraform fmt` propre & `validate` passe | Met | exécution locale : fmt=0, validate « Success » sur 7 modules |
| TF-07 | Pas d'account id/région/ARN codés en dur là où var/data conviennent | Partial | `documentation/terraform/observability/providers.tf:12` (bucket+account id+région en dur), reste propre (`bootstrap/main.tf:31`) |
| TF-08 | DRY via modules/`for_each` ; copie-coller minimal | Met | `documentation/terraform/runtime/logs.tf:3`, `runtime/main.tf:4` (for_each) ; boilerplate provider/remote_state répété (structurel) |
| TF-09 | `count`/`for_each` corrects ; pas d'indexation fragile | Met | `documentation/terraform/observability/main.tf:34,39,21` (count gardé + splat) |
| TF-10 | Dépendances explicites où nécessaire | Met | `documentation/terraform/runtime/build.tf:3`, `runtime/logs.tf` (chaînage), `ingestion/main.tf` (Lambda depends_on) |
| TF-11 | `lifecycle`/`prevent_destroy`/`ignore_changes` délibérés sur ressources à état | Partial | `documentation/terraform/security/main.tf:38` (ignore_changes OK) mais **aucun `prevent_destroy`** (bucket d'état, table, secrets) |
| TF-12 | Tagging via `default_tags`/locals ; nommage cohérent | Partial | `documentation/terraform/ecr/providers.tf:20-27` (OK 6 modules) ; `security/providers.tf:20-24` (default_tags retiré → security non tagué) |
| TF-13 | `assume-role` provider à moindre privilège ; pas de creds longue durée | Partial | pas de creds statiques (SSO) — bon ; **aucun `assume_role`** dans les `providers.tf` |
| TF-14 | Checks CI IaC (fmt/validate/plan, tflint/checkov) si pipeline | Missing | aucun `.github/workflows`/CodeBuild/pre-commit (recherche repo) |

## Améliorations priorisées
| priorité | action | effort |
|----------|--------|--------|
| P0 | Activer le verrouillage d'état : `use_lockfile = true` + `required_version >= 1.10.0` sur les 7 backends (ou table DynamoDB si maintien ≥1.6) — **libère le plafonnement global** (TF-F1) | S |
| P1 | Ajouter `prevent_destroy` sur bucket d'état, table d'idempotence et secrets (TF-F3) | S |
| P1 | Externaliser le backend via `-backend-config` (account id/région hors code) (TF-F2) | S |
| P2 | Rétablir `default_tags` dans `security` (workaround CMK obsolète) (TF-F4) | S |
| P2 | Workflow CI minimal : `fmt -check` + `validate -backend=false` + `plan` (+ tflint/checkov) (TF-F5) | M |
| P3 | Blocs `validation` sur entrées à risque + descriptions manquantes (TF-F6) | S |
| P3 | Rôle de déploiement dédié + `assume_role` provider (TF-F7) | M |

## Notes & hypothèses
- **Audit statique** : `terraform fmt -check -recursive` et `terraform validate -backend=false`
  ont été exécutés en lecture seule (init `-backend=false` dans un `TF_DATA_DIR` temporaire, aucune
  écriture vers l'état distant, aucun `plan`/`apply`/`import`). Terraform local : v1.15.7.
- **Coverage 95 %** : les 14 critères ont été évalués sur lecture intégrale des 7 modules + `fmt`/`validate`.
  Non vérifiable en statique : l'exécution réelle du verrou (inexistant), le comportement en apply concurrent.
- **Contrainte org intégrée** : la désactivation de CloudTrail (`observability/terraform.tfvars:8`
  `enable_cloudtrail = false`) est un **override d'environnement correct** (trail géré au niveau org,
  Deny explicite `cloudtrail:*`), **non pénalisé** ici. De même, l'absence de CMK et le retrait de
  `default_tags` dans `security` découlent du Deny org `kms:CreateKey` — mais ce dernier est désormais
  **obsolète** (CMK retirée) et redevient corrigeable (TF-F4).
- **Plafonnement** : TF-F1 (Critical) plafonne la **maturité globale** de l'audit à 2/5 tant qu'il
  reste ouvert (règle §5 du barème). Le score/ maturité **de ce pilier** (74/3) reflète la grille de
  critères ; le plafonnement s'applique à l'agrégat global, à énoncer explicitement par l'orchestrateur.
