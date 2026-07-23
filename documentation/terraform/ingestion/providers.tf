terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {
    bucket  = "amzn-agent-technical-doc-statetf-375039967495-eu-central-1"
    region  = "eu-central-1"
    key     = "ingestion/terraform.tfstate"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project = var.project_name
      Env     = var.environment
      Module  = "ingestion"
    }
  }
}

# WAFv2 scope=CLOUDFRONT (et sa logging configuration) doit être créé en
# us-east-1 quelle que soit la région du reste de la stack — contrainte AWS
# globale, cf. waf.tf.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project = var.project_name
      Env     = var.environment
      Module  = "ingestion"
    }
  }
}
