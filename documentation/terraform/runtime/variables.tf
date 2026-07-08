variable "aws_region" {
  type        = string
  description = "Région AWS"
}

variable "aws_profile" {
  type        = string
  description = "Profil AWS CLI pour le build/push Docker (vide = credentials par défaut)"
  default     = ""
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
  description = "Bucket S3 du state (remote states ecr, roles, security)"
}

variable "runtime_enable_alarms" {
  type        = bool
  description = "Activer les alarmes CloudWatch d'erreurs runtime"
  default     = true
}

variable "runtime_error_threshold" {
  type        = number
  description = "Seuil d'erreurs runtime avant alarme"
  default     = 5
}

variable "log_retention_days" {
  type        = number
  description = "Rétention des logs CloudWatch du runtime (jours)"
  default     = 30
}
