# Platform Roadmap

`../.agents-cli-spec.md` is authoritative for product scope and acceptance. This
roadmap only orders approved platform work and cannot expand that scope.
Development and live-verification gates are in
`../harness/docs/verification.md`; deployment details are in
`docs/deployment.md`. Paths below are relative to `platform/`.

The platform consumes a released harness artifact. Future event adapters and
consumers are coordinated with the harness contract and appear in both roadmaps.

## Complete

- [x] Managed deployment, Level 2 (single operator): container-first Pulumi base
  with a versioned journal bucket, least-privileged runner service account,
  Artifact Registry repository, and one Cloud Run job (`infra/`, `Dockerfile`).
  Live-verified 2026-09-27 in the restored container shape at
  `f0d87f1`/`bc00442`: idempotent-admission no-op, `book` execution, and a
  fresh-capture cycle appending a new `turn_admitted` inside the deployed
  container; see Recorded Live Verification in
  `docs/deployment.md`. The journal bucket and job remain the
  operator's durable session; multi-tenant hard isolation via one GCP project
  per tenant is deferred as described in `docs/deployment.md`.

## Next

1. Launch bounded paper `run` sessions from the Cloud Run Job once a released
   harness artifact includes it. The job remains request-triggered; no always-on
   harness process is required.
2. **GCP/other event consumer:** after the harness event producer and paper
   consumer are implemented and transport is selected, deploy an
   independent least-privilege consumer. Its runtime follows specified delivery,
   quote-freshness, reconciliation, and exit-protection requirements; it is not
   assumed to be an always-on manager. Keep each consumer's ledger separate,
   never import harness code, and keep authenticated execution disabled.

## Deferred

- Cloud SQL, RAG Engine, Memory Bank, and managed runtime services, gated on
  adoption triggers in `docs/deployment.md`.
- Multi-tenant or public-facing deployment (Level 3), which requires explicit
  design before anything exists.

## Updating This Roadmap

- Change only work owned by `platform/`.
- Start a milestone only with explicit user approval and an agreed contract.
- Every externally observable feature addition or change requires both offline
  checks and bounded live verification against the real changed boundary, as
  defined in `../harness/docs/verification.md`. A failed or unavailable live check
  leaves the feature incomplete and blocks any commit recommendation.
- Mark work **Complete** only after acceptance evidence exists and the change is
  committed.
- Do not add speculative services or infrastructure.
