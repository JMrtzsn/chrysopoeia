# Platform Roadmap

`../.agents-cli-spec.md` is authoritative for product scope and acceptance. This
roadmap only orders approved platform work and cannot expand that scope.
Development and live-verification gates are in
`../harness/docs/verification.md`; deployment details are in
`docs/deployment.md`. Paths below are relative to `platform/`.

The platform consumes a released harness artifact. Future event adapters and
consumers are coordinated with the harness contract and appear in both roadmaps.

Operator-approved coordination boundary (2026-10-06): the harness owns Vertex
model endpoint selection (`gemini-3.5-flash` at `us`). Platform continues to
supply ambient project/auth and place resources in its configured compute
region; no platform model-location override is planned. This records a
coordination decision, not a new platform work item.

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
- [x] Optional Pub/Sub publisher (`3d942a5`, later moved into Harness): disabled
  by default; journal outbox, topic-scoped publisher IAM, and
  conditional API/topic setup. One synthetic event was published, confirmed,
  received, and acknowledged through temporary resources, then cleaned up on
  2026-10-08. No subscriber or Cloud Run rollout is included; see
  `docs/deployment.md`.
- [x] Optional paper-consumer deployment shape: conditional on both a pinned
  `consumer_image_digest` and producer topic, with separate ledger/runtime
  identity, scale-to-zero service (one instance/concurrency one), OIDC push and
  minute sweep, retry, retention, and dead letter resources. Bounded live
  verification passed 2026-10-10 (push, fill, sweep close; temporary resources
  removed); see `docs/deployment.md`. Not left deployed.

## Next

1. At the next deploy, rebuild the Harness image (plain `chrysopoeia`
   entrypoint) and run one bounded job execution with
   `CHRYSOPOEIA_EVENT_SINK=pubsub:...` to verify the deployed direct-publishing
   path. Harness `pubsub:` publishing itself was live-verified 2026-10-12.
2. Launch bounded paper `run` sessions from the Cloud Run Job once a released
   harness artifact includes it. The job remains request-triggered; no always-on
   harness process is required.
3. Deploy the live-execution consumer (separate identity and secret handling)
   only after `../consumer/ROADMAP.md` live-execution gates pass and are
   approved.

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
