# Gate roles do not overlap: tflint = correctness, trivy = security,
# conftest (added at 12c) = operator policy.
plugin "terraform" {
  enabled = true
}

# The per-concern file layout (roadmap item 12a) replaces a main.tf
# entrypoint by design; this is a single root, not a reusable module.
rule "terraform_standard_module_structure" {
  enabled = false
}

plugin "google" {
  enabled = true
  version = "0.41.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}

rule "terraform_deprecated_index" {
  enabled = true
}

rule "terraform_required_providers" {
  enabled = true
}

rule "terraform_unused_declarations" {
  enabled = true
}

rule "terraform_typed_variables" {
  enabled = true
}
