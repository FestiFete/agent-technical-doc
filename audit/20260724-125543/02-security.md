# Sécurité — Audit

**Score:** 89/100  **Maturité:** 4 (Managed)  **Couverture:** 95%  **Confiance:** medium
**Applicable:** oui

## Charte & périmètre

Ce pilier évalue la posture de sécurité du projet `agent-technical-doc` : IAM au
moindre privilège, gestion des secrets, chiffrement au repos et en transit,
segmentation réseau et exposition, authentification/autorisation des surfaces
exposées, validation d'entrée et protection anti-injection (dont prompt-injection
et SSRF), contrôles détectifs, gestion des vulnérabilités des dépendances, non
journalisation des secrets, authenticité des webhooks, sécurité du CI/CD et
confinement du rayon d'explosion.

Audit **statique** (code/IaC uniquement, aucun appel AWS live). Le chiffrement
effectif, l'activation réelle des alarmes et l'existence d'un trail org-wide ne
sont pas vérifiables ici — jugés sur l'IaC.

**Contrainte organisationnelle intégrée** (cf. context pack) : le rôle SSO de
déploiement porte des **Deny explicites au niveau org** sur CloudTrail
(`CreateTrail`/`DescribeTrails`), `kms:CreateKey` et probablement GuardDuty. Ces
services sont **centralisés au niveau org**. Le projet fournit l'IaC togglable et
désactive correctement le trail local (`enable_cloudtrail = false`). Cette
désactivation **n'est pas** pénalisée : elle reflète une adaptation correcte au
garde-fou org. Les contrôles détectifs et la CMK sont jugés `Partial`
(présents/assumés au niveau org, non vérifiables en statique), pas `Missing`.

Ce pilier ne couvre pas : le verrou de state Terraform (→ Terraform), les
politiques de rétention/coût (→ Cost), la fiabilité DLQ/retry (→ Reliability).

## Points forts

- **Authentification multi-couches du webhook public** — vérification de l'en-tête
  d'origine CloudFront `X-Origin-Verify` en temps constant, PUIS signature HMAC
  `X-Hub-Signature-256` (`hmac.compare_digest`), avec message de rejet identique
  pour ne pas créer d'oracle. _evidence: `documentation/scripts/lambdas/webhook-receiver/handler.py:62`, `:82`, `:207`, `:214`_
- **Défense en profondeur en frontal** — CloudFront + WAFv2 (Core Rule Set, Known
  Bad Inputs, rate-based 2000/IP, taille de corps calibrée 128 Ko, fail-safe
  `oversize_handling=MATCH`) devant l'HTTP API, en plus du throttle API GW
  (10 rps/20 burst) et du quota anti-DoS par dépôt. _evidence: `documentation/terraform/ingestion/waf.tf:76`, `:120`, `:189`, `documentation/scripts/lambdas/webhook-receiver/handler.py:169`_
- **Moindre privilège & confinement du rayon d'explosion** — 3 rôles distincts
  scopés par ARN : le rôle webhook n'a **pas** accès au token GitHub ; le worker
  n'a que `InvokeAgentRuntime` sur des ARNs précis ; seul le runtime lit le token.
  _evidence: `documentation/terraform/ingestion/main.tf:60`, `:135`, `documentation/terraform/roles/main.tf:70`_
