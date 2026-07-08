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
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
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
  alarm_actions       = var.alarm_actions
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
  alarm_actions       = var.alarm_actions
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
          title  = "Worker — durée d'invocation (proxy durée de run)",
          region = var.aws_region,
          view   = "timeSeries",
          stat   = "Average",
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", local.worker_fn]
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
      }
    ]
  })
}

output "dashboard_name" {
  value       = aws_cloudwatch_dashboard.main.dashboard_name
  description = "Nom du dashboard CloudWatch"
}
