data "terraform_remote_state" "ingestion" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "ingestion/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  name       = "${var.project_name}-${var.environment}"
  webhook_fn = data.terraform_remote_state.ingestion.outputs.webhook_function_name
  worker_fn  = data.terraform_remote_state.ingestion.outputs.worker_function_name
  dlq_name   = "${local.name}-dlq"
  queue_name = "${local.name}-queue"
  runtime_ns = "AgentCore/Runtime/${var.agent_name}"

  # Cibles de notification des alarmes (REL-F1) : le topic créé ici + tout ARN
  # additionnel fourni par l'appelant. aws_sns_topic.alarms[*].arn vaut [] si
  # var.create_alarm_topic = false, donc les alarmes restent valides sans topic.
  alarm_targets = concat(var.alarm_actions, aws_sns_topic.alarms[*].arn)
}

# ============================================================================
# Notification des alarmes — topic SNS (REL-F1)
# ============================================================================
# Sans destination, toutes les alarmes se déclenchaient dans le vide (alarm_actions
# défaut []). Ce topic centralise la notification ; un abonnement email optionnel
# est créé si var.alarm_email est renseignée.
# Note : pas de chiffrement KMS sur le topic — un topic SSE avec la clé gérée AWS
# (alias/aws/sns) empêche le service CloudWatch d'y publier (impossible d'accorder
# le principal au key policy d'une clé managée), ce qui casserait la notification.
# Cohérent avec le contournement CMK documenté ailleurs (DENY kms:CreateKey).
resource "aws_sns_topic" "alarms" {
  count = var.create_alarm_topic ? 1 : 0
  name  = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "alarms_email" {
  count     = var.create_alarm_topic && var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ============================================================================
# Alarmes
# ============================================================================

# 1. Messages en DLQ (échecs non rejouables) — signal fort à investiguer.
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${local.name}-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = local.dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Des messages sont en DLQ (runs de documentation en échec)."
  alarm_actions       = local.alarm_targets
  ok_actions          = local.alarm_targets
}

# 2. Erreurs de la Lambda worker.
resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${local.name}-worker-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = local.worker_fn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Trop d'erreurs de la Lambda worker."
  alarm_actions       = local.alarm_targets
}

# 3. Erreurs de la Lambda webhook.
resource "aws_cloudwatch_metric_alarm" "webhook_errors" {
  alarm_name          = "${local.name}-webhook-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = local.webhook_fn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Trop d'erreurs de la Lambda webhook."
  alarm_actions       = local.alarm_targets
}

# 4. Stall silencieux du pipeline (REL-F1) — le plus vieux message de la file
# principale dépasse le seuil : le poller SQS→worker ne consomme plus (perte
# d'IAM sqs:*, worker en échec systématique, etc.). Ni worker_errors ni
# dlq_not_empty ne couvrent ce cas (le worker n'est jamais invoqué, rien ne part
# en DLQ), d'où cette alarme dédiée sur l'âge du message.
resource "aws_cloudwatch_metric_alarm" "main_queue_stalled" {
  alarm_name          = "${local.name}-main-queue-stalled"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = local.queue_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.queue_max_age_seconds
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Le plus vieux message de la file principale dépasse ${var.queue_max_age_seconds}s : le pipeline SQS vers worker ne consomme plus (stall silencieux)."
  alarm_actions       = local.alarm_targets
  ok_actions          = local.alarm_targets
}

# ============================================================================
# Dashboard agrégé
# ============================================================================
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2,
        properties = {
          markdown = "# ${var.project_name} (${var.environment}) — agent de documentation technique\nIngestion webhook → SQS → worker → AgentCore. Tracer un run via son `correlation_id` (X-GitHub-Delivery) dans les 3 groupes de logs."
        }
      },
      {
        type = "metric", x = 0, y = 2, width = 12, height = 6,
        properties = {
          title  = "Ingestion — invocations Lambda",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", local.webhook_fn, { label = "webhook" }],
            ["AWS/Lambda", "Invocations", "FunctionName", local.worker_fn, { label = "worker" }]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 2, width = 12, height = 6,
        properties = {
          title  = "Ingestion — erreurs Lambda",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", local.webhook_fn, { label = "webhook" }],
            ["AWS/Lambda", "Errors", "FunctionName", local.worker_fn, { label = "worker" }]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 8, width = 12, height = 6,
        properties = {
          title  = "SQS — file principale vs DLQ",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", local.queue_name, { label = "queue" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", local.dlq_name, { label = "DLQ" }]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 8, width = 12, height = 6,
        properties = {
          title  = "Durée de run — EMF (ms)",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            ["AgentTechnicalDoc", "DurationMs", "Agent", var.agent_name, "Outcome", "complete", { stat = "Average", label = "moy. (complete)" }],
            ["AgentTechnicalDoc", "DurationMs", "Agent", var.agent_name, "Outcome", "complete", { stat = "p90", label = "p90 (complete)" }],
            ["AgentTechnicalDoc", "DurationMs", "Agent", var.agent_name, "Outcome", "failed", { stat = "Average", label = "moy. (failed)" }]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 14, width = 12, height = 6,
        properties = {
          title  = "Runtime AgentCore — erreurs applicatives",
          region = var.aws_region,
          view   = "timeSeries",
          metrics = [
            [local.runtime_ns, "RuntimeErrors", { label = "erreurs runtime" }]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 14, width = 12, height = 6,
        properties = {
          title  = "Runs par outcome (EMF)",
          region = var.aws_region,
          view   = "timeSeries",
          stat   = "Sum",
          metrics = [
            ["AgentTechnicalDoc", "Runs", "Agent", var.agent_name, "Outcome", "complete", { label = "complete" }],
            ["...", "Outcome", "failed", { label = "failed" }],
            ["...", "Outcome", "skipped_fork", { label = "skipped_fork" }],
            ["...", "Outcome", "skipped_duplicate", { label = "skipped_duplicate" }]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 20, width = 12, height = 6,
        properties = {
          title  = "SQS — âge du plus vieux message (stall)",
          region = var.aws_region,
          view   = "timeSeries",
          stat   = "Maximum",
          annotations = {
            horizontal = [{ label = "seuil stall", value = var.queue_max_age_seconds }]
          },
          metrics = [
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", local.queue_name, { label = "queue (s)" }],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", local.dlq_name, { label = "DLQ (s)" }]
          ]
        }
      }
    ]
  })
}

output "dashboard_name" {
  value       = aws_cloudwatch_dashboard.main.dashboard_name
  description = "Nom du dashboard CloudWatch"
}

output "alarm_topic_arn" {
  value       = var.create_alarm_topic ? aws_sns_topic.alarms[0].arn : null
  description = "ARN du topic SNS des alarmes (null si non créé). Abonner email/Slack/PagerDuty ici."
}
