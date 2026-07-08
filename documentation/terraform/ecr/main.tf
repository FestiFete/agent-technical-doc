locals {
  ecr_repository_name = coalesce(var.ecr_repository_name, "${var.project_name}-ecr")
}

resource "aws_ecr_repository" "agents" {
  name                 = local.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = local.ecr_repository_name
  }
}

resource "aws_ecr_lifecycle_policy" "agents" {
  repository = aws_ecr_repository.agents.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Supprimer les images non taguées après 1 jour"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Garder les ${var.image_retention_count} dernières images taguées"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["agent", "v", "latest", "POC"]
          countType     = "imageCountMoreThan"
          countNumber   = var.image_retention_count
        }
        action = { type = "expire" }
      }
    ]
  })
}

output "repository_url" {
  value       = aws_ecr_repository.agents.repository_url
  description = "URL du repository ECR"
}

output "repository_arn" {
  value       = aws_ecr_repository.agents.arn
  description = "ARN du repository ECR"
}

output "repository_name" {
  value       = aws_ecr_repository.agents.name
  description = "Nom du repository ECR"
}
