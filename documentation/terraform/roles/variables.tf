variable "aws_region" {
  type        = string
  description = "Région AWS"
}

variable "project_name" {
  type        = string
  description = "Nom du projet"
}

variable "environment" {
  type        = string
  description = "Environnement (POC)"
}

variable "state_bucket" {
  type        = string
  description = "Bucket S3 du state Terraform (lecture des remote states security + ecr)"
}

variable "ecr_repository_name" {
  type        = string
  description = "Nom du repository ECR (défaut: {project_name}-ecr)"
  default     = null
}

variable "role_name_prefix" {
  type        = string
  description = "Préfixe imposé aux noms de rôles IAM (guardrail org : iam:CreateRole n'est autorisé que si le nom commence par ce préfixe)."
  default     = "limited-"
}
