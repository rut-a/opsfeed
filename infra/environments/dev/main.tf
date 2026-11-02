module "events_table" {
  source = "../../modules/events_table"

  table_name = "opsfeed-dev-events"

  point_in_time_recovery_enabled = false
  deletion_protection_enabled    = false

  tags = {
    Project     = "opsfeed"
    Environment = "dev"
    ManagedBy   = "terraform"
    Component   = "events-storage"
  }
}

module "ingest_lambda" {
  source = "../../modules/lambda_function"

  function_name       = "opsfeed-dev-ingest"
  execution_role_name = "opsfeed-dev-lambda-execution-ingest"

  source_dir   = "${path.root}/../../../services/ingest"
  package_path = "${path.root}/.build/opsfeed-ingest.zip"

  runtime       = "python3.12"
  handler       = "handler.handler"
  architectures = ["arm64"]

  timeout     = 10
  memory_size = 256

  log_retention_in_days = 14

  environment_variables = {
    LOGS_TABLE_NAME      = module.events_table.table_name
    TENANT_MAP_PARAMETER = "/opsfeed/dev/tenant-api-keys"
    RETENTION_DAYS       = "30"
  }
  extra_policy_statements = [
    {
      sid = "WriteEventsToDynamoDB"

      actions = [
        "dynamodb:PutItem"
      ]

      resources = [
        module.events_table.table_arn
      ]
    },
    {
      sid = "ReadTenantMapFromSSM"

      actions = [
        "ssm:GetParameter"
      ]

      resources = [
        "arn:aws:ssm:us-east-1:112859066344:parameter/opsfeed/dev/tenant-api-keys"
      ]
    }
  ]

  tags = {
    Project     = "opsfeed"
    Environment = "dev"
    ManagedBy   = "terraform"
    Component   = "ingestion"
  }
}

module "http_api" {
  source = "../../modules/http_api"

  api_name             = "opsfeed-dev-api"
  lambda_function_name = module.ingest_lambda.function_name
  lambda_invoke_arn    = module.ingest_lambda.invoke_arn
  route_key            = "POST /v1/events"

  tags = {
    Project     = "opsfeed"
    Environment = "dev"
  }
}