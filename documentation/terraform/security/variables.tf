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

variable "idempotency_ttl_days" {
  type        = number
  description = "Durée de rétention (jours) des clés d'idempotence dans DynamoDB (purge par TTL)"
  default     = 30
}

variable "state_bucket" {
  type    = string
  default = null
}
