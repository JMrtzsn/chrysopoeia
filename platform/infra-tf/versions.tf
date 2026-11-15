# Pinned toolchain (roadmap item 12a). Upgrades are deliberate, never casual.
terraform {
  required_version = "~> 1.15.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "8.11.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "8.11.0"
    }
  }
}
