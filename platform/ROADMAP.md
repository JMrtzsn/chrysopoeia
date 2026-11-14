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

- [x] Open-positions projection writer (2026-11-14, operator-approved via the
  Observer ROADMAP Next item 1): the `open_positions` derived table in the
  archive dataset (explicitly unprotected and retained on delete — a rebuildable
  read model, never authoritative), a customer-managed transfer runner service
  account with project `roles/bigquery.jobUser`, archive-dataset
  `roles/bigquery.dataViewer`, table-level `roles/bigquery.dataEditor`, operator
  `roles/iam.serviceAccountUser` for config creation, `roles/iam.serviceAccountTokenCreator`
  for the Google-managed transfer agent on the runner, and the
  `open-positions-refresh` scheduled query (every 15 minutes, atomic
  TRUNCATE+INSERT full rebuild from the 90-day archive window). API-created
  scheduled queries require an explicit service-account credential and
  Google-managed service agents reject impersonation, so the runner is a normal
  service account. First rebuild ran as the operator: 20 rows (9 rejected,
  7 settled, 4 pending). See `docs/deployment.md`; the Observer reads the table
  for journey-health lifecycle state.

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
- [x] Bounded job-trigger queue (2026-10-25): permanent Cloud Tasks queue,
  least-privilege trigger identity, and the gated `run.sh enqueue` action for
  operator-approved campaigns of independently capped sessions. Two-task pilot
  verified; first campaign (80 executions × $1.50 = $120 worst case) running
  for Harness evidence accumulation. See `docs/deployment.md`.

## Next

Coordination boundary (2026-10-19): the Dockerfile installs the locked
dependency set in its own layer before copying the wheel and configs. Keep that
ordering; it is what makes an ordinary code or TOML change push only small layers
instead of re-uploading ~357 MB. A `uv.lock` change is still a full push. No
service, resource, or contract change is included.

Implementation evidence: Dockerfile reordered and an 11th Platform contract test
asserts the dependency layer precedes wheel/config copies. Image
`sha256:13eac92e…` was pinned and deployed; `validate --json` execution
`chrysopoeia-cycle-local-mdptj` exited 0 and loaded the platform profile with
`research=False` and the BTC series. The claim that later code/TOML changes push
small layers is not yet measured.

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

Operator hard requirement (2026-10-18): during development the deployed profile
must forecast only BTC 5m Up/Down. `configs/platform.toml` now requires
`series = "btc-updown-5m"` with a 300-second cadence; rebuild, pin, deploy, and
verify one bounded execution. The earlier two-cycle verification filled a
non-BTC soccer market and must not be repeated under the new requirement.

Implementation evidence: the image now installs the frozen `uv.lock` export
(ADK 2.8.0/pydantic 2.13.4), validates both bundled profiles, was pinned as
`sha256:3ae64def…`, and the job was updated; `validate --json` execution
`chrysopoeia-cycle-local-7jccr` succeeded with the BTC series. The two-window
BTC smoke (`chrysopoeia-cycle-local-jj49n`) admitted two BTC windows but both
turns failed without a structured proposal, so the model path is not verified
under the new profile. See `docs/deployment.md`.

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

1. ~~Deploy the Pulumi-managed consumer subscription and verify its
   `trade_plan_ready` filter replacement~~ (done 2026-10-25): the filtered
   push subscription is deployed and delivered only plan events to the
   consumer; full lifecycle evidence in `docs/deployment.md`.
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
4. **Outcome archive and context-history access** (coordinated operator
   approval, 2026-10-21; IAM applied and verified 2026-10-22): the optional
   Consumer service identity can publish lifecycle outcomes to the existing
   topic, and `context_history_enabled` grants the Harness runner
   `bigquery.jobUser` plus dataset-scoped `bigquery.dataViewer` and passes the
   archive table/location to the job. Both grants are live-verified; the
   deployed image does not use them yet.
5. **Self-learning rollout steps** (coordinated with Harness roadmap item 8;
   each separately operator-approved): (a) ~~rebuild and pin a harness image
   containing the context-profile feature~~ (done 2026-10-23):
   `sha256:83447e14…` pinned and deployed; the job also sets
   `CHRYSOPOEIA_CONTEXT_CATALOG=/mnt/journal/context_profiles.jsonl` so
   generated profiles persist on the journal bucket; (b) ~~redeploy with
   `[history]`/`[context_learning]` enabled and the 3072 output ceiling~~
   (done 2026-10-23): budget re-checked (~$1.05 worst case vs $1.50),
   execution `chrysopoeia-cycle-local-j7xbh` exited 0 at its two-cycle cap
   with $0.12549240 actual cost and a context-pinned v3 outcome carrying the
   deployed history aggregate; see `../harness/docs/verification.md`;
   (c) ~~roll out the Consumer so real fills publish
   `consumer_outcome` events~~ (done 2026-10-25): `sha256:6807f5c7…` pinned,
   15 resources created, synthetic-plan fill/settlement outcomes archived —
   see `docs/deployment.md`; model-produced delivery pending a non-abstaining
   turn; (d) run bounded cycles until a context has 20
   finalized outcomes, then verify the first agent-approved profile revision
   end to end. No scheduling is authorized by this entry alone.
6. **Current-stack rollout with a private Observer** (coordinated operator
   approval, 2026-10-31): rebuild and pin current Harness and Consumer images,
   and add the optional Observer service, dedicated read-only identity, and
   single invoker grant. Verification is no-model only: Harness `validate`,
   Consumer revision readiness, and one deployed Observer query. No campaign,
   enqueue, or forecasting spend is included. Deployed 2026-11-07 and verified
   (see `docs/deployment.md`); the trigger queue is left paused. Cloud Run
   reserves `/healthz`, so the Observer health route moved to `/health` and was
   redeployed alone.
