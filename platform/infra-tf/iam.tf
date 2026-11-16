# Least-privileged identities. Each service owns exactly its resource grants.
resource "google_service_account" "runner" {
  project      = var.project_id
  account_id   = format("%.30s", "chrysopoeia-runner-${var.operator}")
  display_name = "Chrysopoeia paper-cycle runner (${var.operator})"
  description  = "Job execution identity: Vertex model calls, image reads, and the journal bucket only."
}

resource "google_service_account" "trigger" {
  project      = var.project_id
  account_id   = format("%.30s", "chrysopoeia-trigger-${var.operator}")
  display_name = "Chrysopoeia job-trigger queue identity (${var.operator})"
  description  = "Executes the paper-cycle job with arg overrides from queued campaign tasks only."
}

# Google-managed service agents (Pub/Sub push, Cloud Tasks OIDC) exist as a
# side effect of enabling the APIs; their emails follow the deterministic
# service-{project_number}@gcp-sa-{service} pattern, so Terraform only needs
# to reference them, not manage them.

# Custom role: run.jobs.run + runWithOverrides only.
resource "google_project_iam_custom_role" "job_trigger" {
  project     = var.project_id
  role_id     = format("%.64s", "chrysopoeia_job_trigger_${replace(var.operator, "-", "_")}")
  title       = "Chrysopoeia job trigger (${var.operator})"
  permissions = ["run.jobs.run", "run.jobs.runWithOverrides"]
}

resource "google_project_iam_member" "job_trigger_executor" {
  project = var.project_id
  role    = google_project_iam_custom_role.job_trigger.id
  member  = local.trigger_member
}

resource "google_project_iam_member" "runner_vertex_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = local.runner_member
}

# Cloud Tasks agent may mint trigger-identity tokens for queued tasks.
resource "google_service_account_iam_member" "tasks_agent_token_creator" {
  service_account_id = google_service_account.trigger.id
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.tasks_agent_member
}

locals {
  tasks_agent_member = "serviceAccount:service-${local.project_number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"
}

# Scheduled scanning: the workflow runs as the trigger identity; the scheduler
# service agent and the trigger identity get the invoker/token-creator grants.
resource "google_service_account_iam_member" "scan_scheduler_token_creator" {
  count              = var.scan_schedule != "" ? 1 : 0
  service_account_id = google_service_account.trigger.id
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.scheduler_agent_member
}

resource "google_project_iam_member" "scan_workflow_invoker" {
  count   = var.scan_schedule != "" ? 1 : 0
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = local.trigger_member
}

# Event archive: only the projection runner and reader identities below.
resource "google_project_iam_member" "transfer_job_user" {
  count      = local.feature_topic ? 1 : 0
  project    = var.project_id
  role       = "roles/bigquery.jobUser"
  member     = local.transfer_member
  depends_on = [google_project_service.bigquerydatatransfer]
}

# Creating a transfer config pinned to the runner's credential requires the
# operator to actAs it during the create itself.
resource "google_project_iam_member" "transfer_config_creator" {
  count   = var.observer_invoker_member != "" && local.feature_topic ? 1 : 0
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = var.observer_invoker_member
}

# The transfer service agent mints runner tokens on every scheduled run.
resource "google_service_account_iam_member" "transfer_token_creator" {
  count              = local.feature_topic ? 1 : 0
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.transfer_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.transfer_agent_member
}

# Read-only context history: optional runner grants.
resource "google_project_iam_member" "runner_job_user" {
  count      = var.context_history_enabled && local.feature_topic ? 1 : 0
  project    = var.project_id
  role       = "roles/bigquery.jobUser"
  member     = local.runner_member
  depends_on = [google_project_service.bigquery]
}

# Observer runtime identity: jobUser + dataset reader only.
resource "google_service_account" "observer" {
  count        = var.observer_image_digest != "" ? 1 : 0
  project      = var.project_id
  account_id   = format("%.30s", "chrysopoeia-observer-${var.operator}")
  display_name = "Chrysopoeia archive observer (${var.operator})"
  description  = "Runs read-only queries against the event archive only."
}

resource "google_project_iam_member" "observer_job_user" {
  count      = var.observer_image_digest != "" ? 1 : 0
  project    = var.project_id
  role       = "roles/bigquery.jobUser"
  member     = local.observer_member
  depends_on = [google_project_service.bigquery]
}

# Consumer identity: publishes outcomes to the event topic.
resource "google_service_account" "consumer" {
  count        = var.consumer_image_digest != "" ? 1 : 0
  project      = var.project_id
  account_id   = format("%.30s", "chrysopoeia-consumer-${var.operator}")
  display_name = "Chrysopoeia paper consumer (${var.operator})"
}

resource "google_pubsub_topic_iam_member" "consumer_outcome_publisher" {
  count   = var.consumer_image_digest != "" ? 1 : 0
  project = var.project_id
  topic   = local.topic_name
  role    = "roles/pubsub.publisher"
  member  = local.consumer_member
}

# Private invoker identity: Pub/Sub and the sweep scheduler invoke the service.
resource "google_service_account" "invoker" {
  count        = var.consumer_image_digest != "" ? 1 : 0
  project      = var.project_id
  account_id   = format("%.30s", "chrysopoeia-invoker-${var.operator}")
  display_name = "Chrysopoeia consumer invoker (${var.operator})"
}

resource "google_service_account_iam_member" "pubsub_invoker_token_creator" {
  count              = var.consumer_image_digest != "" ? 1 : 0
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.invoker_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent_member
}

# Open-positions projection runner identity: a normal project service account,
# because API-created scheduled-query configs need an explicit credential and
# Google-managed service agents reject impersonation.
resource "google_service_account" "transfer_runner" {
  count        = local.feature_topic ? 1 : 0
  project      = var.project_id
  account_id   = format("%.30s", "chrysopoeia-transfer-${var.operator}")
  display_name = "Chrysopoeia open-positions projection (${var.operator})"
  description  = "Runs the scheduled query that rebuilds the open-positions projection."
}
