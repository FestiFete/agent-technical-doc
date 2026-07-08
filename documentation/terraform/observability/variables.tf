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
  description = "Bucket S3 du state (remote states ingestion + runtime)"
}

variable "alarm_actions" {
  type        = list(string)
  description = "ARNs SNS notifiés par les alarmes (vide = pas de notification)"
  default     = []
}

variable "agent_name" {
  type        = string
  description = "Nom de l'agent (namespace métriques runtime)"
  default     = "agent-technical-doc"
}
