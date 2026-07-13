# Paramètres spécifiques à l'ingestion (à compléter avant mise en service).
# Usage : terraform apply -var-file=../shared.tfvars -var-file=terraform.tfvars

mention_handle = "@agent-technical-doc"

# ALLOWLIST — OBLIGATOIRE : liste des dépôts autorisés à déclencher l'agent.
# Vide = aucun dépôt autorisé (fail-safe). Renseignez vos dépôts ici.
allowed_repositories = [
  "FestiFete/RogerVoiceTest",
]

allowed_author_associations = ["OWNER", "MEMBER", "COLLABORATOR"]
