provider "google" {
  project = var.project_id
  region  = var.region
}

# google_project_service_identity only exists in the beta provider.
provider "google-beta" {
  project = var.project_id
  region  = var.region
}
