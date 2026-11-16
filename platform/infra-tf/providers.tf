provider "google" {
  project = var.project_id
  region  = var.region
  # The provider does not read the ADC quota project (b/360405077), so
  # client-based APIs (billingbudgets) need this pairing explicitly.
  user_project_override = true
  billing_project       = var.project_id
}
