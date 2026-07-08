# AgentCore Runtime — un par image d'agent (ici : agent-technical-doc).

resource "awscc_bedrockagentcore_runtime" "agents" {
  for_each = local.discovered_agents

  agent_runtime_name = substr(replace("${each.key}_${var.environment}", "-", "_"), 0, 48)
  description        = "AgentCore Runtime pour ${each.key}"
  role_arn           = local.runtime_execution_role_arn

  # Référence par digest : un nouveau build met à jour le runtime en place.
  agent_runtime_artifact = {
    container_configuration = {
      container_uri = "${local.ecr_repository_url}@${data.aws_ecr_image.agents[each.key].image_digest}"
    }
  }

  # PUBLIC : egress sortant requis pour l'API GitHub + Bedrock (analyse statique).
  network_configuration = {
    network_mode        = "PUBLIC"
    network_mode_config = null
  }

  lifecycle_configuration = {
    idle_runtime_session_timeout_in_seconds = each.value.idle_timeout
    max_lifetime_in_seconds                 = each.value.max_lifetime
  }

  # Variables d'env : agents.json + injections plateforme (secret, table, ...).
  environment_variables = merge(
    each.value.environment_variables,
    {
      GITHUB_TOKEN_SECRET_ARN = local.github_token_secret_arn
      IDEMPOTENCY_TABLE       = local.idempotency_table_name
    }
  )

  protocol_configuration   = each.value.protocol
  authorizer_configuration = null

  tags = {
    Name  = "${var.project_name}-${each.key}-${var.environment}"
    Agent = each.key
  }
}
