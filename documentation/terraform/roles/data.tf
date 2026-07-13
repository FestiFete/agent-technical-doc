data "aws_caller_identity" "current" {}

data "terraform_remote_state" "ecr" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "ecr/terraform.tfstate"
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
  account_id          = data.aws_caller_identity.current.account_id
  ecr_repository_name = coalesce(var.ecr_repository_name, "${var.project_name}-ecr")
  ecr_repository_arn  = "arn:aws:ecr:${var.aws_region}:${local.account_id}:repository/${local.ecr_repository_name}"

  github_token_secret_arn = data.terraform_remote_state.security.outputs.github_token_secret_arn
  idempotency_table_arn   = data.terraform_remote_state.security.outputs.idempotency_table_arn
}
