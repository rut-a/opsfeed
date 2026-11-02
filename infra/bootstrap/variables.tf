
variable "aws_region" {
  description = "AWS region for the Opsfeed infrastructure."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for Terraform state."
  type        = string

  validation {
    condition     = length(var.state_bucket_name) >= 3 && length(var.state_bucket_name) <= 63
    error_message = "The S3 bucket name must be between 3 and 63 characters."
  }
}

variable "github_org" {
  description = "Exact GitHub organization or user name."
  type        = string
}

variable "github_repo" {
  description = "Exact GitHub repository name, preserving its case."
  type        = string
}

variable "environments" {
  description = "Environments that receive separate apply roles."
  type        = set(string)
  default     = ["dev"]

  validation {
    condition = (
      length(var.environments) > 0 &&
      alltrue([
        for env in var.environments :
        can(regex("^[a-z0-9-]+$", env))
      ])
    )
    error_message = "Environments must be non-empty lowercase names containing only letters, digits, and hyphens."
  }
}

variable "create_github_oidc_provider" {
  description = "Create the GitHub OIDC provider if it does not already exist."
  type        = bool
  default     = true
}
