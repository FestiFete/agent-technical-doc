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
  description = "Bucket S3 du state (remote states security + runtime)"
}

# --- Paramètres d'ingestion (voir terraform.tfvars) --------------------------
variable "mention_handle" {
  type        = string
  description = "Handle mentionné qui déclenche l'agent"
  default     = "@agent-technical-doc"
}

variable "allowed_repositories" {
  type        = list(string)
  description = "Allowlist des dépôts autorisés (owner/repo). Vide = aucun (fail-safe)."
  default     = []
}

variable "allowed_author_associations" {
  type        = list(string)
  description = "Associations d'auteur autorisées à déclencher l'agent"
  default     = ["OWNER", "MEMBER", "COLLABORATOR"]
}

# --- Résilience / dimensionnement --------------------------------------------
variable "worker_timeout_seconds" {
  type        = number
  description = "Timeout de la Lambda worker (maintient la connexion streaming au runtime)"
  default     = 900
}

variable "webhook_timeout_seconds" {
  type        = number
  description = "Timeout de la Lambda webhook"
  default     = 15
}

variable "worker_max_concurrency" {
  type        = number
  description = "Concurrence max du worker (scaling SQS→Lambda)"
  default     = 5
}

variable "max_receive_count" {
  type        = number
  description = "Nombre de tentatives avant envoi en DLQ"
  default     = 2
}

variable "log_retention_days" {
  type        = number
  description = "Rétention des logs CloudWatch des Lambdas (jours)"
  default     = 14
}
