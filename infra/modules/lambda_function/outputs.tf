output "function_name" {
  description = "Name of the Lambda function."
  value       = aws_lambda_function.this.function_name
}

output "function_arn" {
  description = "ARN of the Lambda function."
  value       = aws_lambda_function.this.arn
}

output "invoke_arn" {
  description = "Invocation ARN used by API Gateway integrations."
  value       = aws_lambda_function.this.invoke_arn
}

output "execution_role_arn" {
  description = "ARN of the Lambda execution role."
  value       = aws_iam_role.this.arn
}

output "log_group_name" {
  description = "Name of the Lambda CloudWatch log group."
  value       = aws_cloudwatch_log_group.this.name
}