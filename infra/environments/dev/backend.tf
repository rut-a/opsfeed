terraform {
  backend "s3" {
    bucket       = "opsfeed-state-test-table"
    key          = "envs/dev/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
}
