output "webhook_url" {
  description = "URL du webhook à configurer dans GitHub (Payload URL) — passe par CloudFront+WAF (SEC-F1), ne pas utiliser l'URL API Gateway directe"
  value       = "https://${aws_cloudfront_distribution.webhook.domain_name}/webhook"
}

output "webhook_api_gateway_url" {
  description = "URL API Gateway directe (origine derrière CloudFront) — debug/diagnostic uniquement, ne pas configurer côté GitHub : contourne le WAF et est désormais rejetée par la Lambda (401, ORIGIN_VERIFY_SECRET manquant, SEC-F1)"
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