7. ~~**Esports scored-only platform profile**~~ (done 2026-11-09): rebuilt,
   pinned as
   `sha256:a21949cfc40a6f3ecae9af56c67ab1cfe9f7638b4b6e6d8ff6da463837d33224`,
   deployed, and verified no-model: executions `chrysopoeia-cycle-local-7rdf8`
   (1m7s, exit 0) plus duplicate validation `-25r7q`; the local gate prints the
   deployed profile as esports scored-only, `cost_budget=3`, `max_cycles=2`,
   gemini-3.5-flash at `us`. See `docs/deployment.md`.
8. ~~**Scheduled esports scanning with a native billing-budget alert**~~
   (done 2026-11-10, budget parked):
   (a) Deploys the scheduling chain behind config (`scan_schedule`,
       `scan_paused`): Cloud Scheduler → `chrysopoeia-scan-local` workflow →
       existing job with per-tick journal override
       `/mnt/journal/esports-<ISO stamp>`; runtime identity is the existing
       least-privilege trigger service account. Settle decisions recorded in
       `docs/deployment.md`: the executions-create API needs OAuth (not OIDC)
       and has no `:execute` method; the journal keys on the tick timestamp
       because a closed session journal rejects re-open, so date-keying alone
       would deadlock the schedule after the first session. Verification
       passed: two scheduler-triggered executions (workflow `493c9ea0` → job
       `chrysopoeia-cycle-local-b627z` → journal
       `esports-2026-11-10T06:13:16.871485Z`; workflow `f7524ed2` → job
       `-xqhqn` → journal `esports-2026-11-10T06:16:09.815551Z`), then
       `scan_paused=true` left the cron `40 13-22 * * *` PAUSED (still ~$0
       while paused; scheduled spend is bounded per tick to the $3 session
       ceiling and $0 on idle discovery days).
   (b) Budget alert deployed 2026-11-11: `Chrysopoeia spend budget (local)`,
       1000 SEK/month (the billing account currency is SEK — a USD amount was
       rejected with an opaque `INVALID_ARGUMENT`), project-filtered, 50/90/100%
       monthly thresholds with default billing-account email recipients. Adopted
       into Pulumi state by import; the resource sits behind `budget_amount_usd`
       and `budget_currency`. Root causes of the earlier parking: the billing
       APIs require a quota project the caller may use (fixed via `gcloud
       config set billing/quota_project PROJECT_ID` and the
       `GOOGLE_CLOUD_QUOTA_PROJECT` env), and the currency mismatch above — no
       IAM grant was ever missing.
   Exclusions unchanged: no harness/consumer/observer change; no
   `scored_only=false`; no real-money execution.

9. **Automated paper trading for esports match winners** (operator-approved
   2026-11-12): harness gate flipped (`run` no longer refuses non-scored-only
   profiles; `configs/platform.toml` sets `scored_only = false`; 377 offline
   tests green), image rebuilt/pinned (`sha256:bdf53208…`), deployed, and
   verified live: forced tick `e62c5a8d` → job `-wmgmb` → journal
   `esports-2026-11-12T13:41:42.030466Z` produced `plan_ready` (p=0.93 vs price
   0.86), a deterministic-policy-approved paper fill ($5.00 stake, 5.81 shares
   @ 0.86, $0.10 fee), and a `trade_plan_ready` outbox event. Real-money
   execution remains prohibited.

10. **Health monitoring** (deployed 2026-11-13): three log-based metrics over
    failure signatures observed this week — consumer service ERROR logs
    (`chrysopoeia_sweep_errors_local`, caught the 8-hour silent sweep outage of
    2026-11-12), cycle task 900-second timeouts (`chrysopoeia_task_timeouts_local`,
    seen 18:56/19:56 on 2026-11-12), scheduler 5xx attempts
    (`chrysopoeia_scheduler_failures_local`) — plus an email notification
    channel, one threshold alert per metric (any rate >0 sustained 10 min for
    sweep errors; >0 sustained 1 h for timeouts; >0 sustained 30 min for
    scheduler failures), and the `Chrysopoeia health (local)` Cloud Monitoring
    dashboard. Gated on `health_alert_email`; no absence alerting because
    overnight silence is by design.

11. **Journey-health event alerting** (operator-approved 2026-11-13,
    event-based direction; implementation separately approved): item 10 pages
    on process-failure logs only; outcome-level degradation must react to the
    event stream, not poll `/v1/health`. Design:
    - a platform-owned filtered push subscription on `chrysopoeia-events`
      triggers a small platform-owned Cloud Run evaluator that invokes the
      private Observer `/v1/health` once per event with its dedicated OIDC
      invoker identity and logs one structured `observer_health` record
      (severity `ERROR` when the status is `degraded`, else `INFO`). The
      Observer stays pull-based and read-only; the evaluator owns no ledger
      and only logs.
    - Alerting keys on those records: one threshold alert on the `degraded`
      record rate >0 sustained ~10 minutes (covers stuck settlements and any
      event-time stale-outcome or cost-budget reason), and one absence
      condition on the health-record rate in-window only — each event logs a
      record, so a stopped loop starves the stream and page instead of the
      overnight silence staying by design.
    - The `Chrysopoeia health (local)` dashboard gains a journey-health panel.
    - Acceptance: offline evaluator tests; image build, pin, and deploy;
      one bounded live check (labeled event → exactly one structured record →
      alert metric visible); no model or campaign spend. Each step separately
      approved. Cost bound: ~10 events/day, scale-to-zero evaluator, and one
      ≤100 MiB Observer query per event.

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
