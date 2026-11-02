data "aws_caller_identity" "current" {}

locals {
  github_oidc_url = "https://token.actions.githubusercontent.com"
  github_audience = "sts.amazonaws.com"

  repo_subject = "repo:${var.github_org}/${var.github_repo}"

  oidc_provider_arn = var.create_github_oidc_provider ? (
    aws_iam_openid_connect_provider.github[0].arn
  ) : data.aws_iam_openid_connect_provider.github[0].arn

  state_bucket_arn = aws_s3_bucket.state.arn
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project   = "opsfeed"
    Purpose   = "terraform-state"
    ManagedBy = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id

  depends_on = [
    aws_s3_bucket_public_access_block.state
  ]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.state.arn,
        "${aws_s3_bucket.state.arn}/*"
      ]
      Condition = {
        Bool = {
          "aws:SecureTransport" = "false"
        }
      }
    }]
  })
}

# ------------------------------------------------------------
# 4.2: GitHub Actions OIDC provider
# ------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url = local.github_oidc_url

  client_id_list = [
    local.github_audience
  ]

  # Common GitHub OIDC thumbprint. Verify against current AWS
  # and GitHub guidance before applying.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1"
  ]

  tags = {
    Project = "opsfeed"
  }
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1

  url = local.github_oidc_url
}

# ------------------------------------------------------------
# Shared trust policy helper
# Each role still has its own exact repository subject.
# ------------------------------------------------------------

data "aws_iam_policy_document" "plan_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = [local.github_audience]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${local.repo_subject}:pull_request"]
    }
  }
}

data "aws_iam_policy_document" "apply_trust" {
  for_each = var.environments

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = [local.github_audience]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "${local.repo_subject}:environment:${each.value}"
      ]
    }
  }
}

# ------------------------------------------------------------
# 4.3: Plan role
# ------------------------------------------------------------

resource "aws_iam_role" "plan" {
  name               = "opsfeed-github-plan"
  assume_role_policy = data.aws_iam_policy_document.plan_trust.json

  tags = {
    Project = "opsfeed"
    Purpose = "terraform-plan"
  }
}

resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}


data "aws_iam_policy_document" "plan_state" {
  # Allow listing only the environment state paths.
  statement {
    sid       = "ListStateBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "envs/*",
        "envs"
      ]
    }
  }

  # Read Terraform state files.
  statement {
    sid     = "ReadEnvironmentState"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${local.state_bucket_arn}/envs/*"
    ]
  }

  # Read, acquire, and release Terraform lock files only.
  statement {
    sid    = "ManageLockFilesOnly"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = [
      "${local.state_bucket_arn}/envs/*/*.tflock"
    ]
  }
}



resource "aws_iam_role_policy" "plan_state" {
  name   = "opsfeed-plan-state-access"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan_state.json
}

# ------------------------------------------------------------
# 4.4: Environment-specific apply roles
# ------------------------------------------------------------

resource "aws_iam_role" "apply" {
  for_each = var.environments

  name               = "opsfeed-github-apply-${each.value}"
  assume_role_policy = data.aws_iam_policy_document.apply_trust[each.key].json

  tags = {
    Project     = "opsfeed"
    Environment = each.value
    Purpose     = "terraform-apply"
  }
}


