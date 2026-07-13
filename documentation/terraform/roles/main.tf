# ─── Rôle d'exécution AgentCore Runtime (moindre privilège) ──────────────────

resource "aws_iam_role" "runtime_execution" {
  name        = "${var.project_name}-agentcore-runtime-execution-${var.environment}"
  description = "Rôle d'exécution AgentCore Runtime pour agent-technical-doc"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })

  tags = { Name = "${var.project_name}-agentcore-runtime-execution-${var.environment}" }
}

resource "aws_iam_role_policy" "runtime_execution" {
  name = "runtime-execution-policy"
  role = aws_iam_role.runtime_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRGetAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid      = "ECRPullImages"
        Effect   = "Allow"
        Action   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Resource = local.ecr_repository_arn
      },
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:${local.account_id}:inference-profile/*"
        ]
      },
      {
        Sid      = "CloudWatchLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/bedrock-agentcore/*"
      },
      {
        Sid      = "EMFMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = "AgentTechnicalDoc" }
        }
      },
      {
        Sid      = "GitHubTokenRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = local.github_token_secret_arn
      },
      {
        Sid      = "IdempotencyStatusUpdate"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = local.idempotency_table_arn
      }
      # Statement KMS retiré : secrets aws/secretsmanager + DynamoDB clé AWS par
      # défaut (POC sans CMK — DENY kms:CreateKey sur le rôle NewSysOps).
    ]
  })
}

output "agentcore_runtime_execution_role_arn" {
  value       = aws_iam_role.runtime_execution.arn
  description = "ARN du rôle d'exécution AgentCore Runtime"
}

output "agentcore_runtime_execution_role_name" {
  value       = aws_iam_role.runtime_execution.name
  description = "Nom du rôle d'exécution AgentCore Runtime"
}
