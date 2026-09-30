# Platform Roadmap

`../.agents-cli-spec.md` is authoritative for product scope and acceptance. This
roadmap only orders approved platform work and cannot expand that scope.
Development and live-verification gates remain in
`../docs/development-lifecycle.md`. Paths below are relative to `platform/`.

The only coupling between the harness and platform flows is a released harness
artifact (wheel/image version). Neither roadmap depends on the other's tasks.

## Complete

- [x] Managed deployment, Level 2 (single operator): container-first Pulumi base
  with a versioned journal bucket, least-privileged runner service account,
  Artifact Registry repository, and one Cloud Run job (`infra/`, `Dockerfile`).
  Live-verified 2026-09-27 in the restored container shape at
  `f0d87f1`/`bc00442`: idempotent-admission no-op, `book` execution, and a
  fresh-capture cycle appending a new `turn_admitted` inside the deployed
  container; see Recorded Live Verification in
  `../docs/development-lifecycle.md`. The journal bucket and job remain the
  operator's durable session; multi-tenant hard isolation via one GCP project
  per tenant is the Level 3 follow-up note in `../docs/gcp-architecture.md`.

## Next

1. Launch the harness loop entrypoint from the Cloud Run job once a released
   harness artifact includes it. The platform adds no loop or scheduler.

## Deferred

- Cloud SQL, RAG Engine, Memory Bank, and managed runtime services, gated on
  adoption triggers in `../docs/gcp-architecture.md`.
- Multi-tenant or public-facing deployment (Level 3), which requires explicit
  design before anything exists.

## Updating This Roadmap

- Change only work owned by `platform/`.
- Start a milestone only with explicit user approval and an agreed contract.
- Every externally observable feature addition or change requires both offline
  checks and bounded live verification against the real changed boundary, as
  defined in `../docs/development-lifecycle.md`. A failed or unavailable live check
  leaves the feature incomplete and blocks any commit recommendation.
- Mark work **Complete** only after acceptance evidence exists and the change is
  committed.
- Do not add speculative services or infrastructure.