data "aws_iam_policy_document" "apply_permissions" {
  for_each = var.environments


  # List only this environment's Terraform state directory.
  statement {
    sid       = "ListEnvironmentState"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "envs/${each.value}",
        "envs/${each.value}/*"
      ]
    }
  }

  # Read and write this environment's state file.
  # State deletion is deliberately not permitted.
  statement {
    sid     = "ReadWriteEnvironmentState"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${local.state_bucket_arn}/envs/${each.value}/terraform.tfstate"
    ]
  }

  # Terraform must be able to create and remove its lock file.
  statement {
    sid    = "ManageEnvironmentLockFile"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    resources = [
      "${local.state_bucket_arn}/envs/${each.value}/terraform.tfstate.tflock"
    ]
  }


  # Service permissions for this environment's Opsfeed resources.
  statement {
    sid    = "ManageOpsfeedRuntime"
    effect = "Allow"
    actions = [
      "dynamodb:CreateTable",
      "dynamodb:DeleteTable",
      "dynamodb:DescribeTable",
      "dynamodb:UpdateTable",
      "dynamodb:TagResource",
      "dynamodb:UntagResource",
      "dynamodb:ListTagsOfResource",
      "dynamodb:UpdateTimeToLive",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:DeleteItem",
      "dynamodb:UpdateItem",

      "lambda:CreateFunction",
      "lambda:DeleteFunction",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
      "lambda:PublishVersion",
      "lambda:CreateAlias",
      "lambda:UpdateAlias",
      "lambda:DeleteAlias",
      "lambda:AddPermission",
      "lambda:RemovePermission",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:ListTags",

      "apigateway:GET",
      "apigateway:POST",
      "apigateway:PUT",
      "apigateway:PATCH",
      "apigateway:DELETE",

      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:PutRetentionPolicy",
      "logs:DeleteRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",

      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:PutParameter",
      "ssm:DeleteParameter",
      "ssm:AddTagsToResource",
      "ssm:RemoveTagsFromResource",
      "ssm:ListTagsForResource"
    ]

    resources = [
      "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/opsfeed-${each.value}-*",
      "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:opsfeed-${each.value}-*",
      "arn:aws:apigateway:${var.aws_region}::/apis/*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/opsfeed-${each.value}-*",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/opsfeed-${each.value}-*"
    ]
  }

  # Discovery actions require broad resource scope.
  statement {
    sid    = "RuntimeDiscovery"
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
      "ssm:DescribeParameters"
    ]
    resources = ["*"]
  }

  # Create and manage only designated Lambda execution roles.
  # Inline policies cannot be added by this GitHub role.
  statement {
    sid    = "ManageLambdaExecutionRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies"
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/opsfeed-${each.value}-lambda-execution-*"
    ]
  }

  # Allow only the basic Lambda logging policy to be attached or detached.
  statement {
    sid    = "AttachApprovedLambdaPolicy"
    effect = "Allow"
    actions = [
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy"
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/opsfeed-${each.value}-lambda-execution-*"
    ]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values = [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
      ]
    }
  }

  # Pass only designated execution roles to the Lambda service.
  statement {
    sid     = "PassOnlyLambdaExecutionRoles"
    effect  = "Allow"
    actions = ["iam:PassRole"]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/opsfeed-${each.value}-lambda-execution-*"
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "apply_permissions" {
  for_each = var.environments

  name   = "opsfeed-apply-${each.value}-permissions"
  role   = aws_iam_role.apply[each.key].id
  policy = data.aws_iam_policy_document.apply_permissions[each.key].json
}

# ------------------------------------------------------------
# 4.5: Environment-specific application deployment roles
# ------------------------------------------------------------

resource "aws_iam_role" "deploy" {
  for_each = var.environments

  name               = "opsfeed-github-deploy-${each.value}"
  assume_role_policy = data.aws_iam_policy_document.apply_trust[each.key].json

  tags = {
    Project     = "opsfeed"
    Environment = each.value
    Purpose     = "application-deployment"
  }
}

data "aws_iam_policy_document" "deploy_permissions" {
  for_each = var.environments

  statement {
    sid    = "DeployOpsfeedLambdaCode"
    effect = "Allow"

    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:UpdateFunctionCode",
      "lambda:PublishVersion"
    ]

    resources = [
      "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:opsfeed-${each.value}-*"
    ]
  }
}

resource "aws_iam_role_policy" "deploy_permissions" {
  for_each = var.environments

  name   = "opsfeed-deploy-${each.value}-permissions"
  role   = aws_iam_role.deploy[each.key].id
  policy = data.aws_iam_policy_document.deploy_permissions[each.key].json
}
