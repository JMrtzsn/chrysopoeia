output "runner_email" {
  description = "Paper-cycle job execution identity."
  value       = local.runner_email
}

output "journal_bucket_name" {
  description = "GCS bucket mounted as /mnt/journal in the cycle job."
  value       = google_storage_bucket.journals.name
}

output "harness_image" {
  description = "Resolved harness container image (pinned digest or registry alias)."
  value       = local.harness_image
}

output "job_name" {
  description = "Cloud Run job executing one paper cycle per invocation."
  value       = google_cloud_run_v2_job.paper_cycle.name
}

output "trigger_queue_name" {
  description = "Bounded Cloud Tasks queue for operator campaigns."
  value       = google_cloud_tasks_queue.job_trigger.name
}

output "trigger_sa_email" {
  description = "Identity that may execute the cycle job with arg overrides."
  value       = local.trigger_email
}

output "consumer_service_url" {
  description = "Base URL of the paper-only consumer service."
  value       = local.consumer_uri
}

output "consumer_ledger_bucket_name" {
  description = "Consumer-owned ledger bucket, separate from journals."
  value       = local.consumer_bucket_name
}

output "consumer_subscription_name" {
  description = "Pub/Sub push subscription delivering trade plans to the consumer."
  value       = local.consumer_subscription_name
}

output "consumer_dead_letter_topic_name" {
  description = "Dead-letter topic for failed consumer deliveries."
  value       = local.dead_letter_name
}

output "consumer_sweep_job_name" {
  description = "Cloud Scheduler job driving the consumer sweep."
  value       = local.consumer_sweep_job_name
}

output "observer_service_url" {
  description = "Base URL of the read-only archive observer."
  value       = try(google_cloud_run_v2_service.observer[0].uri, "")
}

output "observer_runtime_email" {
  description = "Observer runtime identity (jobUser + dataset reader only)."
  value       = local.observer_email
}

output "event_archive_table" {
  description = "Fully qualified BigQuery table receiving archived events."
  value       = local.feature_topic ? "${var.project_id}.${local.archive_dataset_id}.${local.archive_table_id}" : ""
}

output "event_archive_subscription" {
  description = "Pub/Sub BigQuery subscription writing the archive."
  value       = local.feature_topic ? "${var.pubsub_topic}-bigquery" : ""
}

output "scan_schedule_name" {
  description = "Cloud Scheduler job driving scheduled opportunity scanning."
  value       = var.scan_schedule != "" ? "chrysopoeia-scan-${var.operator}" : ""
}

output "scan_workflow_name" {
  description = "Workflow requesting one scan paper-cycle execution per tick."
  value       = var.scan_schedule != "" ? local.scan_workflow_name : ""
}
