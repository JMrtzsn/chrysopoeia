data "google_project" "current" {
  project_id = var.project_id
}

locals {
  feature_topic = var.pubsub_topic != ""

  operator_lower = lower(var.operator)
  project_number = data.google_project.current.number

  # Unconditional identities.
  runner_email   = google_service_account.runner.email
  runner_member  = "serviceAccount:${google_service_account.runner.email}"
  trigger_email  = google_service_account.trigger.email
  trigger_member = "serviceAccount:${google_service_account.trigger.email}"

  # Conditional identities resolve to "" while their feature is disabled;
  # every consumer of them is gated on the same feature flag.
  observer_email       = try(google_service_account.observer[0].email, "")
  observer_member      = try("serviceAccount:${google_service_account.observer[0].email}", "")
  transfer_email       = try(google_service_account.transfer_runner[0].email, "")
  transfer_member      = try("serviceAccount:${google_service_account.transfer_runner[0].email}", "")
  consumer_email       = try(google_service_account.consumer[0].email, "")
  consumer_member      = try("serviceAccount:${google_service_account.consumer[0].email}", "")
  invoker_email        = try(google_service_account.invoker[0].email, "")
  consumer_bucket_name = try(google_storage_bucket.consumer_ledger[0].name, "")
  consumer_uri         = try(google_cloud_run_v2_service.consumer[0].uri, "")
  pubsub_agent_member  = try("serviceAccount:${google_project_service_identity.pubsub_agent[0].email}", "")

  # Event-archive dataset/table IDs, resolved only when the topic exists.
  archive_dataset_id         = try(google_bigquery_dataset.event_archive[0].dataset_id, "")
  archive_table_id           = try(google_bigquery_table.raw_events[0].table_id, "")
  open_positions_id          = try(google_bigquery_table.open_positions[0].table_id, "")
  topic_id                   = try(google_pubsub_topic.trade_plans[0].id, "")
  topic_name                 = try(google_pubsub_topic.trade_plans[0].name, "")
  dead_letter_id             = try(google_pubsub_topic.dead_letter[0].id, "")
  consumer_subscription_name = try(google_pubsub_subscription.paper_consumer[0].name, "")

  harness_image = var.image_digest != "" ? var.image_digest : format(
    "%s-docker.pkg.dev/%s/%s/harness:latest",
    var.region,
    var.project_id,
    google_artifact_registry_repository.images.name,
  )

  scan_workflow_name = "chrysopoeia-scan-${var.operator}"
  scan_workflow_uri = format(
    "https://workflowexecutions.googleapis.com/v1/projects/%s/locations/%s/workflows/%s/executions",
    var.project_id,
    var.region,
    local.scan_workflow_name,
  )
  transfer_agent_member  = "serviceAccount:service-${local.project_number}@gcp-sa-bigquerydatatransfer.iam.gserviceaccount.com"
  scheduler_agent_member = "serviceAccount:service-${local.project_number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

  # Consumer sweep scheduler name matches the Pulumi auto-named live resource
  # (roadmap 12d imports it by ID); changing it would recreate the job.
  consumer_sweep_job_name = "consumer-sweep-916f9e1"
}
