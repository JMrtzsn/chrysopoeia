resource "google_storage_bucket" "journals" {
  project = var.project_id
  name = format(
    "%.22s-chrs-journals-%.8s",
    lower(var.project_id),
    local.operator_lower,
  )
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}

resource "google_storage_bucket_iam_member" "runner_object_admin" {
  bucket = google_storage_bucket.journals.name
  role   = "roles/storage.objectAdmin"
  member = local.runner_member
}

# Consumer ledger bucket: separate from journals by design; the consumer owns
# its own ledger and the harness never reads it.
resource "google_storage_bucket" "consumer_ledger" {
  count   = var.consumer_image_digest != "" ? 1 : 0
  project = var.project_id
  name = format(
    "%.20s-chrs-consumer-%.8s",
    lower(var.project_id),
    local.operator_lower,
  )
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }
}

resource "google_storage_bucket_iam_member" "consumer_object_admin" {
  count  = var.consumer_image_digest != "" ? 1 : 0
  bucket = local.consumer_bucket_name
  role   = "roles/storage.objectAdmin"
  member = local.consumer_member
}
