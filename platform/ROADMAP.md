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

12. **Terraform migration with plan gates** (proposed 2026-11-15; approved
    2026-11-15 with amendments): replace the single-file Pulumi program with a
    structured Terraform root so LLM-authored infrastructure changes pass
    deterministic gates before any apply. Pulumi problems recorded in
    `docs/deployment.md` include ghost diffs, `--target` not creating new
    resources, and file-backed state. Most other live defects were GCP API
    behavior and will carry over, and two carry over structurally: Terraform's
    `-target` has the same state-only limitation, and the `google` provider has
    its own perpetual-diff family (scheduler `http_target.headers`,
    transfer-config `params` formatting, IAM binding ordering). Land this
    before item 11 adds more resources. Each step needs separate operator
    approval; no resource may be recreated.
    - **Single-writer rule.** From the start of 12d (import) until 12e
      (cutover) completes, Pulumi applies are forbidden: `platform/run.sh
      deploy` must refuse once import begins, so two tools never apply to the
      same cloud. Pulumi previews stay allowed for comparison.
    - **Ghost-diff allowance list (12d/12f).** `terraform plan` after import is
      accepted only with an explicit, committed list of known provider-quirk
      diffs (initial suspects: transfer-config `params.query` string
      formatting, scheduler `http_target.headers`, IAM binding ordering). At
      12f, drift detection ignores only that list; anything else is drift.
      12d outcome: all three suspects proved to be exact-mirror fixes, so the
      committed list is empty — 12f drift detection ignores nothing.
    - **12a. Structure and offline gates.** Add `infra-tf/` with per-concern
      files (`apis`, `iam`, `storage`, `events`, `bigquery`, `run`,
      `scheduling`, `monitoring`, `budget`), keeping the same optional-feature
      conditions as today's config keys. Add pinned `google` provider and
      Terraform versions plus a GCS state backend with locking. The state
      bucket is created once by the operator, versioned, and its access is
      pinned from day one (who can write state can rewrite the cloud); the
      empty-passphrase file-backed local-dev habit does not carry over.
      Gate roles do not overlap: tflint = correctness, trivy config =
      security, conftest (12c) = operator policy. Offline gates:
      `terraform fmt -check`, `validate`, `tflint` (Google ruleset), and
      `trivy config`. Acceptance: all gates pass with no cloud access.

      **Complete (2026-11-15).** `platform/infra-tf/` mirrors the ~70-resource
      Pulumi program per concern, with the same optional-feature conditions
      (`count`-gated on `pubsub_topic`, image digests, `scan_schedule`,
      `budget_amount_usd`, `health_alert_email`) and the program's
      cross-config guards as variable validations. Pinned: Terraform
      `~> 1.15.0`, google/google-beta provider `8.11.0`; GCS backend declared
      (`PROJECT_ID-chrs-tfstate-local`, created by the operator in 12d,
      not yet provisioned). Pulumi auto-named live resources are reflected
      exactly (`paper-consumer-a8db57a`, `consumer-dead-letter-retention-7304458`,
      `consumer-sweep-916f9e1`) so 12d imports by ID without recreation.
      Archive dataset carries `prevent_destroy`, tables their
      `deletion_protection` as today. Evidence: `./gates.sh` all green with no
      cloud access (`terraform init -backend=false`): `fmt -check`, `validate`,
      tflint 0.66.0 + Google ruleset 0.41.0 (0 issues), trivy 0.76.2 config
      HIGH/CRITICAL (0 findings). Offline only — no resource created, no
      state written.
    - **12b. Protections first.** Add `lifecycle { prevent_destroy = true }`
      on the journal bucket, consumer ledger bucket, and archive dataset/table,
      matching today's Pulumi `protect`/`deletion_protection`. Add an offline
      test that fails if any protection is removed.

      **Complete (2026-11-15).** `prevent_destroy` pinned on the journals
      bucket, consumer ledger bucket, archive dataset, and `raw_events`
      (table also keeps `deletion_protection = true`); the `open_positions`
      projection table stays deliberately unprotected — it is a rebuildable
      read model and deletion loses nothing. New
      `tests/test_protections.py` (stdlib only, brace-parsed resource blocks)
      asserts every pinned protection; verified to fail when one is removed
      and pass when restored. Wired into `gates.sh` as the fourth gate. All
      gates green offline, no cloud access.
    - **12c. Plan policy.** Gate with `plan -out=tfplan`, then
      `terraform show -json`, then `conftest` (Rego). Deny delete/replace of
      protected resources, `allUsers`/`allAuthenticatedUsers` members,
      project-level owner/editor grants, and non-digest image references.
      Add fixture-plan tests for each rule. Apply only a saved, gated
      `tfplan`, never a fresh plan.

      **Complete (2026-11-15).** `policy/plan_policy.rego` (conftest 0.71.1,
      OPA rego v1) denies: destruction of any 12b-protected resource, replace
      via destroy+create of one, any `allUsers`/`allAuthenticatedUsers` leaf
      anywhere in the plan, any `roles/owner`/`roles/editor` grant, and any
      non-digest container image. `policy/test.sh` runs one fixture per rule
      (`deny_*` must produce a denial, `allow_*` must pass clean) and is wired
      into `gates.sh` as the fifth gate — all green offline. Notes: the walk
      rules intentionally scan whole-plan leaves, which is stricter than
      "project-level" grants and catches every IAM resource shape; conftest's
      default namespace is `main`, so the runner passes
      `--namespace terraform.plan`. The saved-plan→policy→apply flow in
      `run.sh` lands at 12e per the item.
    - **12d. Import.** Use `import` blocks for every live resource in the
      `local-dev` stack, keeping existing IDs. Acceptance: `terraform plan`
      against live state shows **no changes** (read-only; needs operator
      approval for authenticated reads). Any diff on a protected resource
      blocks the step.

      **Complete (2026-11-16).** State bucket
      `PROJECT_ID-chrs-tfstate-local` created first (versioning,
      UBLA, public access prevention enforced, only the project owner/editor
      legacy bindings). The single-writer guard
      (`IMPORT_BEGAN` + `run.sh deploy` refusal) was committed before the
      first import. All 69 importable live resources imported by ID; the
      scan workflow has no importer in the provider (8.11.0 and main), so its
      state entry was pushed by hand with identity attributes only and the
      provider refreshed it from the API on the first plan — 71 objects in
      state. `terraform plan` against live state now reports **no changes**;
      the import apply wrote state only (69 imports + two config-only
      `disable_on_destroy`/`disable_dependent_services` materializations on
      project services, no API calls). Ghost-diff burn-down notes: the
      suspected ghosts were eliminated by exact mirroring rather than
      allowed — transfer-config `params.query` via `chomp()` (the API strips
      the trailing newline; the workflow source keeps its newline, so the
      workflow uses the plain heredoc), scheduler `http_target` via the
      literal live body `{"argument": "{}"}` (jsonencode produced compact
      JSON) and no `headers` block (the API returns none), and the dashboard
      via the verbatim live JSON (including system-set `plotType`/`targetAxis`
      and `etag`) keyed on the project NUMBER. The live
      `deletion_protection` on the run job/services, workflow, and
      `open_positions` is `true` (provider defaults since creation), so the
      config mirrors it; `open_positions` still has no `prevent_destroy`
      lifecycle and stays rebuildable-by-policy. Real corrections found by
      the import: the transfer config's live `serviceAccount` is unset (it
      runs as its owner, the transfer identity, via the actAs creation grant),
      `pubsub_topic` config values are short topic names with full paths
      derived locally, and the dead-letter subscriber IAM needs the full
      subscription path with no explicit project. Provider-level:
      `google-beta` dropped (`google_project_service_identity` has no
      importer; agents resolve via the deterministic
      `service-{number}@gcp-sa-{service}` emails), and the provider needs
      `user_project_override` + `billing_project` because it does not read
      the ADC quota project (b/360405077). Evidence: `gates.sh` exit 0;
      import apply output retained; post-apply `terraform plan` = "no
      changes". Operator-local `terraform.tfvars` is gitignored.
    - **12e. Cutover.** Point `run.sh deploy` at the gated
      plan→policy→apply flow and keep the `CHRYSOPOEIA_RUN_PLATFORM=1`
      refusal. Make image pins Terraform variables, and update `AGENTS.md`
      and `docs/deployment.md`. Acceptance: one bounded image repin applied
      through the gated flow, plus one job execution or `validate --json`.
      Then remove the Pulumi state with `pulumi state delete`/`stack rm`
      (resources stay in place; never `destroy`), delete `infra/`, and
      archive the old state file.
    - **12f. Drift check.** Run a scheduled or manual
      `plan -detailed-exitcode`; any non-zero exit is reported as drift.
      CI required checks and apply approval follow once a remote repository
      policy exists.
    - Cost: ~$0 beyond one GCS state bucket. No model spend. Rollback until
      12e: Pulumi state is untouched and stays authoritative.
13. **Paused for re-evaluation; resume gate** (2026-11-18). Both Scheduler
    jobs are paused through Terraform (`scan_paused`, `consumer_sweep_paused`).
    Resume each one only after the item that gates it is Complete: scan after
    Harness Next item 1 (bounded cycle wall-clock), sweep after Consumer Next
    item 1 (settle without a usable quote). Before resuming, record real spend: enable the
    Cloud Billing export to BigQuery (a one-time console setting on the billing
    account) and query the last 30 days by service, which separates Vertex
    model cost from Cloud Run, Pub/Sub, and BigQuery. Acceptance: a recorded
    spend breakdown, then each resume applied separately through the gated
    plan→policy→apply flow, with one clean scheduled tick or sweep observed.

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
