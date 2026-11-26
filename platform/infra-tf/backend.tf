# Remote state with lock-based concurrency, created once by the operator.
# The bucket must exist and be versioned before the first
# authenticated init; offline gates run `terraform init -backend=false`.
# The bucket name lives in the operator-local, git-ignored backend.hcl:
#   bucket = "<project-id>-chrs-tfstate-local"
terraform {
  backend "gcs" {
    prefix = "infra"
  }
}
