# ============================================================================
# Variables partagées entre les modules Terraform de agent-technical-doc.
# Usage : terraform plan -var-file=../shared.tfvars (adapter le chemin relatif)
#
# NOTE : les blocs backend "s3" (providers.tf) ne peuvent pas utiliser de
# variables. Si vous changez project_name / state_bucket, mettez aussi à jour
# manuellement le bucket dans chaque providers.tf (ou utilisez
# `terraform init -backend-config=...`).
#
# Les paramètres spécifiques à l'ingestion (handle mentionné, allowlist de
# dépôts, associations d'auteur) sont dans terraform/ingestion/terraform.tfvars.
# ============================================================================

aws_region   = "eu-central-1"
project_name = "technical-doc"
environment  = "POC"

# Bucket S3 du state Terraform (créé par le module bootstrap). À adapter.
state_bucket = "amzn-agent-technical-doc-statetf-CHANGEME-eu-central-1"
