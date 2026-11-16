# Import blocks for every live local-dev resource (roadmap item 12d).
# IDs collected from the live project on 2026-11-16. This file is deleted
# after cutover; the plan is read-only until an operator-approved apply.
import {
  to = google_project_service.run
  id = "PROJECT_ID/run.googleapis.com"
}
import {
  to = google_project_service.artifactregistry
  id = "PROJECT_ID/artifactregistry.googleapis.com"
}
import {
  to = google_project_service.cloudtasks
  id = "PROJECT_ID/cloudtasks.googleapis.com"
}
import {
  to = google_project_service.pubsub[0]
  id = "PROJECT_ID/pubsub.googleapis.com"
}
import {
  to = google_project_service.bigquery[0]
  id = "PROJECT_ID/bigquery.googleapis.com"
}
import {
  to = google_project_service.bigquerydatatransfer[0]
  id = "PROJECT_ID/bigquerydatatransfer.googleapis.com"
}
import {
  to = google_project_service.cloudscheduler[0]
  id = "PROJECT_ID/cloudscheduler.googleapis.com"
}
import {
  to = google_project_service.workflows[0]
  id = "PROJECT_ID/workflows.googleapis.com"
}
import {
  to = google_project_service.monitoring[0]
  id = "PROJECT_ID/monitoring.googleapis.com"
}
import {
  to = google_project_service.billingbudgets[0]
  id = "PROJECT_ID/billingbudgets.googleapis.com"
}

import {
  to = google_service_account.runner
  id = "chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_service_account.trigger
  id = "chrysopoeia-trigger-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_service_account.observer[0]
  id = "chrysopoeia-observer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_service_account.consumer[0]
  id = "chrysopoeia-consumer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_service_account.invoker[0]
  id = "chrysopoeia-invoker-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_service_account.transfer_runner[0]
  id = "chrysopoeia-transfer-local@PROJECT_ID.iam.gserviceaccount.com"
}

import {
  to = google_project_iam_custom_role.job_trigger
  id = "projects/PROJECT_ID/roles/chrysopoeia_job_trigger_local"
}

import {
  to = google_project_iam_member.job_trigger_executor
  id = "projects/PROJECT_ID projects/PROJECT_ID/roles/chrysopoeia_job_trigger_local serviceAccount:chrysopoeia-trigger-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.runner_vertex_user
  id = "projects/PROJECT_ID roles/aiplatform.user serviceAccount:chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.scan_workflow_invoker[0]
  id = "projects/PROJECT_ID roles/workflows.invoker serviceAccount:chrysopoeia-trigger-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.transfer_job_user[0]
  id = "projects/PROJECT_ID roles/bigquery.jobUser serviceAccount:chrysopoeia-transfer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.runner_job_user[0]
  id = "projects/PROJECT_ID roles/bigquery.jobUser serviceAccount:chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.observer_job_user[0]
  id = "projects/PROJECT_ID roles/bigquery.jobUser serviceAccount:chrysopoeia-observer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_project_iam_member.transfer_config_creator[0]
  id = "projects/PROJECT_ID roles/iam.serviceAccountUser user:johannes.mauritzson@gmail.com"
}

