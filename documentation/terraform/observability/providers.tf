terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket       = "amzn-agent-technical-doc-statetf-375039967495-eu-central-1"
    region       = "eu-central-1"
    key          = "observability/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project = var.project_name
      Env     = var.environment
      Module  = "observability"
    }
  }
}
