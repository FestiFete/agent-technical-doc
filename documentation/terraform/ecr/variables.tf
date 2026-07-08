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

variable "ecr_repository_name" {
  type        = string
  description = "Nom du repository ECR (défaut: {project_name}-ecr)"
  default     = null
}

variable "image_retention_count" {
  type        = number
  description = "Nombre d'images taguées à conserver"
  default     = 10
}

variable "state_bucket" {
  type    = string
  default = null
}
