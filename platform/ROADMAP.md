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
- [x] Pub/Sub-level `trade_plan_ready` filtering: a temporary filtered
  subscription received only the plan fixture while an unfiltered subscription
  received both the real outcome and plan fixture on 2026-10-12; all temporary
  resources were deleted. The Pulumi-managed subscription remains undeployed.

## Next

Coordinated operator approval (2026-10-18): consume the Harness config-only
operating-settings contract. Bundle its platform profile, pin the rebuilt
image, and replace setting flags with `CHRYSOPOEIA_CONFIG`. Verify exactly one
execution with at most two cycles, then retain the journal. No BTC benchmark,
consumer rollout, scheduler, or archive lifecycle change is included.

Implementation evidence: published/pinned image `sha256:d6c13fc6…`, updated only
the existing job, and verified execution `chrysopoeia-cycle-local-nr6tj` stopped
at the profile's two-cycle cap. One turn filled in paper and one failed;
$0.87996215 booked model cost stayed within the $1.50 ceiling. Both emitted
events reached BigQuery; archive data/protections stayed intact. Ten offline
Platform tests passed and final preview showed 19 unchanged. See
`docs/deployment.md`; no benchmark, Consumer rollout, or scheduler was run.

Operator approval (2026-10-18): add and deploy a raw-event BigQuery archive
subscribed to `chrysopoeia-events`, then verify one labeled synthetic event.
Retain payload and Pub/Sub metadata without filtering event types; this is an
analytics copy, never a financial ledger. Coordinated Harness work adds local
BTC 5m series selection, but no forecasting session is authorized by this work.
No consumer deployment, image rollout, or scheduler is included.

Implementation evidence: archive deployed and verified with one
synthetic publish/query on 2026-10-18; preview reports 19 unchanged. See
`docs/deployment.md#event-archive`. No collection session was started.

Operator approval (2026-10-18): treat the archive dataset and table as permanent
fixtures across runtime recreation. Keep both Pulumi-protected and retained on
delete, preserve their existing IDs, and document state recovery by import.
Do not destroy/recreate storage to test this; use offline contracts and a
non-destructive protection update with an existing-row check.

Implementation evidence: applied metadata-only protections;
exported state confirms `protect` and `retainOnDelete` on both resources.
The original synthetic row remained unchanged before/after. No storage or
runtime resources were replaced or deleted. Recovery steps are in
`docs/deployment.md#permanent-storage-and-infrastructure-recreation`.

1. Deploy the Pulumi-managed consumer subscription and verify its
   `trade_plan_ready` filter replacement. The rebuilt image and a bounded job
   execution with `CHRYSOPOEIA_EVENT_SINK=pubsub:...` were live-verified
   2026-10-14 (see `docs/deployment.md`): the deployed direct-publishing path is
   confirmed, so only the undeployed subscription remains.
2. Launch bounded paper `run` sessions from the Cloud Run Job. Live-verified
   2026-10-14: one execution completed two bounded cycles using CLI settings.
   The config-only contract above replaces those settings with the bundled
   platform profile and `run --journal /mnt/journal/run`. The job remains
   request-triggered; no always-on harness process is required. Repeat
   executions should pass a fresh `--journal` via `execute --args`, since
   resuming a session immediately hits its cycle cap.
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
