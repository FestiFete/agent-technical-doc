terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "~> 1.0"
    }
  }

  backend "s3" {
    bucket  = "amzn-agent-technical-doc-statetf-CHANGEME-eu-central-1"
    region  = "eu-central-1"
    key     = "runtime/terraform.tfstate"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project = var.project_name
      Env     = var.environment
      Module  = "runtime"
    }
  }
}

provider "awscc" {
  region = var.aws_region
}
