# Native billing budget on the project (billing-domain alert only). The
# billing account currency must match the amount's currency.
resource "google_billing_budget" "spend" {
  count           = var.budget_amount_usd > 0 ? 1 : 0
  billing_account = var.billing_account_id
  display_name    = "Chrysopoeia spend budget (${var.operator})"

  budget_filter {
    projects = ["projects/${local.project_number}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = var.budget_amount_usd
    }
  }

  threshold_rules {
    threshold_percent = 0.5
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 0.9
    spend_basis       = "CURRENT_SPEND"
  }

  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  depends_on = [google_project_service.billingbudgets]
}
