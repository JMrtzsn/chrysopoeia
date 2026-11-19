package terraform.plan

# Operator policy for plan gating (roadmap item 12c). Input is the JSON output
# of `terraform show -json tfplan`. Runs offline against fixtures in
# policy/fixtures; against a real saved plan at apply time from 12e on.
import rego.v1

protected contains id if {
	some rc in input.resource_changes
	id := sprintf("%s.%s", [rc.type, rc.name])
	id in {
		"google_storage_bucket.journals",
		"google_storage_bucket.consumer_ledger",
		"google_bigquery_dataset.event_archive",
		"google_bigquery_table.raw_events",
		"google_bigquery_table.open_positions",
	}
}

# Pure destruction of a protected resource.
deny contains msg if {
	some rc in input.resource_changes
	id := sprintf("%s.%s", [rc.type, rc.name])
	id in protected
	"delete" in rc.change.actions
	not "create" in rc.change.actions
	msg := sprintf("%s: protected resource destroyed (12b)", [rc.address])
}

# Replacement (destroy + create) of a protected resource is recreation.
deny contains msg if {
	some rc in input.resource_changes
	id := sprintf("%s.%s", [rc.type, rc.name])
	id in protected
	"delete" in rc.change.actions
	"create" in rc.change.actions
	msg := sprintf("%s: protected resource replaced via destroy+create (12b)", [rc.address])
}

# No public IAM members anywhere in the plan, in any IAM resource shape.
deny contains msg if {
	some path, value
	walk(input, [path, value])
	value in {"allUsers", "allAuthenticatedUsers"}
	msg := sprintf("%v: public IAM member %q", [path, value])
}

# Owner/editor grants are never part of this infrastructure.
deny contains msg if {
	some path, value
	walk(input, [path, value])
	value in {"roles/owner", "roles/editor"}
	msg := sprintf("%v: owner/editor grant %q", [path, value])
}

# Container images must be digest-pinned; :latest is only a build-tag alias.
deny contains msg if {
	some path, value
	walk(input, [path, value])
	path[count(path) - 1] == "image"
	is_string(value)
	value != ""
	not contains(value, "@sha256:")
	msg := sprintf("%v: image %q is not digest-pinned", [path, value])
}
