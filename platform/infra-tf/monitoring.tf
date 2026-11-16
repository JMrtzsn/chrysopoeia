# Health monitoring: log-based metrics over failure signatures we have already
# hit (consumer sweep errors, cycle task timeouts, scheduler attempt failures),
# email alerts for each, and a Cloud Monitoring dashboard. Overnight silence is
# by design (no ticks are scheduled then), so alerts key on error events.
locals {
  sweep_errors_filter = format(
    "resource.type=\"cloud_run_revision\" resource.labels.service_name=\"chrysopoeia-consumer-%s\" severity>=ERROR",
    var.operator,
  )
  task_timeouts_filter = format(
    "resource.type=\"cloud_run_job\" resource.labels.job_name=\"chrysopoeia-cycle-%s\" severity>=ERROR \"maximum timeout\"",
    var.operator,
  )
  scheduler_failures_filter = "resource.type=\"cloud_scheduler_job\" httpRequest.status>=500"

  sweep_errors_metric       = replace("chrysopoeia_sweep_errors_${var.operator}", "-", "_")
  task_timeouts_metric      = replace("chrysopoeia_task_timeouts_${var.operator}", "-", "_")
  scheduler_failures_metric = replace("chrysopoeia_scheduler_failures_${var.operator}", "-", "_")
}

resource "google_logging_metric" "sweep_errors" {
  count       = var.health_alert_email != "" ? 1 : 0
  project     = var.project_id
  name        = local.sweep_errors_metric
  description = local.sweep_errors_filter
  filter      = local.sweep_errors_filter

  depends_on = [google_project_service.monitoring]
}

resource "google_logging_metric" "task_timeouts" {
  count       = var.health_alert_email != "" ? 1 : 0
  project     = var.project_id
  name        = local.task_timeouts_metric
  description = local.task_timeouts_filter
  filter      = local.task_timeouts_filter

  depends_on = [google_project_service.monitoring]
}

resource "google_logging_metric" "scheduler_failures" {
  count       = var.health_alert_email != "" ? 1 : 0
  project     = var.project_id
  name        = local.scheduler_failures_metric
  description = local.scheduler_failures_filter
  filter      = local.scheduler_failures_filter

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_notification_channel" "health_email" {
  count        = var.health_alert_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "Chrysopoeia health (${var.operator})"
  type         = "email"

  labels = {
    email_address = var.health_alert_email
  }

  depends_on = [google_project_service.monitoring]
}

# Threshold alerts: sweep errors page on any sustained failure; two
# consecutive hours of tick timeouts means the profile needs attention.
resource "google_monitoring_alert_policy" "sweep_errors" {
  count        = var.health_alert_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "Chrysopoeia consumer sweep errors (${var.operator})"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.health_email[0].id,
  ]

  conditions {
    display_name = "consumer sweep errors"

    condition_threshold {
      filter = format(
        "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/%s\"",
        local.sweep_errors_metric,
      )
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "600s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_alert_policy" "task_timeouts" {
  count        = var.health_alert_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "Chrysopoeia cycle task timeouts (${var.operator})"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.health_email[0].id,
  ]

  conditions {
    display_name = "cycle task timeouts"

    condition_threshold {
      filter = format(
        "resource.type=\"cloud_run_job\" AND metric.type=\"logging.googleapis.com/user/%s\"",
        local.task_timeouts_metric,
      )
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "3600s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_alert_policy" "scheduler_failures" {
  count        = var.health_alert_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "Chrysopoeia scheduler attempt failures (${var.operator})"
  combiner     = "OR"

  notification_channels = [
    google_monitoring_notification_channel.health_email[0].id,
  ]

  conditions {
    display_name = "scheduler attempt failures"

    condition_threshold {
      filter = format(
        "resource.type=\"cloud_scheduler_job\" AND metric.type=\"logging.googleapis.com/user/%s\"",
        local.scheduler_failures_metric,
      )
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "1800s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }

      trigger {
        count = 1
      }
    }
  }

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_dashboard" "health" {
  count = var.health_alert_email != "" ? 1 : 0
  # Live dashboards key their identity on the project NUMBER.
  project = local.project_number

  # Mirrors the live dashboard verbatim (including etag and system-set
  # plotType/targetAxis) so the import produces no drift.
  dashboard_json = <<-DASH
{
  "displayName": "Chrysopoeia health (local)",
  "etag": "eda4221bda1f0aa2a48f82900c2db6bd",
  "gridLayout": {
    "widgets": [
      {
        "title": "Consumer sweep errors (rate)",
        "xyChart": {
          "dataSets": [
            {
              "plotType": "LINE",
              "targetAxis": "Y1",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "aggregation": {
                    "alignmentPeriod": "300s",
                    "perSeriesAligner": "ALIGN_RATE"
                  },
                  "filter": "resource.type=\"cloud_run_revision\" AND metric.type=\"logging.googleapis.com/user/chrysopoeia_sweep_errors_local\""
                }
              }
            }
          ],
          "timeshiftDuration": "86400s"
        }
      },
      {
        "title": "Cycle task timeouts (rate)",
        "xyChart": {
          "dataSets": [
            {
              "plotType": "LINE",
              "targetAxis": "Y1",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "aggregation": {
                    "alignmentPeriod": "300s",
                    "perSeriesAligner": "ALIGN_RATE"
                  },
                  "filter": "resource.type=\"cloud_run_job\" AND metric.type=\"logging.googleapis.com/user/chrysopoeia_task_timeouts_local\""
                }
              }
            }
          ],
          "timeshiftDuration": "86400s"
        }
      },
      {
        "title": "Scheduler attempt failures (rate)",
        "xyChart": {
          "dataSets": [
            {
              "plotType": "LINE",
              "targetAxis": "Y1",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "aggregation": {
                    "alignmentPeriod": "300s",
                    "perSeriesAligner": "ALIGN_RATE"
                  },
                  "filter": "resource.type=\"cloud_scheduler_job\" AND metric.type=\"logging.googleapis.com/user/chrysopoeia_scheduler_failures_local\""
                }
              }
            }
          ],
          "timeshiftDuration": "86400s"
        }
      }
    ]
  },
  "name": "projects/${local.project_number}/dashboards/841758d8-acb6-48f2-8291-1d1817fe7682"
}
DASH

  depends_on = [google_project_service.monitoring]
}
