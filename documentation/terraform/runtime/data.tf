data "terraform_remote_state" "ecr" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "ecr/terraform.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "roles" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "roles/terraform.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "security" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "security/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  ecr_repository_url  = data.terraform_remote_state.ecr.outputs.repository_url
  ecr_repository_name = data.terraform_remote_state.ecr.outputs.repository_name

  runtime_execution_role_arn = data.terraform_remote_state.roles.outputs.agentcore_runtime_execution_role_arn

  github_token_secret_arn = data.terraform_remote_state.security.outputs.github_token_secret_arn
  idempotency_table_name  = data.terraform_remote_state.security.outputs.idempotency_table_name

  # Agents source (dans le repo autonome : documentation/scripts/agents)
  agents_root    = "${path.module}/../../scripts/agents"
  agents_json    = jsondecode(file("${local.agents_root}/agents.json"))
  enabled_agents = { for name, cfg in local.agents_json : name => cfg if try(cfg.enabled, false) }

  agent_source_files = {
    for name in keys(local.enabled_agents) :
    name => [
      for f in fileset("${local.agents_root}/${name}", "**") :
      f if !strcontains(f, "__pycache__") && !endswith(f, ".pyc")
    ]
  }
  agent_source_hash = {
    for name, files in local.agent_source_files :
    name => sha1(join("", [for f in files : filesha1("${local.agents_root}/${name}/${f}")]))
  }

  default_agent_config = {
    idle_timeout = 900
    max_lifetime = 3600
    protocol     = "HTTP"
  }

  discovered_agents = {
    for name, cfg in local.enabled_agents :
    name => merge(local.default_agent_config, {
      environment_variables = try(cfg.environment_variables, {})
    })
  }
}
