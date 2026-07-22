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

# --- Contrôles détectifs (SEC-F3) --------------------------------------------
variable "role_name_prefix" {
  type        = string
  description = "Préfixe imposé aux noms de rôles IAM (guardrail org : iam:CreateRole n'est autorisé que si le nom commence par ce préfixe)."
  default     = "limited-"
}

variable "enable_cloudtrail" {
  type        = bool
  description = "Active le trail CloudTrail account-wide + les metric filters/alarmes associées. À désactiver si un trail existe déjà au niveau organisation (éviter doublon/coût)."
  default     = true
}

variable "enable_guardduty" {
  type        = bool
  description = "Active un détecteur GuardDuty dans ce compte/région. À désactiver si GuardDuty est déjà géré au niveau organisation (un seul détecteur autorisé par compte et par région)."
  default     = true
}

variable "cloudtrail_log_retention_days" {
  type        = number
  description = "Rétention CloudWatch Logs des événements CloudTrail (jours) — plus longue que les logs applicatifs (var.log_retention_days ailleurs) car ce sont des logs de sécurité/audit."
  default     = 90
}

variable "cloudtrail_s3_retention_days" {
  type        = number
  description = "Rétention S3 des fichiers de logs CloudTrail bruts (jours) avant expiration."
  default     = 365
}

variable "secrets_access_alarm_threshold" {
  type        = number
  description = "Seuil (nb d'appels secretsmanager:GetSecretValue sur 5 min) au-delà duquel l'alarme se déclenche. Volontairement > 0 : l'accès aux secrets est une opération normale et fréquente ici (1 par delivery webhook + 1 par run accepté) ; l'alarme vise un pic anormal, pas l'usage nominal."
  default     = 30
}
