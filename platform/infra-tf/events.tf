# The event topic and its subscriptions. The topic is registered under its
# full resource path, exactly like the Pulumi program does today.
resource "google_pubsub_topic" "trade_plans" {
  count      = local.feature_topic ? 1 : 0
  project    = var.project_id
  name       = var.pubsub_topic
  depends_on = [google_project_service.pubsub]
}

resource "google_pubsub_topic_iam_member" "runner_publisher" {
  count   = local.feature_topic ? 1 : 0
  project = var.project_id
  topic   = local.topic_name
  role    = "roles/pubsub.publisher"
  member  = local.runner_member
}

# BigQuery subscription writes the raw event archive; the writer IAM on the
# table must exist before the subscription.
resource "google_pubsub_subscription" "event_archive" {
  count                      = local.feature_topic ? 1 : 0
  project                    = var.project_id
  name                       = "${var.pubsub_topic}-bigquery"
  topic                      = local.topic_id
  message_retention_duration = "2678400s"

  expiration_policy {
    ttl = "" # never expires
  }

  bigquery_config {
    table            = "${var.project_id}.${local.archive_dataset_id}.${local.archive_table_id}"
    write_metadata   = true
    use_topic_schema = false
    use_table_schema = false
  }

  depends_on = [google_bigquery_table_iam_member.archive_writer]
}

# Consumer dead-letter topic: Pub/Sub's own service agent publishes and
# subscribes there on final delivery failure.
resource "google_pubsub_topic" "dead_letter" {
  count      = var.consumer_image_digest != "" ? 1 : 0
  project    = var.project_id
  name       = "${var.pubsub_topic}-dead-letter"
  depends_on = [google_project_service.pubsub]
}

resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  count   = var.consumer_image_digest != "" ? 1 : 0
  project = var.project_id
  topic   = local.dead_letter_name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent_member
}

locals {
  dead_letter_name = try(google_pubsub_topic.dead_letter[0].name, "")
}

# Push subscription with OIDC-authenticated delivery, 10-attempt retry, and a
# dead-letter topic. Name matches the Pulumi auto-named live resource.
resource "google_pubsub_subscription" "paper_consumer" {
  count                      = var.consumer_image_digest != "" ? 1 : 0
  project                    = var.project_id
  name                       = "paper-consumer-a8db57a"
  topic                      = local.topic_id
  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"
  filter                     = "attributes.record_type = \"trade_plan_ready\""

  push_config {
    push_endpoint = "${local.consumer_uri}/push"

    oidc_token {
      service_account_email = local.invoker_email
      audience              = local.consumer_uri
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = local.dead_letter_id
    max_delivery_attempts = 10
  }

  depends_on = [
    google_service_account_iam_member.pubsub_invoker_token_creator,
    google_cloud_run_v2_service_iam_member.consumer_invoker,
    google_pubsub_topic_iam_member.dead_letter_publisher,
  ]
}

resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  count        = var.consumer_image_digest != "" ? 1 : 0
  project      = var.project_id
  subscription = local.consumer_subscription_name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent_member
}

# Retention copy of dead letters for manual inspection.
resource "google_pubsub_subscription" "dead_letter_retention" {
  count                      = var.consumer_image_digest != "" ? 1 : 0
  project                    = var.project_id
  name                       = "consumer-dead-letter-retention-7304458"
  topic                      = local.dead_letter_id
  message_retention_duration = "604800s"

  expiration_policy {
    ttl = "2678400s"
  }
}
