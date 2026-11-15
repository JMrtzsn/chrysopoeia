# Always-on APIs. disable_on_destroy semantics match infra/__main__.py:
# Run and Artifact Registry stay enabled if the stack is destroyed.
resource "google_project_service" "run" {
  project                    = var.project_id
  service                    = "run.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = true
}

resource "google_project_service" "artifactregistry" {
  project                    = var.project_id
  service                    = "artifactregistry.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = true
}

resource "google_project_service" "cloudtasks" {
  project                    = var.project_id
  service                    = "cloudtasks.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Event/archive feature APIs.
resource "google_project_service" "pubsub" {
  count                      = local.feature_topic ? 1 : 0
  project                    = var.project_id
  service                    = "pubsub.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "bigquery" {
  count                      = local.feature_topic ? 1 : 0
  project                    = var.project_id
  service                    = "bigquery.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "bigquerydatatransfer" {
  count                      = local.feature_topic ? 1 : 0
  project                    = var.project_id
  service                    = "bigquerydatatransfer.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
  depends_on                 = [google_project_service.bigquery]
}

# Consumer scheduling API.
resource "google_project_service" "cloudscheduler" {
  count                      = var.consumer_image_digest != "" ? 1 : 0
  project                    = var.project_id
  service                    = "cloudscheduler.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Scheduled scanning API.
resource "google_project_service" "workflows" {
  count                      = var.scan_schedule != "" ? 1 : 0
  project                    = var.project_id
  service                    = "workflows.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Health monitoring API.
resource "google_project_service" "monitoring" {
  count                      = var.health_alert_email != "" ? 1 : 0
  project                    = var.project_id
  service                    = "monitoring.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Native billing budget API.
resource "google_project_service" "billingbudgets" {
  count                      = var.budget_amount_usd > 0 ? 1 : 0
  project                    = var.project_id
  service                    = "billingbudgets.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}
