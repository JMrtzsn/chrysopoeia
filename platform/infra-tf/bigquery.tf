# Raw event analytics archive. It is never an authoritative financial ledger:
# datasets/tables are analytics copies, and nothing here is authoritative
# storage. The dataset is protected against destruction.
resource "google_bigquery_dataset" "event_archive" {
  count                      = local.feature_topic ? 1 : 0
  project                    = var.project_id
  dataset_id                 = "chrysopoeia_events_${replace(var.operator, "-", "_")}"
  location                   = var.region
  description                = "Raw event analytics archive; not an authoritative financial ledger."
  delete_contents_on_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.bigquery]
}

resource "google_bigquery_table" "raw_events" {
  count               = local.feature_topic ? 1 : 0
  project             = var.project_id
  dataset_id          = local.archive_dataset_id
  table_id            = "raw_events"
  deletion_protection = true

  schema = jsonencode([
    { name = "data", type = "STRING", mode = "NULLABLE" },
    { name = "attributes", type = "STRING", mode = "NULLABLE" },
    { name = "message_id", type = "STRING", mode = "NULLABLE" },
    { name = "publish_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "subscription_name", type = "STRING", mode = "NULLABLE" },
  ])

  time_partitioning {
    type  = "DAY"
    field = "publish_time"
  }

  require_partition_filter = true

  # The raw archive is protected twice: the API-level flag and the local
  # destroy guard, matching the Pulumi program's protect + deletion_protection.
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_table_iam_member" "archive_writer" {
  count      = local.feature_topic ? 1 : 0
  project    = var.project_id
  dataset_id = local.archive_dataset_id
  table_id   = local.archive_table_id
  role       = "roles/bigquery.dataEditor"
  member     = local.pubsub_agent_member
}

# Open-positions projection: a derived, rebuildable read model over the
# archive, refreshed by a scheduled query. Never authoritative; deletion
# loses nothing.
resource "google_bigquery_table" "open_positions" {
  count               = local.feature_topic ? 1 : 0
  project             = var.project_id
  dataset_id          = local.archive_dataset_id
  table_id            = "open_positions"
  deletion_protection = true

  schema = jsonencode([
    { name = "trade_plan_event_id", type = "STRING", mode = "NULLABLE" },
    { name = "profile_id", type = "STRING", mode = "NULLABLE" },
    { name = "profile_version", type = "INT64", mode = "NULLABLE" },
    { name = "market_end", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "plan_created_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "settled_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "pnl", type = "FLOAT64", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_dataset_iam_member" "transfer_data_viewer" {
  count      = local.feature_topic ? 1 : 0
  project    = var.project_id
  dataset_id = local.archive_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = local.transfer_member
}

resource "google_bigquery_table_iam_member" "transfer_projection_writer" {
  count      = local.feature_topic ? 1 : 0
  project    = var.project_id
  dataset_id = local.archive_dataset_id
  table_id   = local.open_positions_id
  role       = "roles/bigquery.dataEditor"
  member     = local.transfer_member
}

resource "google_bigquery_dataset_iam_member" "observer_data_viewer" {
  count      = var.observer_image_digest != "" ? 1 : 0
  project    = var.project_id
  dataset_id = local.archive_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = local.observer_member
}

resource "google_bigquery_dataset_iam_member" "runner_data_viewer" {
  count      = var.context_history_enabled && local.feature_topic ? 1 : 0
  project    = var.project_id
  dataset_id = local.archive_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = local.runner_member
}

# Atomic full rebuild: replaying the archive re-derives every row, so the
# projection stays a pure read model rather than incrementally accreted state.
# The `params.query` string formatting is a known provider-quirk diff
# (roadmap 12d ghost-diff allowance list).
resource "google_bigquery_data_transfer_config" "open_positions_refresh" {
  count          = local.feature_topic ? 1 : 0
  project        = var.project_id
  location       = var.region
  data_source_id = "scheduled_query"
  display_name   = "open-positions-refresh"
  schedule       = "every 15 minutes"

  # The live config runs as its owner (the transfer identity, via the
  # operator's serviceAccountUser grant at creation). serviceAccount is unset
  # on purpose; recreating this config would re-own it to the operator, which
  # is why the archive resources carry destroy protections instead.

  params = {
    query = chomp(<<-SQL
TRUNCATE TABLE `${var.project_id}.${local.archive_dataset_id}.open_positions`;
INSERT INTO `${var.project_id}.${local.archive_dataset_id}.open_positions` (trade_plan_event_id, profile_id, profile_version, market_end, plan_created_at, status, settled_at, pnl)
WITH parsed AS (
  SELECT SAFE.PARSE_JSON(data) AS payload, publish_time
  FROM `${var.project_id}.${local.archive_dataset_id}.raw_events`
  WHERE publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
    AND publish_time < CURRENT_TIMESTAMP()
    AND data IS NOT NULL
), events AS (
  SELECT payload
  FROM parsed
  WHERE payload IS NOT NULL
    AND JSON_VALUE(payload, '$.event_id') IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_VALUE(payload, '$.record_type'), JSON_VALUE(payload, '$.event_id')
    ORDER BY publish_time DESC
  ) = 1
), plans AS (
  SELECT
    JSON_VALUE(payload, '$.event_id') AS trade_plan_event_id,
    SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) AS plan_created_at,
    SAFE_CAST(JSON_VALUE(payload, '$.market_end') AS TIMESTAMP) AS market_end
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'trade_plan_ready'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) IN (1, 2)
    AND SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) < CURRENT_TIMESTAMP()
), turns AS (
  SELECT
    JSON_VALUE(payload, '$.trade_plan_event_id') AS trade_plan_event_id,
    JSON_VALUE(payload, '$.context.profile_id') AS profile_id,
    SAFE_CAST(JSON_VALUE(payload, '$.context.profile_version') AS INT64) AS profile_version,
    SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) AS created_at
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'turn_outcome'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) IN (3, 4)
    AND SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) < CURRENT_TIMESTAMP()
), turn_context AS (
  SELECT trade_plan_event_id, profile_id, profile_version
  FROM turns
  WHERE trade_plan_event_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY trade_plan_event_id ORDER BY created_at DESC) = 1
), consumer_events AS (
  SELECT
    JSON_VALUE(payload, '$.trade_plan_event_id') AS trade_plan_event_id,
    JSON_VALUE(payload, '$.status') AS status,
    SAFE_CAST(JSON_VALUE(payload, '$.pnl') AS FLOAT64) AS pnl,
    SAFE_CAST(JSON_VALUE(payload, '$.recorded_at') AS TIMESTAMP) AS recorded_at
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'consumer_outcome'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) = 1
    AND SAFE_CAST(JSON_VALUE(payload, '$.recorded_at') AS TIMESTAMP) < CURRENT_TIMESTAMP()
), lifecycle AS (
  SELECT
    trade_plan_event_id,
    LOGICAL_OR(status = 'filled') AS was_filled,
    LOGICAL_OR(status = 'rejected') AS was_rejected,
    ARRAY_AGG(
      IF(status IN ('closed', 'settled'), STRUCT(recorded_at, pnl), NULL)
      IGNORE NULLS ORDER BY recorded_at DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS final_outcome
  FROM consumer_events
  WHERE trade_plan_event_id IS NOT NULL
  GROUP BY trade_plan_event_id
)
SELECT
  p.trade_plan_event_id,
  tc.profile_id,
  tc.profile_version,
  p.market_end,
  p.plan_created_at,
  CASE
    WHEN l.was_filled THEN IF(l.final_outcome IS NULL, 'open', 'settled')
    WHEN l.was_rejected THEN 'rejected'
    ELSE 'pending'
  END AS status,
  l.final_outcome.recorded_at AS settled_at,
  l.final_outcome.pnl AS pnl
FROM plans p
LEFT JOIN turn_context tc USING (trade_plan_event_id)
LEFT JOIN lifecycle l USING (trade_plan_event_id)
SQL
    )
  }

  depends_on = [
    google_bigquery_table.open_positions,
    google_project_iam_member.transfer_job_user,
  ]
}
