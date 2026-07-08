data "aws_caller_identity" "current" {}

data "terraform_remote_state" "security" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "security/terraform.tfstate"
    region = var.aws_region
  }
}

data "terraform_remote_state" "runtime" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "runtime/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  name       = "${var.project_name}-${var.environment}"

  kms_key_arn             = data.terraform_remote_state.security.outputs.kms_key_arn
  webhook_hmac_secret_arn = data.terraform_remote_state.security.outputs.webhook_hmac_secret_arn
  idempotency_table_name  = data.terraform_remote_state.security.outputs.idempotency_table_name
  idempotency_table_arn   = data.terraform_remote_state.security.outputs.idempotency_table_arn
  idempotency_ttl_days    = data.terraform_remote_state.security.outputs.idempotency_ttl_days

  runtime_arn = data.terraform_remote_state.runtime.outputs.doc_agent_runtime_arn

  lambdas_src = "${path.module}/../../scripts/lambdas"
}
