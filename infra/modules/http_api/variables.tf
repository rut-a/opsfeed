variable "api_name" {
  description = "Name of the API Gateway HTTP API."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the Lambda function receiving requests."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "Invoke ARN of the Lambda function."
  type        = string
}

variable "route_key" {
  description = "HTTP API route that invokes the Lambda."
  type        = string
  default     = "POST /v1/events"
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default     = {}
}