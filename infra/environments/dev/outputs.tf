output "events_table_name" {
  description = "Name of the Opsfeed events table."
  value       = module.events_table.table_name
}

output "events_table_arn" {
  description = "ARN of the Opsfeed events table."
  value       = module.events_table.table_arn
}

output "events_table_stream_arn" {
  description = "Stream ARN of the Opsfeed events table."
  value       = module.events_table.stream_arn
}

output "ingest_lambda_function_name" {
  value = module.ingest_lambda.function_name
}

output "ingest_lambda_function_arn" {
  value = module.ingest_lambda.function_arn
}

output "ingest_lambda_invoke_arn" {
  value = module.ingest_lambda.invoke_arn
}

output "ingest_lambda_execution_role_arn" {
  value = module.ingest_lambda.execution_role_arn
}

output "ingest_lambda_log_group_name" {
  value = module.ingest_lambda.log_group_name
}

output "ingest_url" {
  description = "Public URL for the Opsfeed ingest endpoint."
  value       = module.http_api.ingest_url
}