# Build & push des images d'agents, piloté par Terraform (comme le socle).
# Le hash du code source déclenche le rebuild ; le runtime référence l'image
# par digest ECR.

resource "null_resource" "validate_ecr" {
  lifecycle {
    precondition {
      condition     = local.ecr_repository_url != null && local.ecr_repository_url != ""
      error_message = "ECR indisponible. Déployez d'abord le module ecr."
    }
  }
}

resource "terraform_data" "build_push" {
  for_each = local.enabled_agents

  triggers_replace = local.agent_source_hash[each.key]

  provisioner "local-exec" {
    command     = "${path.module}/build_push.sh"
    interpreter = ["/usr/bin/env", "bash"]

    environment = merge(
      {
        AGENT_DIR  = "${local.agents_root}/${each.key}"
        ECR_URL    = local.ecr_repository_url
        IMAGE_TAG  = each.key
        AWS_REGION = var.aws_region
      },
      var.aws_profile != "" ? { AWS_PROFILE = var.aws_profile } : {}
    )
  }

  depends_on = [null_resource.validate_ecr]
}

data "aws_ecr_image" "agents" {
  for_each = local.enabled_agents

  repository_name = local.ecr_repository_name
  image_tag       = each.key

  depends_on = [terraform_data.build_push]
}
