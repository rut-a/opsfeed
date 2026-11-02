output "api_id" {
  description = "ID of the HTTP API."
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Base URL of the HTTP API."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "ingest_url" {
  description = "URL for the ingest route."
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/v1/events"
}