import {
  to = google_service_account_iam_member.tasks_agent_token_creator
  id = "projects/PROJECT_ID/serviceAccounts/chrysopoeia-trigger-local@PROJECT_ID.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:service-PROJECT_NUMBER@gcp-sa-cloudtasks.iam.gserviceaccount.com"
}
import {
  to = google_service_account_iam_member.scan_scheduler_token_creator[0]
  id = "projects/PROJECT_ID/serviceAccounts/chrysopoeia-trigger-local@PROJECT_ID.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}
import {
  to = google_service_account_iam_member.transfer_token_creator[0]
  id = "projects/PROJECT_ID/serviceAccounts/chrysopoeia-transfer-local@PROJECT_ID.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:service-PROJECT_NUMBER@gcp-sa-bigquerydatatransfer.iam.gserviceaccount.com"
}
import {
  to = google_service_account_iam_member.pubsub_invoker_token_creator[0]
  id = "projects/PROJECT_ID/serviceAccounts/chrysopoeia-invoker-local@PROJECT_ID.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com"
}

import {
  to = google_storage_bucket.journals
  id = "PROJECT_ID-chrs-journals-local"
}
import {
  to = google_storage_bucket.consumer_ledger[0]
  id = "PROJECT_ID-chrs-consumer-local"
}
import {
  to = google_storage_bucket_iam_member.runner_object_admin
  id = "b/PROJECT_ID-chrs-journals-local roles/storage.objectAdmin serviceAccount:chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_storage_bucket_iam_member.consumer_object_admin[0]
  id = "b/PROJECT_ID-chrs-consumer-local roles/storage.objectAdmin serviceAccount:chrysopoeia-consumer-local@PROJECT_ID.iam.gserviceaccount.com"
}

import {
  to = google_artifact_registry_repository.images
  id = "projects/PROJECT_ID/locations/us-central1/repositories/chrysopoeia"
}
import {
  to = google_artifact_registry_repository_iam_member.runner_reader
  id = "projects/PROJECT_ID/locations/us-central1/repositories/chrysopoeia roles/artifactregistry.reader serviceAccount:chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}

import {
  to = google_cloud_run_v2_job.paper_cycle
  id = "projects/PROJECT_ID/locations/us-central1/jobs/chrysopoeia-cycle-local"
}
import {
  to = google_cloud_run_v2_service.observer[0]
  id = "projects/PROJECT_ID/locations/us-central1/services/chrysopoeia-observer-local"
}
import {
  to = google_cloud_run_v2_service.consumer[0]
  id = "projects/PROJECT_ID/locations/us-central1/services/chrysopoeia-consumer-local"
}
import {
  to = google_cloud_run_v2_service_iam_member.observer_invoker[0]
  id = "projects/PROJECT_ID/locations/us-central1/services/chrysopoeia-observer-local roles/run.invoker user:johannes.mauritzson@gmail.com"
}
import {
  to = google_cloud_run_v2_service_iam_member.consumer_invoker[0]
  id = "projects/PROJECT_ID/locations/us-central1/services/chrysopoeia-consumer-local roles/run.invoker serviceAccount:chrysopoeia-invoker-local@PROJECT_ID.iam.gserviceaccount.com"
}

import {
  to = google_pubsub_topic.trade_plans[0]
  id = "projects/PROJECT_ID/topics/chrysopoeia-events"
}
import {
  to = google_pubsub_topic_iam_member.runner_publisher[0]
  id = "projects/PROJECT_ID/topics/chrysopoeia-events roles/pubsub.publisher serviceAccount:chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_pubsub_topic.dead_letter[0]
  id = "projects/PROJECT_ID/topics/chrysopoeia-events-dead-letter"
}
import {
  to = google_pubsub_topic_iam_member.dead_letter_publisher[0]
  id = "projects/PROJECT_ID/topics/chrysopoeia-events-dead-letter roles/pubsub.publisher serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com"
}
import {
  to = google_pubsub_topic_iam_member.consumer_outcome_publisher[0]
  id = "projects/PROJECT_ID/topics/chrysopoeia-events roles/pubsub.publisher serviceAccount:chrysopoeia-consumer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_pubsub_subscription.event_archive[0]
  id = "projects/PROJECT_ID/subscriptions/chrysopoeia-events-bigquery"
}
import {
  to = google_pubsub_subscription.paper_consumer[0]
  id = "projects/PROJECT_ID/subscriptions/paper-consumer-a8db57a"
}
import {
  to = google_pubsub_subscription_iam_member.dead_letter_subscriber[0]
  id = "projects/PROJECT_ID/subscriptions/paper-consumer-a8db57a roles/pubsub.subscriber serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com"
}
import {
  to = google_pubsub_subscription.dead_letter_retention[0]
  id = "projects/PROJECT_ID/subscriptions/consumer-dead-letter-retention-7304458"
}

import {
  to = google_bigquery_dataset.event_archive[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local"
}
import {
  to = google_bigquery_table.raw_events[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local/tables/raw_events"
}
import {
  to = google_bigquery_table.open_positions[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local/tables/open_positions"
}
import {
  to = google_bigquery_table_iam_member.archive_writer[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local/tables/raw_events roles/bigquery.dataEditor serviceAccount:service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com"
}
import {
  to = google_bigquery_table_iam_member.transfer_projection_writer[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local/tables/open_positions roles/bigquery.dataEditor serviceAccount:chrysopoeia-transfer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_bigquery_dataset_iam_member.transfer_data_viewer[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local roles/bigquery.dataViewer serviceAccount:chrysopoeia-transfer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_bigquery_dataset_iam_member.observer_data_viewer[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local roles/bigquery.dataViewer serviceAccount:chrysopoeia-observer-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_bigquery_dataset_iam_member.runner_data_viewer[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local roles/bigquery.dataViewer serviceAccount:chrysopoeia-runner-local@PROJECT_ID.iam.gserviceaccount.com"
}
import {
  to = google_bigquery_data_transfer_config.open_positions_refresh[0]
  id = "projects/PROJECT_NUMBER/locations/us-central1/transferConfigs/6af90310-0000-2a7f-b93d-14223bb0999a"
}

import {
  to = google_cloud_tasks_queue.job_trigger
  id = "projects/PROJECT_ID/locations/us-central1/queues/chrysopoeia-trigger-local"
}
import {
  to = google_workflows_workflow.scan[0]
  id = "projects/PROJECT_ID/locations/us-central1/workflows/chrysopoeia-scan-local"
}
import {
  to = google_cloud_scheduler_job.cycle_scan[0]
  id = "projects/PROJECT_ID/locations/us-central1/jobs/chrysopoeia-scan-local"
}
import {
  to = google_cloud_scheduler_job.consumer_sweep[0]
  id = "projects/PROJECT_ID/locations/us-central1/jobs/consumer-sweep-916f9e1"
}

import {
  to = google_logging_metric.sweep_errors[0]
  id = "PROJECT_ID chrysopoeia_sweep_errors_local"
}
import {
  to = google_logging_metric.task_timeouts[0]
  id = "PROJECT_ID chrysopoeia_task_timeouts_local"
}
import {
  to = google_logging_metric.scheduler_failures[0]
  id = "PROJECT_ID chrysopoeia_scheduler_failures_local"
}
import {
  to = google_monitoring_notification_channel.health_email[0]
  id = "projects/PROJECT_ID/notificationChannels/11730879466731657335"
}
import {
  to = google_monitoring_alert_policy.sweep_errors[0]
  id = "projects/PROJECT_ID/alertPolicies/9263187485625505386"
}
import {
  to = google_monitoring_alert_policy.task_timeouts[0]
  id = "projects/PROJECT_ID/alertPolicies/9263187485625507683"
}
import {
  to = google_monitoring_alert_policy.scheduler_failures[0]
  id = "projects/PROJECT_ID/alertPolicies/3968063247948612047"
}
import {
  to = google_monitoring_dashboard.health[0]
  id = "projects/${local.project_number}/dashboards/841758d8-acb6-48f2-8291-1d1817fe7682"
}

import {
  to = google_billing_budget.spend[0]
  id = "BILLING_ACCOUNT_ID/567d69f3-a8cb-4b10-9344-91e5f56611d1"
}
