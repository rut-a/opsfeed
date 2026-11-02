variable "table_name" {
  description = "Name of the DynamoDB events table."
  type        = string
}

variable "point_in_time_recovery_enabled" {
  description = "Whether point-in-time recovery is enabled."
  type        = bool
  default     = false
}

variable "deletion_protection_enabled" {
  description = "Whether deletion protection is enabled."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to the DynamoDB table."
  type        = map(string)
  default     = {}
}