data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  name       = "${var.project_name}-${var.environment}"
}

# ============================================================================
# CMK KMS retirée : le rôle NewSysOps a un DENY explicite sur kms:CreateKey.
# Contournement POC → chiffrement au repos via clés gérées par AWS
# (aws/secretsmanager pour les secrets, clé AWS par défaut pour DynamoDB,
# SSE-SQS pour les files). À rétablir en CMK avant prod (droits KMS requis).
# ============================================================================

# ============================================================================
# Secrets Manager — authentification GitHub App (préférée) + secret HMAC webhook.
# App : {app_id, private_key (PEM), installation_id?}. Repli PAT possible :
# {token: "ghp_..."}. Les valeurs sont posées hors Terraform (ignore_changes).
# ============================================================================
resource "aws_secretsmanager_secret" "github_token" {
  name        = "${local.name}-github-token"
  description = "Auth GitHub App (app_id + private_key, permissions contents:write + pull_requests:write) pour agent-technical-doc — repli PAT supporté"
  # kms_key_id retiré → clé gérée AWS aws/secretsmanager (POC, pas de CMK).
}

resource "aws_secretsmanager_secret_version" "github_token" {
  secret_id = aws_secretsmanager_secret.github_token.id
  secret_string = jsonencode({
    app_id          = "REPLACE_ME"
    installation_id = "REPLACE_ME"
    private_key     = "REPLACE_ME"
  })

  lifecycle {
    ignore_changes = [secret_string] # valeur gérée hors IaC (rotation manuelle POC)
  }
}

resource "aws_secretsmanager_secret" "webhook_hmac" {
  name        = "${local.name}-webhook-hmac"
  description = "Secret HMAC de validation des webhooks GitHub (X-Hub-Signature-256)"
  # kms_key_id retiré → clé gérée AWS aws/secretsmanager (POC, pas de CMK).
}

resource "aws_secretsmanager_secret_version" "webhook_hmac" {
  secret_id     = aws_secretsmanager_secret.webhook_hmac.id
  secret_string = "REPLACE_ME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ============================================================================
# DynamoDB — table d'idempotence (clé repo#pr#sha), purge par TTL.
# ============================================================================
resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.name}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # server_side_encryption CMK retiré → chiffrement par défaut (clé AWS-owned).

  point_in_time_recovery {
    enabled = true
  }

  # tags retirés (cohérence avec le contournement KMS ; évite tout appel TagResource).
}

# ─── Outputs ─────────────────────────────────────────────────────────────────
output "github_token_secret_arn" {
  value       = aws_secretsmanager_secret.github_token.arn
  description = "ARN du secret contenant le token GitHub"
}

output "webhook_hmac_secret_arn" {
  value       = aws_secretsmanager_secret.webhook_hmac.arn
  description = "ARN du secret HMAC du webhook"
}

output "idempotency_table_name" {
  value       = aws_dynamodb_table.idempotency.name
  description = "Nom de la table DynamoDB d'idempotence"
}

output "idempotency_table_arn" {
  value       = aws_dynamodb_table.idempotency.arn
  description = "ARN de la table DynamoDB d'idempotence"
}

output "idempotency_ttl_days" {
  value       = var.idempotency_ttl_days
  description = "Rétention TTL des clés d'idempotence"
}
