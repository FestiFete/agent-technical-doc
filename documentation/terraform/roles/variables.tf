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
