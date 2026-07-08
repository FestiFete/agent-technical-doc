# Observabilité du runtime : log groups + delivery API + métriques + alarmes.

resource "aws_cloudwatch_log_group" "runtime" {
  for_each = local.discovered_agents

  name              = "/aws/bedrock-agentcore/runtime/${each.key}-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = { Name = "${each.key}-runtime-logs", Agent = each.key }
}

resource "awscc_logs_delivery_source" "runtime_app_logs" {
  for_each = local.discovered_agents

  name         = "${each.key}-${var.environment}-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = awscc_bedrockagentcore_runtime.agents[each.key].agent_runtime_arn

  depends_on = [awscc_bedrockagentcore_runtime.agents]
}

resource "awscc_logs_delivery_source" "runtime_usage_logs" {
  for_each = local.discovered_agents

  name         = "${each.key}-${var.environment}-usage-logs"
  log_type     = "USAGE_LOGS"
  resource_arn = awscc_bedrockagentcore_runtime.agents[each.key].agent_runtime_arn

  depends_on = [awscc_bedrockagentcore_runtime.agents]
}

resource "awscc_logs_delivery_destination" "runtime_logs" {
  for_each = local.discovered_agents

  name                      = "${each.key}-${var.environment}-logs-dest"
  delivery_destination_type = "CWL"
  destination_resource_arn  = aws_cloudwatch_log_group.runtime[each.key].arn
}

resource "awscc_logs_delivery" "runtime_app_logs" {
  for_each = local.discovered_agents

  delivery_source_name     = awscc_logs_delivery_source.runtime_app_logs[each.key].name
  delivery_destination_arn = awscc_logs_delivery_destination.runtime_logs[each.key].arn

  depends_on = [
    awscc_logs_delivery_source.runtime_app_logs,
    awscc_logs_delivery_destination.runtime_logs
  ]
}

resource "awscc_logs_delivery" "runtime_usage_logs" {
  for_each = local.discovered_agents

  delivery_source_name     = awscc_logs_delivery_source.runtime_usage_logs[each.key].name
  delivery_destination_arn = awscc_logs_delivery_destination.runtime_logs[each.key].arn

  depends_on = [
    awscc_logs_delivery_source.runtime_usage_logs,
    awscc_logs_delivery_destination.runtime_logs,
    awscc_logs_delivery.runtime_app_logs
  ]
}

resource "aws_cloudwatch_log_metric_filter" "runtime_errors" {
  for_each = local.discovered_agents

  name           = "${var.project_name}-${each.key}-errors-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.runtime[each.key].name
  pattern        = "?ERROR ?Error ?Echec"

  metric_transformation {
    name      = "RuntimeErrors"
    namespace = "AgentCore/Runtime/${each.key}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "runtime_errors_alarm" {
  for_each = var.runtime_enable_alarms ? local.discovered_agents : {}

  alarm_name          = "${var.project_name}-${each.key}-errors-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RuntimeErrors"
  namespace           = "AgentCore/Runtime/${each.key}"
  period              = 300
  statistic           = "Sum"
  threshold           = var.runtime_error_threshold
  alarm_description   = "Trop d'erreurs runtime pour ${each.key}"
  treat_missing_data  = "notBreaching"

  tags = { Agent = each.key, Severity = "high" }
}
