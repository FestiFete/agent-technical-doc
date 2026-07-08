data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  name       = "${var.project_name}-${var.environment}"
}

# ============================================================================
# KMS CMK — chiffre les secrets, la file SQS, la table DynamoDB et les logs.
# ============================================================================
resource "aws_kms_key" "main" {
  description             = "CMK agent-technical-doc (${var.environment})"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccount"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.aws_region}.amazonaws.com" }
        Action = [
          "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
          "kms:GenerateDataKey*", "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:*"
          }
        }
      }
    ]
  })

  tags = { Name = "${local.name}-cmk" }
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}

# ============================================================================
# Secrets Manager — token GitHub (PAT) + secret HMAC du webhook.
# Les valeurs sont posées hors Terraform (placeholders + ignore_changes).
# ============================================================================
resource "aws_secretsmanager_secret" "github_token" {
  name        = "${local.name}-github-token"
  description = "PAT GitHub (contents:write + pull_requests:write) pour agent-technical-doc"
  kms_key_id  = aws_kms_key.main.arn
}

resource "aws_secretsmanager_secret_version" "github_token" {
  secret_id     = aws_secretsmanager_secret.github_token.id
  secret_string = jsonencode({ token = "REPLACE_ME" })

  lifecycle {
    ignore_changes = [secret_string] # valeur gérée hors IaC (rotation manuelle POC)
  }
}

resource "aws_secretsmanager_secret" "webhook_hmac" {
  name        = "${local.name}-webhook-hmac"
  description = "Secret HMAC de validation des webhooks GitHub (X-Hub-Signature-256)"
  kms_key_id  = aws_kms_key.main.arn
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

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "${local.name}-idempotency" }
}

# ─── Outputs ─────────────────────────────────────────────────────────────────
output "kms_key_arn" {
  value       = aws_kms_key.main.arn
  description = "ARN de la CMK partagée"
}

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
