
output "state_bucket_name" {
  description = "S3 bucket used for Terraform state."
  value       = aws_s3_bucket.state.bucket
}

output "plan_role_arn" {
  description = "IAM role ARN for GitHub pull-request plans."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arns" {
  description = "IAM role ARNs indexed by environment."
  value = {
    for env, role in aws_iam_role.apply :
    env => role.arn
  }
}

output "deploy_role_arns" {
  description = "IAM role ARNs for application deployments, indexed by environment."

  value = {
    for env, role in aws_iam_role.deploy :
    env => role.arn
  }
}
