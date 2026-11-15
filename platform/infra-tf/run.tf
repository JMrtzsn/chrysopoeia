resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "chrysopoeia"
  format        = "DOCKER"

  depends_on = [
    google_project_service.run,
    google_project_service.artifactregistry,
  ]
}

resource "google_artifact_registry_repository_iam_member" "runner_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.reader"
  member     = local.runner_member
}

# One Cloud Run job executes one harnessed paper cycle per invocation; every
# execution bills only its own vCPU seconds (zero idle cost).
resource "google_cloud_run_v2_job" "paper_cycle" {
  project             = var.project_id
  location            = var.region
  name                = "chrysopoeia-cycle-${var.operator}"
  launch_stage        = "GA"
  deletion_protection = false

  template {
    task_count = 1

    template {
      timeout         = "900s"
      max_retries     = 0
      service_account = local.runner_email

      containers {
        name  = "chrysopoeia"
        image = local.harness_image
        args  = var.job_args

        dynamic "env" {
          for_each = local.cycle_envs
          content {
            name  = env.value.name
            value = env.value.value
          }
        }

        resources {
          limits = {
            memory = "512Mi"
            cpu    = "1"
          }
        }

        volume_mounts {
          name       = "journal"
          mount_path = "/mnt/journal"
        }
      }

      volumes {
        name = "journal"

        gcs {
          bucket    = google_storage_bucket.journals.name
          read_only = false
        }
      }
    }
  }

  depends_on = [google_project_service.run]
}

locals {
  cycle_envs = concat(
    [
      { name = "CHRYSOPOEIA_CONFIG", value = "/etc/chrysopoeia-platform.toml" },
      { name = "GOOGLE_GENAI_USE_VERTEXAI", value = "TRUE" },
      { name = "GOOGLE_CLOUD_PROJECT", value = var.project_id },
      { name = "GOOGLE_CLOUD_LOCATION", value = var.region },
      { name = "CHRYSOPOEIA_CONTEXT_CATALOG", value = "/mnt/journal/context_profiles.jsonl" },
    ],
    local.feature_topic ? [
      { name = "CHRYSOPOEIA_EVENT_SINK", value = "pubsub:${var.pubsub_topic}" },
    ] : [],
    var.context_history_enabled && local.feature_topic ? [
      {
        name  = "CHRYSOPOEIA_HISTORY_TABLE"
        value = "${var.project_id}.${local.archive_dataset_id}.${local.archive_table_id}"
      },
      { name = "CHRYSOPOEIA_HISTORY_LOCATION", value = var.region },
    ] : [],
  )
}

# Read-only archive Observer: private by IAM, no ledger, storage, or publishing.
resource "google_cloud_run_v2_service" "observer" {
  count               = var.observer_image_digest != "" ? 1 : 0
  project             = var.project_id
  location            = var.region
  name                = "chrysopoeia-observer-${var.operator}"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = local.observer_email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.observer_image_digest

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "OBSERVER_ARCHIVE_TABLE"
        value = "${var.project_id}.${local.archive_dataset_id}.${local.archive_table_id}"
      }

      env {
        name  = "OBSERVER_BIGQUERY_LOCATION"
        value = var.region
      }
    }
  }

  depends_on = [google_project_service.run]
}

resource "google_cloud_run_v2_service_iam_member" "observer_invoker" {
  count    = var.observer_image_digest != "" ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = local.observer_service_name
  role     = "roles/run.invoker"
  member   = var.observer_invoker_member
}

locals {
  observer_service_name = try(google_cloud_run_v2_service.observer[0].name, "")
}

# Paper-only consumer service: strict schema ingress, its own ledger bucket.
resource "google_cloud_run_v2_service" "consumer" {
  count               = var.consumer_image_digest != "" ? 1 : 0
  project             = var.project_id
  location            = var.region
  name                = "chrysopoeia-consumer-${var.operator}"
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = local.consumer_email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.consumer_image_digest

      env {
        name  = "CONSUMER_JOURNAL"
        value = "/mnt/consumer/ledger.jsonl"
      }

      env {
        name  = "CHRYSOPOEIA_EVENT_TOPIC"
        value = var.pubsub_topic
      }

      volume_mounts {
        name       = "consumer-ledger"
        mount_path = "/mnt/consumer"
      }
    }

    volumes {
      name = "consumer-ledger"

      gcs {
        bucket    = local.consumer_bucket_name
        read_only = false
      }
    }
  }

  depends_on = [google_project_service.run]
}

resource "google_cloud_run_v2_service_iam_member" "consumer_invoker" {
  count    = var.consumer_image_digest != "" ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = "chrysopoeia-consumer-${var.operator}"
  role     = "roles/run.invoker"
  member   = local.invoker_member
}

locals {
  invoker_member = try("serviceAccount:${google_service_account.invoker[0].email}", "")
}
