# ============================================================================
# Contrôles détectifs account-wide (SEC-F3, audit/20260721-154651/02-security.md) :
# piste d'audit CloudTrail centralisée, alarmes sur les changements IAM et les
# accès Secrets Manager, et GuardDuty en détection continue légère.
#
# Ces contrôles sont account-wide, pas spécifiques à un composant du pipeline
# webhook → SQS → worker → runtime — c'est pourquoi ils vivent dans le module
# observability plutôt que ingestion/security. Désactivables individuellement
# (var.enable_cloudtrail / var.enable_guardduty) si l'organisation gère déjà
# un trail ou un détecteur GuardDuty au niveau compte/org (GuardDuty n'autorise
# qu'un seul détecteur par compte et par région — vérifier avant d'activer :
# `aws guardduty list-detectors`, `aws cloudtrail describe-trails`).
#
# Chiffrement au repos via clé AWS-managée (aws:kms géré par S3), pas de CMK —
# cohérent avec le contournement documenté ailleurs dans le projet (SEC-07,
# DENY compte sur kms:CreateKey), pas un nouvel écart introduit ici.
# ============================================================================

data "aws_caller_identity" "current" {}

locals {
  cloudtrail_bucket_name = "amzn-${var.project_name}-cloudtrail-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
}

# ─── S3 : destination durable des logs CloudTrail ───────────────────────────
resource "aws_s3_bucket" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = local.cloudtrail_bucket_name
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  count                   = var.enable_cloudtrail ? 1 : 0
  bucket                  = aws_s3_bucket.cloudtrail[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id

  rule {
    id     = "expire-old-trail-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.cloudtrail_s3_retention_days
    }
  }
}

data "aws_iam_policy_document" "cloudtrail_bucket" {
  count = var.enable_cloudtrail ? 1 : 0

  statement {
    sid     = "AWSCloudTrailAclCheck"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = [aws_s3_bucket.cloudtrail[0].arn]
  }

  statement {
    sid     = "AWSCloudTrailWrite"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.cloudtrail[0].arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  policy = data.aws_iam_policy_document.cloudtrail_bucket[0].json
}

# ─── CloudWatch Logs : diffusion quasi temps-réel, base des metric filters ──
resource "aws_cloudwatch_log_group" "cloudtrail" {
  count             = var.enable_cloudtrail ? 1 : 0
  name              = "/aws/cloudtrail/${local.name}"
  retention_in_days = var.cloudtrail_log_retention_days
}

data "aws_iam_policy_document" "cloudtrail_to_cw_assume" {
  count = var.enable_cloudtrail ? 1 : 0
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cloudtrail_to_cw" {
  count              = var.enable_cloudtrail ? 1 : 0
  name               = "${var.role_name_prefix}${local.name}-cloudtrail-to-cw"
  assume_role_policy = data.aws_iam_policy_document.cloudtrail_to_cw_assume[0].json
}

data "aws_iam_policy_document" "cloudtrail_to_cw_policy" {
  count = var.enable_cloudtrail ? 1 : 0
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.cloudtrail[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "cloudtrail_to_cw" {
  count  = var.enable_cloudtrail ? 1 : 0
  name   = "${local.name}-cloudtrail-to-cw-policy"
  role   = aws_iam_role.cloudtrail_to_cw[0].id
  policy = data.aws_iam_policy_document.cloudtrail_to_cw_policy[0].json
}

# ─── Le trail lui-même (multi-région, événements globaux IAM inclus) ────────
resource "aws_cloudtrail" "account" {
  count                         = var.enable_cloudtrail ? 1 : 0
  name                          = "${local.name}-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail[0].id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.cloudtrail[0].arn}:*"
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_to_cw[0].arn

  depends_on = [aws_s3_bucket_policy.cloudtrail, aws_iam_role_policy.cloudtrail_to_cw]
}

# ─── Metric filter + alarme : changement de politique/rôle IAM ──────────────
# Rare et normalement délibéré → seuil bas (tout changement mérite un regard).
resource "aws_cloudwatch_log_metric_filter" "iam_changes" {
  count          = var.enable_cloudtrail ? 1 : 0
  name           = "${local.name}-iam-policy-changes"
  log_group_name = aws_cloudwatch_log_group.cloudtrail[0].name
  pattern        = "{ ($.eventSource = \"iam.amazonaws.com\") && (($.eventName = \"Put*Policy\") || ($.eventName = \"Attach*\") || ($.eventName = \"Detach*\") || ($.eventName = \"Create*\") || ($.eventName = \"Delete*\") || ($.eventName = \"Update*\")) }"

  metric_transformation {
    name      = "IAMPolicyChanges"
    namespace = "${local.name}/Security"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "iam_changes" {
  count               = var.enable_cloudtrail ? 1 : 0
  alarm_name          = "${local.name}-iam-policy-changed"
  namespace           = aws_cloudwatch_log_metric_filter.iam_changes[0].metric_transformation[0].namespace
  metric_name         = aws_cloudwatch_log_metric_filter.iam_changes[0].metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Une politique ou un rôle IAM a été modifié dans le compte (SEC-F3)."
  alarm_actions       = var.alarm_actions
}

# ─── Metric filter + alarme : accès Secrets Manager ─────────────────────────
# Fréquent et attendu ici (1 lecture par delivery webhook + 1 par run accepté)
# → seuil volumétrique (var.secrets_access_alarm_threshold), pas "≥1 accès",
# pour viser un pic anormal sans noyer l'alarme dans le trafic nominal.
resource "aws_cloudwatch_log_metric_filter" "secrets_access" {
  count          = var.enable_cloudtrail ? 1 : 0
  name           = "${local.name}-secrets-access"
  log_group_name = aws_cloudwatch_log_group.cloudtrail[0].name
  pattern        = "{ ($.eventSource = \"secretsmanager.amazonaws.com\") && ($.eventName = \"GetSecretValue\") }"

  metric_transformation {
    name      = "SecretsManagerAccess"
    namespace = "${local.name}/Security"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "secrets_access" {
  count               = var.enable_cloudtrail ? 1 : 0
  alarm_name          = "${local.name}-secrets-access-spike"
  namespace           = aws_cloudwatch_log_metric_filter.secrets_access[0].metric_transformation[0].namespace
  metric_name         = aws_cloudwatch_log_metric_filter.secrets_access[0].metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.secrets_access_alarm_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Volume d'appels secretsmanager:GetSecretValue au-delà du seuil attendu (SEC-F3)."
  alarm_actions       = var.alarm_actions
}

# ─── GuardDuty : détection continue (comportement anormal, credentials compromis) ──
resource "aws_guardduty_detector" "this" {
  count  = var.enable_guardduty ? 1 : 0
  enable = true
}

# ─── Outputs ─────────────────────────────────────────────────────────────────
output "cloudtrail_bucket_name" {
  value       = var.enable_cloudtrail ? aws_s3_bucket.cloudtrail[0].bucket : null
  description = "Bucket S3 des logs CloudTrail bruts"
}

output "cloudtrail_arn" {
  value       = var.enable_cloudtrail ? aws_cloudtrail.account[0].arn : null
  description = "ARN du trail CloudTrail"
}

output "guardduty_detector_id" {
  value       = var.enable_guardduty ? aws_guardduty_detector.this[0].id : null
  description = "ID du détecteur GuardDuty"
}
