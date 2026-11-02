# Package the Python application into a ZIP file.
data "archive_file" "this" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = var.package_path

  excludes = [
    "tests/**",
    "**/__pycache__/**",
    "**/*.pyc"
  ]
}

# Lambda needs this role to assume an IAM role.
data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Create the execution role.
resource "aws_iam_role" "this" {
  name               = var.execution_role_name
  assume_role_policy = data.aws_iam_policy_document.assume_role.json

  tags = var.tags
}

# Create the Lambda log group explicitly.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_in_days

  tags = var.tags
}

# Define the permissions this Lambda needs.
data "aws_iam_policy_document" "permissions" {
  # Allow writing logs only to this function's log group.
  statement {
    sid    = "WriteFunctionLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]

    resources = [
      "${aws_cloudwatch_log_group.this.arn}:*"
    ]
  }

  # Allow the environment root to add service-specific permissions.
  dynamic "statement" {
    for_each = var.extra_policy_statements

    content {
      sid       = statement.value.sid
      effect    = "Allow"
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

# Attach the permissions to the execution role.
resource "aws_iam_role_policy" "this" {
  name   = "${var.execution_role_name}-permissions"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.permissions.json
}

# Deploy the Lambda function.
resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = aws_iam_role.this.arn

  runtime       = var.runtime
  handler       = var.handler
  architectures = var.architectures

  filename         = data.archive_file.this.output_path
  source_code_hash = data.archive_file.this.output_base64sha256

  timeout     = var.timeout
  memory_size = var.memory_size

  # Only create the environment block when variables are supplied.
  dynamic "environment" {
    for_each = length(var.environment_variables) > 0 ? [var.environment_variables] : []

    content {
      variables = environment.value
    }
  }

  tags = var.tags

  # Ensure the log group and permissions exist before Lambda creation.
  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy.this
  ]
}