- **Authentification GitHub App à privilège réduit** — JWT RS256 → token
  d'installation court (~1 h), révocable, non lié à un utilisateur ; repli PAT.
  _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/github_auth.py:112`, `:170`_
- **Secrets en Secrets Manager, jamais en clair dans le code/state** — valeurs
  posées hors IaC (`ignore_changes`, placeholders `REPLACE_ME`) ; masquage
  systématique dans les logs (`mask_secrets`), journalisation des noms de clés
  uniquement. _evidence: `documentation/terraform/security/main.tf:35`, `:56`, `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:42`, `documentation/scripts/agents/agent-technical-doc/docagent/secrets.py:60`_
- **Anti prompt-injection appliqué par le code (pas par le prompt)** — cible de
  commit figée `docs/agent/**` avec anti-traversal (`normalize_output_path`),
  extraction tarball rejetant liens symboliques/durs et path traversal, LLM sans
  pouvoir d'écriture. _evidence: `documentation/scripts/agents/agent-technical-doc/docagent/paths.py:38`, `documentation/scripts/agents/agent-technical-doc/docagent/repo_reader.py:41`, `:55`_
- **Aucune exposition publique des data stores** — DynamoDB/SQS/Secrets non
  publics ; bucket CloudTrail (si activé) avec `public_access_block` complet.
  _evidence: `documentation/terraform/observability/cloudtrail.tf:52`_

## Faiblesses / Findings

### [Medium] SEC-F1 — Dépendances applicatives non figées et absence de scan de vulnérabilités
- **Evidence:** `documentation/scripts/agents/agent-technical-doc/requirements.txt:1-9` (`bedrock-agentcore>=0.1.0`, `strands-agents[otel]>=0.1.0`, `boto3>=1.34.0`, `pyjwt[crypto]>=2.8.0` — pins plancher `>=`, aucun `==` ni hash) ; aucun outil de scan (`trivy`/`checkov` absents, pas de `.github/workflows`, pas de `scan_on_push` ECR observé).
- **Impact:** builds non reproductibles ; introduction silencieuse d'une version
  vulnérable ou compromise (supply chain) à chaque build d'image ; aucune
  détection automatisée de CVE sur les dépendances ou l'image de conteneur.
- **Recommendation:** figer les versions (`==` + hashes via `pip-compile`/lock),
  activer `image_scanning_configuration { scan_on_push = true }` sur le repo ECR,
  et ajouter un scan de dépendances/image dans un futur pipeline.
- **Alternative solution:** _None nécessaire (Medium)_ — à défaut de pipeline,
  un scan `pip-audit`/`trivy fs` exécuté localement avant chaque `docker push`
  couvre l'essentiel. Effort S. Impact cross-pilier : Operational Excellence +,
  Maintainability +.

### [Low] SEC-F2 — Plancher TLS viewer faible via le certificat CloudFront par défaut
- **Evidence:** `documentation/terraform/ingestion/waf.tf:288` (`viewer_certificate { cloudfront_default_certificate = true }`) ; `viewer_protocol_policy = "https-only"` (`:277`) mais `cloudfront_default_certificate` impose `minimum_protocol_version = TLSv1` (non surchargeable).
- **Impact:** un client peut négocier TLSv1.0/1.1 côté viewer. En pratique GitHub
  émet en TLS 1.2+, le risque réel est faible, mais le plancher n'est pas conforme
  aux bonnes pratiques (TLS 1.2 minimum). Le trafic origine est déjà en TLSv1.2
  (`origin_ssl_protocols = ["TLSv1.2"]`, `:270`).
- **Recommendation:** utiliser un certificat ACM avec un domaine custom et
  `minimum_protocol_version = "TLSv1.2_2021"` sur le `viewer_certificate`.
- **Alternative solution:** _None — l'approche HTTPS-only est appropriée ; seul le
  plancher est à durcir, ce qui nécessite un certificat ACM (donc un domaine)._

### [Low] SEC-F3 — Couverture partielle des contrôles détectifs
- **Evidence:** `documentation/terraform/observability/cloudtrail.tf` (CloudTrail + metric filters IAM/Secrets + GuardDuty présents mais togglables) ; `documentation/terraform/observability/terraform.tfvars:8` (`enable_cloudtrail = false`) ; aucun `aws_config_*` ni `aws_securityhub_*` (grep vide).
- **Impact:** en dehors de CloudTrail (assumé org-wide) et GuardDuty (activé par
  défaut), pas d'AWS Config (conformité/dérive de configuration) ni Security Hub
  (agrégation de findings). Non vérifiable en statique côté org.
- **Recommendation:** confirmer la couverture CloudTrail/GuardDuty/Config/Security
  Hub au niveau org (hors périmètre de ce compte) ; documenter l'hypothèse.
- **Alternative solution:** _None — CloudTrail/GuardDuty sont gérés au niveau org
  (contrainte documentée) ; la désactivation locale n'est pas un défaut._

### [Low] SEC-F4 — Aucun contrôle de sécurité CI/CD (pas de pipeline)
- **Evidence:** absence de `.github/workflows`, de CodeBuild/CodePipeline (context pack) ; déploiement Terraform manuel multi-module, secrets posés à la main.
- **Impact:** pas d'artefacts signés, pas de branches protégées vérifiables, pas
  de gate de sécurité automatisé. Point positif : les secrets ne transitent par
  aucun pipeline (posés hors IaC dans Secrets Manager), donc pas de fuite CI/CD.
- **Recommendation:** à l'industrialisation, ajouter un pipeline avec branches
  protégées, scan IaC/déps, et signature d'image (cosign / ECR image signing).
- **Alternative solution:** _None nécessaire pour un POC — la gestion des secrets
  hors code est déjà correcte ; cross-ref Operational Excellence._

### [Info] SEC-F5 — Chiffrement au repos sans CMK (contrainte org)
- **Evidence:** `documentation/terraform/security/main.tf:14-17`, `:37`, `:70` (clés gérées AWS : `aws/secretsmanager`, DynamoDB AWS-owned, SSE-SQS `documentation/terraform/ingestion/main.tf:11`, `:22`).
- **Impact:** pas de rotation/contrôle de clé propre au projet ni d'isolation
  cryptographique par CMK. Accepté : `kms:CreateKey` en Deny org.
- **Recommendation:** rétablir des CMK (rotation annuelle, key policy scopée) avant
  passage en production, une fois les droits KMS obtenus.
- **Alternative solution:** _None — contrainte org documentée, chiffrement au repos
  bien présent via clés gérées AWS._

## Grille de critères
| id | critère | verdict | evidence |
|----|---------|---------|----------|
| SEC-01 | Moindre privilège IAM (pas de `*` injustifié) | Met | `documentation/terraform/roles/main.tf:36`, `:74`, `documentation/terraform/ingestion/main.tf:70`, `:150` (seuls `*` : `ecr:GetAuthorizationToken` requis par AWS, `PutMetricData` borné par condition `namespace`) |
| SEC-02 | Pas de secret long terme en code/state ; Secrets Manager/rôles | Met | `documentation/terraform/security/main.tf:35`, `:56`, `documentation/scripts/agents/agent-technical-doc/docagent/secrets.py:60` |
| SEC-03 | Chiffrement au repos sur tous les data stores | Met | `documentation/terraform/ingestion/main.tf:11`, `:22`, `documentation/terraform/security/main.tf:37`, `:70` |
| SEC-04 | Chiffrement en transit (TLS) imposé | Partial | `documentation/terraform/ingestion/waf.tf:270`, `:277`, `:288` (HTTPS-only imposé mais plancher viewer TLSv1 via cert par défaut — SEC-F2) |
| SEC-05 | Segmentation réseau & moindre exposition | Met | `documentation/terraform/ingestion/waf.tf:225`, `documentation/terraform/ingestion/main.tf:284` (endpoint public unique fronté WAF ; data stores accédés via IAM, pas de surface superflue) |
| SEC-06 | Pas d'exposition publique des data stores/surfaces admin | Met | `documentation/terraform/observability/cloudtrail.tf:52`, `documentation/terraform/security/main.tf:47` (DynamoDB/SQS/Secrets non publics) |
| SEC-07 | Usage & rotation de CMK KMS le cas échéant | Partial | `documentation/terraform/security/main.tf:14-17` (Deny org `kms:CreateKey` → clés gérées AWS, accepté) |
| SEC-08 | AuthN/AuthZ sur toutes les surfaces exposées | Met | `documentation/scripts/lambdas/webhook-receiver/handler.py:207`, `:214`, `:130`, `:135` (origin + HMAC + allowlist repo + author_association) |
| SEC-09 | Validation d'entrée / anti-injection (SSRF, prompt-injection) | Met | `documentation/scripts/agents/agent-technical-doc/docagent/paths.py:38`, `documentation/scripts/agents/agent-technical-doc/docagent/repo_reader.py:41`, `documentation/scripts/agents/agent-technical-doc/instructions.md:11` |
| SEC-10 | Contrôles détectifs (CloudTrail, Config, GuardDuty, Security Hub) | Partial | `documentation/terraform/observability/cloudtrail.tf`, `terraform.tfvars:8` (CloudTrail org-managed/désactivé local, GuardDuty on ; pas de Config/Security Hub) |
| SEC-11 | Gestion vuln. dépendances & images (pins, scan) | Partial | `documentation/scripts/agents/agent-technical-doc/requirements.txt:1-9` (pins plancher `>=`, pas de scan ; TF providers verrouillés `.terraform.lock.hcl`) |
| SEC-12 | Secrets non journalisés ; redaction PII | Met | `documentation/scripts/agents/agent-technical-doc/docagent/correlation.py:31`, `:42`, `documentation/scripts/agents/agent-technical-doc/docagent/secrets.py:60` |
| SEC-13 | Authenticité des webhooks (vérif. signature) | Met | `documentation/scripts/lambdas/webhook-receiver/handler.py:82`, `:214` (`hmac.compare_digest`) |
| SEC-14 | Sécurité dans le CI/CD (pas de fuite, branches protégées, artefacts signés) | Partial | Pas de pipeline (context pack) ; secrets hors code (positif) mais ni signature d'artefact ni gate — SEC-F4 |
| SEC-15 | Confinement du rayon d'explosion (rôles par service) | Met | `documentation/terraform/ingestion/main.tf:60`, `:135`, `documentation/terraform/roles/main.tf:19` (3 rôles distincts, webhook sans token) |

## Améliorations priorisées
| priorité | action | effort |
|----------|--------|--------|
| P1 | Figer les dépendances Python (`==` + hashes) et activer `scan_on_push` ECR (SEC-F1) | S |
| P2 | Certificat ACM + `minimum_protocol_version = TLSv1.2_2021` sur CloudFront (SEC-F2) | M |
| P2 | Documenter/valider la couverture org CloudTrail/GuardDuty/Config/Security Hub (SEC-F3) | S |
| P3 | Rétablir des CMK KMS avec rotation avant la prod, une fois les droits obtenus (SEC-F5) | M |
| P3 | À l'industrialisation : pipeline avec branches protégées, scan IaC/déps, signature d'image (SEC-F4) | L |

## Notes & hypothèses
- **Statique uniquement** : chiffrement effectif, alarmes actives et existence du
  trail org-wide non vérifiables (le rôle de déploiement ne peut même pas lire
  CloudTrail/GuardDuty — Deny org). Couverture ~95% de la grille.
- Aucun **finding Critical ou High** : la posture de sécurité est solide et
  multi-couches. Les écarts restants sont Medium/Low/Info et n'ouvrent aucune
  exposition exploitable, fuite de secret ou data store public-writable.
- Le secret `random_password.origin_verify` réside dans le state Terraform
  (S3) — défense en profondeur (l'HMAC reste requis), impact limité ; noté sous
  SEC-02 sans dégrader le verdict.
- Scanners `tflint`/`checkov`/`tfsec`/`trivy` absents (non installés, conformément
  aux consignes) : verdicts fondés sur l'analyse de code + lecture IaC.
- Contrainte org (CloudTrail/KMS/GuardDuty centralisés) intégrée : aucune pénalité
  sur la désactivation locale du trail.
