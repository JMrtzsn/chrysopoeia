# Bounded job-trigger queue: operator campaigns enqueue individually scheduled
# HTTP tasks that execute the paper-cycle job with per-task journal args. The
# queue is inert and free when empty; pausing or purging it stops a campaign.
resource "google_cloud_tasks_queue" "job_trigger" {
  project  = var.project_id
  location = var.region
  name     = "chrysopoeia-trigger-${var.operator}"

  depends_on = [google_project_service.cloudtasks]
}

# Scheduled opportunity scanning: Cloud Scheduler invokes the workflow, which
# computes a fresh minute-keyed journal name per tick and requests one
# paper-cycle job execution with args overridden per execution. The workflow
# runtime identity is the least-privilege trigger identity.
resource "google_workflows_workflow" "scan" {
  count               = var.scan_schedule != "" ? 1 : 0
  project             = var.project_id
  region              = var.region
  name                = local.scan_workflow_name
  service_account     = local.trigger_email
  deletion_protection = false

  source_contents = <<-WF
main:
  steps:
    - init:
        assign:
          - stamp: $${time.format(sys.now())}
    - run:
        call: googleapis.run.v2.projects.locations.jobs.run
        args:
          name: "projects/${var.project_id}/locations/${var.region}/jobs/chrysopoeia-cycle-${var.operator}"
          body:
            overrides:
              containerOverrides:
                - args:
                    - run
                    - --journal
                    - $${"/mnt/journal/esports-" + stamp}
          connector_params:
            skip_polling: True
        result: accepted
    - done:
        return: $${accepted.name}
WF

  depends_on = [google_project_service.workflows]
}

# Workflows executes.create accepts OAuth2 access tokens only; the documented
# scheduler integration uses one (not OIDC), with the octet-stream content type.
resource "google_cloud_scheduler_job" "cycle_scan" {
  count            = var.scan_schedule != "" ? 1 : 0
  project          = var.project_id
  region           = var.region
  name             = "chrysopoeia-scan-${var.operator}"
  schedule         = var.scan_schedule
  time_zone        = "Etc/UTC"
  paused           = var.scan_paused
  attempt_deadline = "120s"

  http_target {
    uri         = local.scan_workflow_uri
    http_method = "POST"

    headers = {
      "Content-Type" = "application/octet-stream"
      "User-Agent"   = "Google-Cloud-Scheduler"
    }

    body = base64encode(jsonencode({ argument = "{}" }))

    oauth_token {
      service_account_email = local.trigger_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_project_service.workflows,
    google_workflows_workflow.scan,
  ]
}

# Sweep scheduler name matches the Pulumi auto-named live resource.
resource "google_cloud_scheduler_job" "consumer_sweep" {
  count     = var.consumer_image_digest != "" ? 1 : 0
  project   = var.project_id
  region    = var.region
  name      = local.consumer_sweep_job_name
  schedule  = var.consumer_sweep_schedule
  time_zone = "Etc/UTC"

  http_target {
    uri         = "${local.consumer_uri}/sweep"
    http_method = "POST"

    oidc_token {
      service_account_email = local.invoker_email
      audience              = local.consumer_uri
    }
  }

  depends_on = [google_project_service.cloudscheduler]
}
