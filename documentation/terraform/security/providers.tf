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
    key          = "security/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  # default_tags retiré : le rôle NewSysOps n'a pas kms:TagResource, or default_tags
  # s'applique à toutes les ressources (dont la CMK) sans possibilité d'exclusion par
  # ressource. Contournement POC pour éviter l'appel TagResource à la création.
}
