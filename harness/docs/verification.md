# Verification

The product spec defines acceptance. Run the canonical offline checks in
[`../AGENTS.md`](../AGENTS.md) before recommending completion. Offline tests
require no credentials or live model/venue calls; paid or network checks do not
belong in automatic hooks.

## Bounded live checks

Externally observable changes need a live check of the changed boundary after
offline checks. Obtain operator approval, estimate cost, bound calls/time/data,
use least privilege and ambient/provider-standard authentication, sanitize the
evidence, and clean up temporary resources. Record command, boundary, result,
bounds, and cost. Failure or unavailability blocks completion. Venue checks are
public/read-only; model checks are bounded paper cycles; authenticated exchange
execution is prohibited. Full policy is in
[`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).
