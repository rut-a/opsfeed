variable "function_name" {
  description = "Name of the Lambda function."
  type        = string
}

variable "execution_role_name" {
  description = "Name of the Lambda execution IAM role."
  type        = string
}

variable "source_dir" {
  description = "Directory containing the Lambda Python source files."
  type        = string
}

variable "package_path" {
  description = "Path where the generated Lambda ZIP package will be written."
  type        = string
}

variable "runtime" {
  description = "Lambda runtime."
  type        = string
  default     = "python3.12"
}

variable "handler" {
  description = "Python module and function that Lambda invokes."
  type        = string
  default     = "handler.handler"
}

variable "architectures" {
  description = "Instruction set architectures for the Lambda function."
  type        = list(string)
  default     = ["arm64"]
}

variable "timeout" {
  description = "Maximum execution time in seconds."
  type        = number
  default     = 10
}

variable "memory_size" {
  description = "Lambda memory allocation in MB."
  type        = number
  default     = 256
}

variable "log_retention_in_days" {
  description = "Number of days to retain Lambda logs."
  type        = number
  default     = 14
}

variable "environment_variables" {
  description = "Environment variables passed to the Lambda function."
  type        = map(string)
  default     = {}
}

variable "extra_policy_statements" {
  description = "Additional IAM permissions required by the Lambda function."

  type = list(object({
    sid       = string
    actions   = list(string)
    resources = list(string)
  }))

  default = []
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default     = {}
}