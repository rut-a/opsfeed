output "table_name" {
  description = "Name of the DynamoDB events table."
  value       = aws_dynamodb_table.this.name
}

output "table_arn" {
  description = "ARN of the DynamoDB events table."
  value       = aws_dynamodb_table.this.arn
}

output "stream_arn" {
  description = "ARN of the DynamoDB stream."
  value       = aws_dynamodb_table.this.stream_arn
}