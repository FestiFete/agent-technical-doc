output "webhook_url" {
  description = "URL du webhook à configurer dans GitHub (Payload URL)"
  value       = "${aws_apigatewayv2_api.webhook.api_endpoint}/webhook"
}

output "queue_url" {
  description = "URL de la file SQS principale"
  value       = aws_sqs_queue.main.url
}

output "dlq_url" {
  description = "URL de la DLQ"
  value       = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  description = "ARN de la DLQ (pour alarmes observability)"
  value       = aws_sqs_queue.dlq.arn
}

output "webhook_function_name" {
  value = aws_lambda_function.webhook.function_name
}

output "worker_function_name" {
  value = aws_lambda_function.worker.function_name
}
