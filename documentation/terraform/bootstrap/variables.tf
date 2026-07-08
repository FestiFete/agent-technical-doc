variable "aws_region" {
  description = "Région AWS"
  type        = string
}

variable "project_name" {
  description = "Nom du projet"
  type        = string
}

variable "environment" {
  description = "Environnement (POC)"
  type        = string
}

# Absorbe la variable présente dans shared.tfvars non utilisée par ce module
# (évite le warning "Value for undeclared variable").
variable "state_bucket" {
  type    = string
  default = null
}
