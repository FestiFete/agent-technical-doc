output "runtime_arns" {
  description = "ARNs des runtimes AgentCore par agent"
  value = {
    for name, rt in awscc_bedrockagentcore_runtime.agents : name => rt.agent_runtime_arn
  }
}

output "runtime_ids" {
  description = "IDs des runtimes AgentCore par agent"
  value = {
    for name, rt in awscc_bedrockagentcore_runtime.agents : name => rt.agent_runtime_id
  }
}

output "doc_agent_runtime_arn" {
  description = "ARN du runtime agent-technical-doc (consommé par le module ingestion)"
  value       = try(awscc_bedrockagentcore_runtime.agents["agent-technical-doc"].agent_runtime_arn, "")
}

output "log_group_names" {
  description = "Noms des log groups runtime par agent"
  value = {
    for name, lg in aws_cloudwatch_log_group.runtime : name => lg.name
  }
}
