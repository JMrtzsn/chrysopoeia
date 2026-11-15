# Remote state with lock-based concurrency, created once by the operator
# (roadmap item 12a). The bucket must exist and be versioned before the first
# authenticated init; offline gates run `terraform init -backend=false`.
terraform {
  backend "gcs" {
    bucket = "PROJECT_ID-chrs-tfstate-local"
    prefix = "infra"
  }
}
