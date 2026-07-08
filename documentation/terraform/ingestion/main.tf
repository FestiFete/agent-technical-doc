# ============================================================================
# SQS : file principale + DLQ (chiffrées KMS). Découple le webhook du worker,
# lisse la charge et isole les échecs.
# ============================================================================
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-dlq"
  kms_master_key_id         = local.kms_key_arn
  message_retention_seconds = 1209600 # 14 jours
}

resource "aws_sqs_queue" "main" {
  name              = "${local.name}-queue"
  kms_master_key_id = local.kms_key_arn
  # Visibility >= timeout worker (évite qu'un message soit rejoué pendant le run).
  visibility_timeout_seconds = var.worker_timeout_seconds + 60
  message_retention_seconds  = 345600 # 4 jours

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

# ============================================================================
# Packaging des Lambdas (boto3 fourni par le runtime → pas de pip install).
# ============================================================================
data "archive_file" "webhook" {
  type        = "zip"
  source_dir  = "${local.lambdas_src}/webhook-receiver"
  output_path = "${path.module}/build/webhook.zip"
}

data "archive_file" "worker" {
  type        = "zip"
  source_dir  = "${local.lambdas_src}/worker-dispatcher"
  output_path = "${path.module}/build/worker.zip"
}

# ============================================================================
# IAM : rôle de la Lambda webhook (moindre privilège, SANS token GitHub).
# ============================================================================
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "webhook" {
  name               = "${local.name}-webhook-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "webhook_basic" {
  role       = aws_iam_role.webhook.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "webhook" {
  name = "${local.name}-webhook-policy"
  role = aws_iam_role.webhook.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadHmacSecret"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = local.webhook_hmac_secret_arn
      },
      {
        Sid      = "ClaimIdempotency"
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = local.idempotency_table_arn
      },
      {
        Sid      = "SendToQueue"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.main.arn
      },
      {
        Sid      = "UseCmk"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = local.kms_key_arn
      }
    ]
  })
}

# ============================================================================
# IAM : rôle de la Lambda worker (InvokeAgentRuntime scopé à l'ARN).
# ============================================================================
resource "aws_iam_role" "worker" {
  name               = "${local.name}-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "worker_basic" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "worker" {
  name = "${local.name}-worker-policy"
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ConsumeQueue"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.main.arn
      },
      {
        Sid    = "InvokeRuntimeScoped"
        Effect = "Allow"
        Action = ["bedrock-agentcore:InvokeAgentRuntime"]
        # Scopé à l'ARN du runtime doc-agent (+ ses endpoints).
        Resource = [
          local.runtime_arn,
          "${local.runtime_arn}/runtime-endpoint/*"
        ]
      },
      {
        Sid      = "UseCmk"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = local.kms_key_arn
      }
    ]
  })
}

# ============================================================================
# CloudWatch Log Groups (rétention bornée).
# ============================================================================
resource "aws_cloudwatch_log_group" "webhook" {
  name              = "/aws/lambda/${local.name}-webhook"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.name}-worker"
  retention_in_days = var.log_retention_days
}

# ============================================================================
# Lambdas
# ============================================================================
resource "aws_lambda_function" "webhook" {
  function_name    = "${local.name}-webhook"
  role             = aws_iam_role.webhook.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = var.webhook_timeout_seconds
  memory_size      = 256
  filename         = data.archive_file.webhook.output_path
  source_code_hash = data.archive_file.webhook.output_base64sha256

  environment {
    variables = {
      WEBHOOK_HMAC_SECRET_ARN     = local.webhook_hmac_secret_arn
      MENTION_HANDLE              = var.mention_handle
      ALLOWED_REPOSITORIES        = join(",", var.allowed_repositories)
      ALLOWED_AUTHOR_ASSOCIATIONS = join(",", var.allowed_author_associations)
      QUEUE_URL                   = aws_sqs_queue.main.url
      IDEMPOTENCY_TABLE           = local.idempotency_table_name
      IDEMPOTENCY_TTL_DAYS        = tostring(local.idempotency_ttl_days)
    }
  }

  depends_on = [aws_cloudwatch_log_group.webhook, aws_iam_role_policy.webhook]
}

resource "aws_lambda_function" "worker" {
  function_name    = "${local.name}-worker"
  role             = aws_iam_role.worker.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = var.worker_timeout_seconds
  memory_size      = 256
  filename         = data.archive_file.worker.output_path
  source_code_hash = data.archive_file.worker.output_base64sha256

  environment {
    variables = {
      RUNTIME_ARN = local.runtime_arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.worker, aws_iam_role_policy.worker]
}

# SQS → worker (avec limite de concurrence).
resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn = aws_sqs_queue.main.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
  enabled          = true

  scaling_config {
    maximum_concurrency = var.worker_max_concurrency
  }
}

# ============================================================================
# API Gateway HTTP API → Lambda webhook (endpoint public HTTPS, auth par HMAC).
# ============================================================================
resource "aws_apigatewayv2_api" "webhook" {
  name          = "${local.name}-webhook-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "webhook" {
  api_id                 = aws_apigatewayv2_api.webhook.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.webhook.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook" {
  api_id    = aws_apigatewayv2_api.webhook.id
  route_key = "POST /webhook"
  target    = "integrations/${aws_apigatewayv2_integration.webhook.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.webhook.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}
