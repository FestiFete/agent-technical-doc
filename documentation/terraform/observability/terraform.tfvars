# Paramètres spécifiques à l'observability.
# Usage : terraform apply -var-file=../shared.tfvars -var-file=terraform.tfvars

# CloudTrail géré au niveau de l'organisation : le rôle SSO de ce compte a un
# Deny explicite sur tout le namespace cloudtrail: (CreateTrail ET DescribeTrails).
# On désactive donc la création d'un trail local (un trail org-wide couvre déjà
# ce compte). Le reste du module (dashboard + alarmes + topic SNS) s'applique.
enable_cloudtrail = false

# GuardDuty : laissé activé. Si l'apply échoue avec le même AccessDeniedException
# (Deny explicite sur guardduty:CreateDetector = service aussi géré par l'org),
# passer cette valeur à false.
# enable_guardduty = false

# Email notifié par les alarmes CloudWatch (REL-F1). Renseigner puis confirmer
# le mail d'abonnement SNS reçu. Vide = topic créé sans abonné email.
alarm_email = ""
