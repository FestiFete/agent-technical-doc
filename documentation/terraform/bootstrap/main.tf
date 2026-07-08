# Bootstrap : bucket S3 du state Terraform (chiffré, versionné, privé).
# À déployer en premier, avec un backend local, puis migrer les autres modules
# vers ce bucket. Voir README.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project = var.project_name
      Env     = var.environment
      Module  = "bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "amzn-agent-${var.project_name}-statetf-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
}

resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket" {
  description = "Nom du bucket S3 du state Terraform (à reporter dans shared.tfvars et les providers.tf)"
  value       = aws_s3_bucket.state.bucket
}
