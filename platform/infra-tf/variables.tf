variable "project_id" {
  type        = string
  description = "Target GCP project for every resource in this root."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "GCP region for regional resources (buckets, jobs, datasets)."
}

variable "operator" {
  type        = string
  default     = "local"
  description = "Instance suffix used in every resource name (e.g. local)."
}

# Harness invocation inputs only; operating settings are the bundled
# platform.toml profile, never CLI flags.
variable "job_args" {
  type        = list(string)
  default     = ["run", "--journal", "/mnt/journal/run"]
  description = "Harness CLI invocation for the paper-cycle job container."
}

# Harness image pin: name@sha256:... (never :latest on a live stack).
# Empty falls back to the registry :latest alias, which is only a build tag.
variable "image_digest" {
  type        = string
  default     = ""
  description = "Pinned harness image digest; empty uses the registry :latest build tag."
}

# Every optional feature below mirrors one Pulumi config key in infra/__main__.py.
variable "pubsub_topic" {
  type        = string
  default     = ""
  description = "Full topic path (projects/<project>/topics/<topic>) for the event sink; empty disables all event/archive resources."
}

variable "consumer_image_digest" {
  type    = string
  default = ""

  validation {
    condition     = var.consumer_image_digest == "" || var.pubsub_topic != ""
    error_message = "The consumer requires a configured pubsub_topic."
  }

  description = "Pinned consumer image digest; empty disables all consumer resources."
}

variable "consumer_sweep_schedule" {
  type        = string
  default     = "* * * * *"
  description = "Cron (UTC) for the consumer settlement sweep."
}

variable "context_history_enabled" {
  type    = bool
  default = false

  validation {
    condition     = !var.context_history_enabled || var.pubsub_topic != ""
    error_message = "Context history requires a configured pubsub_topic."
  }

  description = "Grants the runner read-only access to the raw-events archive."
}

variable "observer_image_digest" {
  type    = string
  default = ""

  validation {
    condition     = var.observer_image_digest == "" || (var.pubsub_topic != "" && var.observer_invoker_member != "")
    error_message = "The observer requires a configured pubsub_topic and a private observer_invoker_member."
  }

  description = "Pinned observer image digest; empty disables all observer resources."
}

variable "observer_invoker_member" {
  type    = string
  default = ""

  validation {
    condition     = !contains(["allUsers", "allAuthenticatedUsers"], var.observer_invoker_member)
    error_message = "The observer invoker must be a private identity, never allUsers or allAuthenticatedUsers."
  }

  description = "Private IAM member allowed to invoke the observer service."
}

variable "scan_schedule" {
  type        = string
  default     = ""
  description = "Cron (UTC) for scheduled opportunity scanning; empty disables the workflow and scheduler."
}

variable "scan_paused" {
  type        = bool
  default     = false
  description = "Deploy the scan schedule paused; enabling it is an explicit config change."
}

variable "billing_account_id" {
  type        = string
  default     = ""
  description = "Billing account for the native monthly budget."
}

variable "budget_amount_usd" {
  type    = number
  default = 0

  validation {
    condition     = var.budget_amount_usd == 0 || var.billing_account_id != ""
    error_message = "budget_amount_usd requires a configured billing_account_id."
  }

  description = "Monthly budget amount; zero (default) deploys no budget."
}

variable "budget_currency" {
  type        = string
  default     = "SEK"
  description = "Currency of the budget amount; must match the billing account currency."
}

variable "health_alert_email" {
  type        = string
  default     = ""
  description = "Alert email address; empty disables log metrics, alerts, and the dashboard."
}
