# Managed GCP deployment

**Status:** Deployed for one operator. Local harness use does not require Google
Cloud.

## Deployed shape

- `harness/` builds a wheel and container image. `platform/` builds/publishes the
  image and deploys the Pulumi program in `infra/`. `Dockerfile` installs the
  locked dependencies in their own layer before copying the wheel and configs, so
  a code or config change reuses the cached dependency layer and pushes only
  small layers; changing `uv.lock` is still a full re-push.
- The image installs the exact `uv.lock` export produced by `build.sh`
  (`uv export --frozen --no-emit-project`) with `--no-deps`, then the wheel
  itself. Installing the wheel alone lets transitive dependencies drift, which
  changed agent workflow behavior between rebuilds: a 2026-10-18 image resolved
  ADK 2.12.0/pydantic 2.14.1 while the verified local lock is ADK
  2.8.0/pydantic 2.13.4, and both deployed BTC turns failed to produce a
  structured proposal. Keep the image dependency set identical to the lock that
  passed offline and live checks.
- Pulumi owns a versioned journal bucket, runner service account, Artifact
  Registry repository, and one Cloud Run job. Live images are pinned by digest,
  never a floating tag.
- The job runs the selected `chrysopoeia` CLI entrypoint on demand. The bucket is
  mounted at `/mnt/journal`; journal semantics belong to the harness.
- Operating settings come from the bundled Harness-owned
  `configs/platform.toml`, selected by `CHRYSOPOEIA_CONFIG=/etc/chrysopoeia-platform.toml`.
  The profile forecasts up to two CS2/Dota 2 match-winner markets per session
  and takes paper positions (`[session] scored_only = false`, operator-approved
  2026-11-12: reviewer-approved plans that pass risk policy produce journal
  fills and `trade_plan_ready` events), with a
  60-minute configured session deadline bounded by the job's 900-second task
  timeout and a $3 session model-cost ceiling. Cost is reserved before model
  work; grounded research is enabled with a 32768-token input ceiling, so one
  cycle reserves up to $1.43376. Changing the profile requires an image rebuild
  and digest update, not extra CLI setting flags. Rebuilt, pinned, and deployed
  2026-11-09 as `sha256:a21949cfc40a6f3ecae9af56c67ab1cfe9f7638b4b6e6d8ff6da463837d33224`;
  executions `chrysopoeia-cycle-local-7rdf8` (and duplicate `-25r7q`) validated
  the esports profile in the deployed container with exit 0 (no-model).
- The harness owns market selection, cadence, recovery, and stopping. The
  platform launches the process but does not drive cycles.
- Scheduled esports scanning (optional; set `scan_schedule` to cron): Cloud
  Scheduler `chrysopoeia-scan-<operator>` (UTC cron, default set to
  `40 13-22 * * *`, ten ticks/day within esports-active hours) POSTs an
  executions-create call for the `chrysopoeia-scan-<operator>` workflow using an
  OAuth2 access token (scope `cloud-platform`) from the existing least-privilege
  trigger identity; Cloud Scheduler additionally needs
  `roles/iam.serviceAccountTokenCreator` on that identity, and the workflow's
  invoker grant is project-level `roles/workflows.invoker`. The workflow
  computes a fresh journal key from the tick timestamp via
  `time.format(sys.now())` — an ISO-8601 string, since Workflows has no strftime
  — and calls the native `googleapis.run.v2.projects.locations.jobs.run`
  connector with `skip_polling` (fire-and-forget) and per-execution journal
  override `/mnt/journal/esports-<ISO stamp>`, so every tick is an independently
  capped $3 session. Journal rotation is what the resume semantics require:
  a closed/expired session journal raises `use a new journal directory provided
  by the operator`, so one journal key per tick is the only scheduler-compatible
  shape without a wrapper service. Secrets stay ambient; 204/`URL_CRAWLED`
  scheduler log entries alongside the real 200 are normal. `scan_paused=true`
  (default after bounded verification) pauses the schedule without deleting it.
  Each tick reserves nothing when discovery is idle; a day with zero eligible
  markets shows per-tick executions that reach the job's 900-second task timeout
  and are marked FAILED with zero model spend (known cosmetic limitation).
  Markets though, worst case (all ticks admit markets but every turn fails):
  ten $3 sessions/day. The native billing budget (item 8a) IS deployed:
  `Chrysopoeia spend budget (local)` — 1000 SEK/month (≈$100; the billing
  account `BILLING_ACCOUNT_ID` currency is SEK and a USD amount is rejected
  with an opaque `INVALID_ARGUMENT`), filtered to this project, alerting at
  50/90/100% of monthly spend to the default billing-account recipients
  (`notificationsRule` empty; the operator gmail account holds
  `roles/billing.admin` and receives the emails). Local plumbing notes: the
  gcloud CLI needs `gcloud config set billing/quota_project
  PROJECT_ID`, and any local call through the billing-budgets API
  (Pulumi included) needs `GOOGLE_CLOUD_QUOTA_PROJECT=PROJECT_ID`.
  The Pulumi `gcp.billing.Budget` resource sits behind `budget_amount_usd`
  (whole units) and `budget_currency` (default SEK) and owns the deployed
  budget by import.
- Re-running the job starts a fresh bounded session only when given a new
  journal. The stored args reuse `/mnt/journal/run`, so a second execution
  resumes the finished session and stops at once at its cycle cap. Override per
  execution, for example
  `gcloud beta run jobs execute chrysopoeia-cycle-local --region us-central1 --args=run,--journal=/mnt/journal/run-$(date +%s)`.
- This job is not an HTTP server. Paper fills and exits are simulated in-process
  only while the paper loop runs. Optional `pubsub_topic` Pulumi configuration
  creates a topic and only a topic-scoped `roles/pubsub.publisher` grant for the
  runner. It sets `CHRYSOPOEIA_EVENT_SINK=pubsub:projects/<project>/topics/<topic>`
  on the plain Harness CLI image. Absent configuration leaves execution unchanged.
- When both `consumer_image_digest` and `pubsub_topic` are set, Pulumi adds the
  independent paper consumer: separate versioned ledger bucket and bucket-only
  runtime identity, private service pinned by digest with revision minimum zero,
  revision maximum one, and request concurrency one, plus OIDC push and minute
  sweep. Optional `consumer_sweep_schedule` sets the UTC cron schedule; it
  defaults to `* * * * *`. The push subscription filters
  `attributes.record_type = "trade_plan_ready"`; Pub/Sub subscription filters are
  immutable, so adding or changing this filter replaces the subscription.
- The Consumer journal uses GCS FUSE and is safe only under this single-writer
  ceiling. The revision limit reduces overlap but does not make the mounted file
  a transactional multi-writer ledger; revision rollover can briefly overlap old
  and new revisions.
- Google API authentication uses the runner's ambient identity. Harness code
  never provisions cloud resources or invokes `gcloud`/`pulumi`.
- A permanent Cloud Tasks queue `chrysopoeia-trigger-<operator>` executes the
  job for bounded operator campaigns. `platform/run.sh enqueue <count>
  <spacing-minutes> <journal-prefix>` creates individually scheduled HTTP
  tasks; each task calls the Run `:run` API with an OAuth token from the
  least-privilege trigger identity (`run.jobs.run` + `run.jobs.runWithOverrides`
  only) and overrides the journal to its own `/mnt/journal/<prefix>-NNN`, so
  every execution is an independently capped session. A campaign's absolute
  worst-case cost is `<count>` × the profile's session `cost_budget`. The queue
  is inert when empty; `gcloud tasks queues pause/purge
  chrysopoeia-trigger-<operator>` stops or abandons a campaign. First campaign
  (2026-10-25, approved): 80 executions at 30-minute spacing (2 pilot + 78),
  worst case $120, expected ~$8-10, for the context-learning evidence
  accumulation in `../harness/ROADMAP.md`.

Harness drains old pending events before `cycle`/`run` and between run cycles,
publishes all canonical event types to one topic with `event_id`, `record_type`,
and `schema_version` attributes, and acknowledges
only after confirmation. Failures leave events pending and may duplicate
delivery, so consumers deduplicate by `event_id`. Platform retains topic, IAM,
and the raw-event archive. The optional paper Consumer publishes its own
`consumer_outcome` lifecycle events to that topic from its durable journal; its
subscription filters only `trade_plan_ready`, so outcome publication is not
recursively consumed. No authenticated trading is part of this milestone.

With neither consumer setting, no consumer resources exist. Setting
`consumer_image_digest` without `pubsub_topic` is a configuration error. With both
settings, messages retain for seven days, retry with bounded backoff, and
dead-letter after ten attempts. Recover by reading the retained dead-letter
subscription, correcting the transient cause, and republishing the original
message data unchanged; stable `event_id` deduplication makes replay safe.

The single-operator deployment is Level 2. Multi-tenant or public use requires
separate design and approval.

## Event archive

When `pubsub_topic` is configured, Pulumi also creates a protected BigQuery
dataset `chrysopoeia_events_<operator>` in the compute region, table `raw_events`,
and an unfiltered subscription `<topic>-bigquery`. The current destination is
`PROJECT_ID.chrysopoeia_events_local.raw_events` in `us-central1`.
The Pub/Sub service agent has `roles/bigquery.dataEditor` on this table only;
producers still need only topic publishing permission. The BigQuery API stays
enabled if the integration is removed.

When the optional Consumer is deployed, its service identity receives
`roles/pubsub.publisher` on this topic and the service gets its fully qualified
topic path through `CHRYSOPOEIA_EVENT_TOPIC`. It publishes strict
`consumer_outcome` v1 records for durable fills, rejections, closes, and
settlements. Delivery is at least once; stable outcome event IDs and journaled
acknowledgements make retries safe.

Harness BigQuery reads are separately disabled by default. Enabling them requires
both `[history].enabled = true` in the bundled Harness profile and Pulumi
`context_history_enabled = true`. Pulumi then grants the runner project-level
`roles/bigquery.jobUser` and dataset-scoped `roles/bigquery.dataViewer`, and sets
the archive table/location environment. The query reads only the configured
archive, filters its required `publish_time` partition, looks back 90 days, and
sets `maximum_bytes_billed` to 100 MiB. This read path does not provision or
mutate BigQuery data. A profile change still requires a rebuilt/pinned image;
IAM changes and live queries require their usual separate operator approval.

`data` preserves the raw UTF-8 event JSON as STRING. `attributes` preserves the
Pub/Sub attributes as a JSON-encoded STRING. Metadata columns are `message_id`,
`publish_time`, and `subscription_name`. Topic/table schema mapping is disabled,
so event-version changes do not drop fields or require table migrations. All
event types are archived, including abstentions and Consumer lifecycle outcomes;
no worker or Dataflow job runs.

Rows have no configured expiration. Both dataset and table have Pulumi
`protect=True` and `retain_on_delete=True`; the table also has provider deletion
protection, and dataset destruction cannot delete its contents.
The table is partitioned daily by `publish_time`, with a required partition
filter to bound scans. For example:

```sql
SELECT publish_time, JSON_VALUE(data, '$.record_type') AS record_type,
       JSON_VALUE(data, '$.event_id') AS event_id, data, attributes
FROM `PROJECT_ID.chrysopoeia_events_local.raw_events`
WHERE publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
LIMIT 100;
```

This is an at-least-once analytics copy, never the financial ledger. Deduplicate
by payload `event_id`, not Pub/Sub `message_id`: an outbox retry can publish the
same event with a new message ID. Synthetic verification rows use
`record_type=archive_verification` and must be excluded from strategy metrics.
Existing journals and events published before subscription creation are not
backfilled. Only published events are captured. Harness in-process paper fills
and settlements remain in the Harness journal; Consumer outcomes are archived
only when the optional Consumer publisher is deployed and configured.

The subscription never expires from inactivity. Undelivered messages retain
for 31 days, not forever. If export fails, inspect `bigqueryConfig.state` with
`gcloud pubsub subscriptions describe chrysopoeia-events-bigquery --project PROJECT_ID`
and monitor backlog/oldest unacknowledged age in Cloud Monitoring. Repair IAM,
table, or export failures before retention expires; otherwise backlog is lost.
Automatic alerting and dead-letter routing are not included. Storage, export,
and queries incur usage charges; smoke-test cost is expected to be negligible,
not guaranteed free.

Local producer usage and bounded scoring are documented in
[`../../harness/docs/collection.md`](../../harness/docs/collection.md). No
forecasting process or schedule starts when the archive is deployed.

## Observer service

When `observer_image_digest` is configured (with `pubsub_topic` and
`observer_invoker_member`), Pulumi creates five resources: service account
`chrysopoeia-observer-<operator>`, its project `roles/bigquery.jobUser`, its
archive-dataset `roles/bigquery.dataViewer`, Cloud Run service
`chrysopoeia-observer-<operator>` (scale zero to one, concurrency one, no
volumes), and `roles/run.invoker` for the configured member only. The service
gets `GOOGLE_CLOUD_PROJECT`, `OBSERVER_ARCHIVE_TABLE`, and
`OBSERVER_BIGQUERY_LOCATION`, and exports `observer_service_url` and
`observer_runtime_email`. It has no storage, publishing, Vertex, scheduler, or
subscription access. Public members are rejected by the program.

Private-by-IAM means the Consumer's pattern: Internet ingress with Cloud Run IAM,
so unauthenticated requests are refused. Invoke it with the configured
identity's token, for example
`curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"`.
Build with `observer/build.sh`, then tag, push, and pin the digest.

A rollout that changes the Consumer image must quiesce its writers first:
keep the trigger queue paused with no tasks, ensure no Harness execution can
publish, pause the Consumer sweep Scheduler, let in-flight pushes and sweeps
finish, then apply and resume the Scheduler only after the new revision is the
sole ready writer. No-model verification uses Harness `validate --json`,
Consumer control-plane readiness, Observer `/health`, and exactly one deployed
`/v1/insights` query.

### Permanent storage and infrastructure recreation

The dataset and table are permanent fixtures, not disposable runtime resources.
Keep their existing project, dataset ID, table ID, location, and Pulumi logical
names. Normal runtime updates reuse them. Protection blocks accidental deletion
or replacement, including removal of `pubsub_topic`; retention additionally
instructs Pulumi to leave the cloud resources intact if they are deliberately
unprotected and removed from management later. Do not disable these safeguards
to get past a deployment error.

Recreate only the intended runtime resources, not storage. Keep the current
Pulumi state and back it up securely before infrastructure maintenance; the
current backend is local under `platform/infra/state/`. Do not erase that state
as a way of resetting infrastructure. A normal full-stack destroy is blocked
by protected resources, rather than silently deleting history. Other storage,
including the paper journals bucket, still needs its own preservation review.

If stack/state must be recreated, restore its backup first. If that is not
possible, import the existing storage before `pulumi up`; never create an empty
replacement archive. With the original project/configuration restored and the
Platform Python environment active, run from the repository root:

```sh
PULUMI_CONFIG_PASSPHRASE='' pulumi -C platform/infra import --stack local-dev \
  --generate-code=false 'gcp:bigquery/dataset:Dataset' event-archive \
  projects/PROJECT_ID/datasets/chrysopoeia_events_local
PULUMI_CONFIG_PASSPHRASE='' pulumi -C platform/infra import --stack local-dev \
  --generate-code=false 'gcp:bigquery/table:Table' raw-events \
  projects/PROJECT_ID/datasets/chrysopoeia_events_local/tables/raw_events
```

Import only into state that is missing these resources. Recover/import other
still-existing infrastructure too, then preview and require no storage
replacement or deletion before the separately approved apply. Use the existing
source, not generated replacement code. The next apply persists both protection
and retention settings. Recreating a subscription does not delete archived
rows, but its backlog and events published during a subscription gap are not
preserved automatically.

These controls prevent Pulumi lifecycle deletion; they are not immutable/WORM
storage or a backup. Privileged SQL deletion, external table/project deletion,
and destructive in-place schema changes require separate access/backup controls.
No storage teardown is part of verification.

## Change and verification boundary

Run Pulumi preview and applies from `platform/`; see
[`../AGENTS.md`](../AGENTS.md) and [`../ROADMAP.md`](../ROADMAP.md). Live applies,
image publication, and job executions require approval and bounded verification
per [`../../harness/docs/verification.md`](../../harness/docs/verification.md).
Running the platform is explicit and off by default: use `platform/run.sh
{deploy|job}`, which refuses unless `CHRYSOPOEIA_RUN_PLATFORM=1` is set, and the
Pulumi program itself refuses any real apply (or destroy) without it. `pulumi
preview` is always allowed and needs neither the script nor the variable.
The 2026-10-10 bounded live check below covered authenticated push, the mounted
ledger across revision restarts, bucket and invoker IAM, and live Gamma/CLOB
timestamp freshness. Dead-letter delivery, YES/NO settlement, and concurrent
revision-rollover writers were not exercised; the GCS-FUSE single-writer ceiling
still applies, so avoid deploying while a push or sweep is in flight.
The optional Pub/Sub and Scheduler APIs use `disable_on_destroy=False`, so
removing the integration never disables a shared API.
For the approved temporary live test, choose a future cron in
`consumer_sweep_schedule` before applying, then manually trigger exactly one sweep. Restore the
operator-selected schedule afterward; shorter intervals reduce exit-monitoring
latency but increase invocation cost.
The file-backed `local-dev` stack has no secure configuration values and uses an
explicitly empty `PULUMI_CONFIG_PASSPHRASE` for preview. Operators must not put
credentials or other secrets in this stack. This local-only setup does not apply
to production stacks, which must not use an empty passphrase.
Do not change Cloud Run environment variables outside Pulumi:
`gcloud beta run jobs update --set-env-vars` replaces the full environment and
can desynchronize state.

## Recorded platform checks

| Date | Command / boundary | Result |
| --- | --- | --- |
| 2026-11-13 | Observer journey-health rollout: `observer/build.sh` (wheel + `uv export --frozen` runtime pin + linux/amd64 build + network-free import check), push `sha256:9aef0265f5aba785770ae9a6754a955cbcdf809c3d4af3fdd56b5b64fecbde12`, `pulumi config set observer_image_digest …@sha256:9aef0265…`, preview (3 diffs: observer image plus two known cosmetic state normalizations — empty-scaling keys on both services, cycle-scan scheduler headers from the 11-09 debugging), `CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh deploy --target urn:pulumi:local-dev::chrysopoeia-infra::gcp:cloudrunv2/service:Service::observer-service`; one authenticated `/v1/health`, one unauthenticated | Apply: 1 updated (observer-service to the new digest), 63 unchanged; the cosmetic normalizations left pending for a later full-stack window. Live (10:46 UTC, outside the scheduled window): unauthenticated `/v1/health` 403; one authenticated request 200 with valid `observer_health` JSON — status `healthy`, reasons `[]`, `in_scheduled_window` false, last decision 2026-11-12T22:46Z, last completed 2026-11-13T04:47Z, 10 decisions/24 h, 6 abstentions (rate 0.6), 2 fills, 1 win, +0.713953488372093 realized, 2.1155223 model cost, 0 stuck settlements, 7.785 h max settlement lag, 0 revisions since last outcome, budget null (unset). One read-only bounded archive query behind the response; no other resources touched; no model or campaign spend. Remaining separately approved: in-window Scheduler probe, `degraded`/absence alerting, dashboard panel. |
| 2026-11-09/10 | Scheduled esports scanning (item 8b): workflow/scheduler/IAM resources added in `infra/__main__.py` behind `scan_schedule`; `pulumi config set scan_schedule "40 13-22 * * *" billing_account_id …`; three `platform/run.sh deploy`; `gcloud workflows execute` + two `gcloud scheduler jobs run` force-runs; two executions plus journals observed; `scan_paused true` deploy → schedule PAUSED | Infra: workflows/Scheduler APIs declared, workflow `chrysopoeia-scan-local` (runtime SA = trigger identity, `run.jobs.run`+`runWithOverrides` only), project `roles/workflows.invoker` for it, and Scheduler-service-agent token-creator on the trigger identity; preview matched. Debugging evidence, all live-discovered: (1) regional endpoint `us-central1-workflows` 404s — the executions API lives on `workflowexecutions.googleapis.com`; (2) that API has no `:execute` method — use `POST …/executions`; (3) it rejects OIDC id tokens ("Expected OAuth 2 access token") — the target must use OAuth (`oauth_token`/`--oauth-service-account-email` per the official scheduler→workflows recipe) plus `Content-Type: application/octet-stream`; (4) Workflows `time.format` is `(seconds[, timezone])` returning ISO-8601, no strftime patterns and no `string.*` symbols in this runtime — the journal key is the raw ISO stamp; (5) the `jobs.run` path uses the native connector with `skip_polling`. Verified gates: workflow execution `493c9ea0` (06:13:16Z) → job execution `chrysopoeia-cycle-local-b627z` → journal `esports-2026-11-10T06:13:16.871485Z/` with `chrysopoeia.jsonl`; scheduler execution `f7524ed2` (06:16:09Z) → `-xqhqn` → `esports-2026-11-10T06:16:09.815551Z/`; distinct minute-keyed journals prove rotation. Both scheduler-triggered; after the second the schedule was set `PAUSED` via `scan_paused=true` (cron remains `40 13-22 * * *` for later use). Overnight the enabled schedule spent ~$0 (no model spend; failures were the auth defect, fixed). Budget (item 8a) parked: `gcloud billing budgets create` denied (no billing-account IAM for the gmail account); `billingbudgets.googleapis.com` and `cloudresourcemanager.googleapis.com` enabled as part of this work; `budget_amount_usd` removed from the stack config until the operator grant lands. Known limitation: idle scheduled ticks hit the 900 s task timeout and are marked FAILED with zero model spend; the two service `-scaling` ghost diffs and non-persisted scheduler headers reappear in every preview (old provider bookkeeping; live state verified correct). Diagnostic-only change, reverted: temporary `iam.serviceAccountTokenCreator` self-grant on the trigger identity. |
| 2026-11-07 | Current-stack rollout with private Observer: `platform/build.sh` (Harness `sha256:219288bb…`), `consumer/build.sh` + no-network import check + push (`sha256:15a636b2…`), `observer/build.sh` + push (`sha256:da5dfa27…`); pin all three plus `observer_invoker_member`; trigger queue and Consumer sweep paused; `platform/run.sh deploy`; Scheduler resumed; one `run.sh job --args=validate,--json`; one authenticated Observer `/v1/insights` | Preview and apply matched: 5 Observer resources created, Harness job and Consumer service updated, 41 unchanged, no deletes. Consumer revision `00002-zt6` Ready with 100% traffic on the new digest before the sweep resumed; the next sweep returned 204 from it. Execution `chrysopoeia-cycle-local-htbtj` succeeded on the new Harness digest: platform profile valid, paper mode, BTC series, research disabled; no model, market, or event calls. Observer runs as `chrysopoeia-observer-local` with only project `roles/bigquery.jobUser` and archive-dataset READER; `roles/run.invoker` only for the configured operator. Unauthenticated `/v1/insights` returned 403. One authenticated request returned 200 (one BigQuery query, 90-day/100 MiB/20 s bounds): two contexts, CS2 v4 (actual 0.180846, reserved 1.43376) and BTC v3 (54 decisions, 2 completed, reserved null). Defect: Cloud Run's front end reserves `/healthz` and returns 404 before the container, so the health route is unusable when deployed. Fixed the same day: route renamed to `/health`, Observer image `sha256:ac0de602…` rebuilt, pushed, and applied with `--target` on the Observer service only (1 updated, 47 unchanged); authenticated `/health` 200 `{"status":"ok"}`, unauthenticated 403. Trigger queue left paused; no campaign or model spend. Credentials: the operator's gmail gcloud account; the default ingka account needed reauthentication. |
| 2026-10-25 | Job-trigger queue: `platform/run.sh deploy` creating the Cloud Tasks API, queue `chrysopoeia-trigger-local`, least-privilege trigger identity (custom role `run.jobs.run` + `run.jobs.runWithOverrides`), and Cloud Tasks agent token-creator grant; `platform/run.sh enqueue 2 15 accum-pilot-20261025` pilot, then `enqueue 78 30 accum-20261025` | Apply: 7 created, 35 unchanged (plus one cosmetic consumer-service state normalization: dropped zero/empty scaling defaults; no service change). Pilot: both tasks dispatched at their schedule times and completed as executions `chrysopoeia-cycle-local-bf7tm`/`-ls6ng` with independent fresh journals on the bucket; queue drained. Approved campaign bound: 80 executions × $1.50 session budget = $120 absolute worst case, expected ~$8-10 actual model cost; each execution is a two-cycle paper session; any produced plans are consumer-filled in paper. Kill switches: `gcloud tasks queues pause/purge chrysopoeia-trigger-local`. Queue idle cost $0. |
| 2026-10-25 | Consumer rollout (Harness self-learning step 3): `consumer/build.sh` (after fixing `.dockerignore` to whitelist the staged `consumer_outcome` schema — the 2026-10-10 build predated that file), push, `pulumi config set consumer_image_digest …@sha256:6807f5c7…`, `platform/run.sh deploy`; then two bounded harness `run` executions and three labeled synthetic `trade_plan_ready` publishes | Deploy created 15 consumer resources (service, filtered push subscription, dead-letter topic + retention sub, ledger bucket, identities, minute sweep); 21 unchanged. The two harness executions abstained (4/4 turns, $0.21739245 actual model cost — the trader declines coin-flip windows; no plan events produced). Synthetic publishes (snapshot_id `synthetic-verification-20261025`, excluded from gate metrics structurally: the history aggregate joins consumer outcomes to real harness turns): #1 rejected (`invalid trade plan event`, schema), #2 rejected (`event ID does not match` — consumer requires `turn-` + sha256 of `[snapshot_id, market_id]`), #3 `turn-9853f52d…` filled YES 10.204 shares @ 0.49, stake $5 + $0.10 fee on a fresh public quote, then settled by the minute sweep at market resolution NO with pnl −$5.10. All three lifecycle outcomes (`rejected`/`filled`/`settled`) published as `consumer_outcome` v1 and archived in BigQuery within ~2 s. Six transient sweep 503s (08:04–08:09) retried by Scheduler and self-recovered; dead-letter empty; ledger on the versioned consumer bucket. No real orders; Pub/Sub/Cloud Run/BigQuery cost ~$0. Model-produced deployed delivery remains pending a non-abstaining harness turn (accumulation step). The consumer stays deployed. |
| 2026-10-22 | `pulumi config set context_history_enabled true` + `CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh deploy`; `gcloud projects get-iam-policy`; `bq show` on the archive dataset | Apply created `roles/bigquery.jobUser` (project) and dataset `roles/bigquery.dataViewer` for the runner, updated the runner description and the job's archive table/location env vars; 17 unchanged. Both grants verified by IAM/bq reads. The runner SA did not run any query yet, and the pinned image predates the history feature, so the deployed query path remains unverified until the next image rollout. The optional Consumer publisher role activates only with a future `consumer_image_digest` rollout. Cost ~$0. |
| 2026-10-19 | `platform/build.sh` after splitting the dependency install into its own Docker layer; Pulumi repin to `sha256:13eac92e…`; one `platform/run.sh job --args=validate,--json --wait` | Scope: layer-cache ordering only; dependencies unchanged. Rebuilt image installs ADK 2.8.0/pydantic 2.13.4 and loads the bundled platform profile with `research=False` and `series=btc-updown-5m`. Pulumi updated only the job; 18 unchanged. Execution `chrysopoeia-cycle-local-mdptj` exited 0 and printed the platform profile summary. No model calls, market reads, or new resources. This build re-pushed the dependency layer because its content/position changed; later code-only or TOML-only changes should push small layers, unverified until the next such build. |
| 2026-10-18 | `platform/build.sh` with frozen-lock install; Pulumi repin to `sha256:3ae64def…`; one `platform/run.sh job --args=validate,--json --wait` | Image now installs `uv export --frozen --no-emit-project` with `--no-deps`; container reports ADK 2.8.0/pydantic 2.13.4 matching the verified lock (previous image drifted to ADK 2.12.0/pydantic 2.14.1). Both bundled profiles validated inside the image. Pulumi updated only the job; 18 unchanged. Execution `chrysopoeia-cycle-local-7jccr` exited 0 and loaded the BTC platform profile. No model calls, market reads, or new resources. |
| 2026-10-18 | Two-cycle BTC smoke `chrysopoeia-cycle-local-jj49n` (`run --journal /mnt/journal/btc-only-20261018-01`) under `configs/platform.toml` | BTC binding confirmed (markets `5818529`, `5818549`), but both turns failed with `ProposalOutput=None` before producing a proposal; no events archived. Booked $1.4077056 of conservative reservations; actual spend unknown. Exposes a trader missing-output defect, recorded in Harness verification. |
| 2026-10-18 | Wheel/image build; Pulumi image pin and config-only job update; one `platform/run.sh job --args=run,--journal=/mnt/journal/config-only-20261018-01 --wait` | Image `sha256:d6c13fc6fcababcae0c62066513b0d55c447af0fb86f460c5176d6589a286840` validated both bundled profiles before upload. Upload required longer timeouts and a final manifest retry after EOF; no rebuild or extra job execution. Pulumi updated only the job; final preview 19 unchanged. Execution `chrysopoeia-cycle-local-nr6tj` exited 0, stopped at configured `max_cycles=2`: one paper fill and one failed turn. Booked model cost $0.87996215 ($0.17610935 completed + $0.7038528 conservative failed-turn reservation; actual failed-turn billing unknown), below $1.50 session cap. Both emitted events reached BigQuery with metadata; original synthetic row retained. One 100 MiB-capped query, no new cloud resources or real orders. Journal retained at `gs://PROJECT_ID-chrs-journals-local/config-only-20261018-01/chrysopoeia.jsonl`, with one unmonitored open paper position. Full bounds/results in Harness verification. No Consumer rollout, scheduler, or BTC benchmark. |
| 2026-10-18 | Protection/retention update via `platform/run.sh deploy --skip-preview`; sanitized `pulumi stack export`; two date-filtered `bq query` checks, each capped at 100 MiB | Metadata-only apply, 19 resources unchanged. State confirms `protect=true` and `retainOnDelete=true` for dataset and table. Original message `21723946407689006`, raw payload, and attributes unchanged before/after. Nine Platform contract tests passed. No teardown, replacement, new publish, model, or forecast run. Estimated query cost ~$0, billing not measured; no temporary resources. |
| 2026-10-18 | `CHRYSOPOEIA_RUN_PLATFORM=1 PULUMI_CONFIG_PASSPHRASE='' platform/run.sh deploy --skip-preview`; one `gcloud pubsub topics publish chrysopoeia-events`; one date-filtered `bq query --maximum_bytes_billed=104857600` | Six archive resources created; existing 13 resources unchanged. First apply enabled the API but failed on transient DNS during identity creation; one retry completed. Subscription `chrysopoeia-events-bigquery` is ACTIVE. Synthetic event `archive-verification-20261018-01`, message `21723946407689006`, arrived in `PROJECT_ID.chrysopoeia_events_local.raw_events` with exact payload and all three attributes plus message/publish/subscription metadata. Exactly one publish and one query, query scan ceiling 100 MiB; ambient auth, no models, forecasts, orders, image rollout, consumer deployment, or job execution. Labeled synthetic row retained as verification evidence; no temporary cloud resources. Estimated incremental cost ~$0, billing not measured. Final preview: 19 unchanged, zero pending changes. |
| 2026-09-18 | Wheel-built image and Pulumi Cloud Run job; bounded `cycle` and `book` executions | Deployed harness accessed Vertex with the runner identity and journal bucket; succeeded after selecting Vertex-compatible model config. Operator-approved; under $0.02 Cloud Run cost. |
| 2026-09-27 | `pulumi refresh`; `pulumi up`; rebuild/pin image; three `gcloud beta run jobs execute chrysopoeia-cycle-<operator> --region <region> --wait` executions | Restored container deployment after discarding a VM experiment. Cached `cycle` was an idempotent no-op, `book` succeeded, fresh-capture `cycle` appended a turn. Journal bucket intentionally retained. |
| 2026-10-08 | Inline Python with `platform/infra/.venv/bin/python` called `drain()` against one temporary Pub/Sub topic and active subscription using ambient ADC; Harness CLI `outbox-pending`/`outbox-ack` | One synthetic valid trade-plan event was published once with confirmation; one matching message was pulled and acknowledged. The temporary subscription and topic were deleted after the check. Total duration was 22.87 s. Estimated incremental Pub/Sub cost was ~$0 within monthly free usage; billing was not measured. No model, market, Cloud Run, order, IAM, API-enablement, or `pulumi up` operation occurred. |
| 2026-10-10 | Temporary Consumer stack via `pulumi up` (18 creates; producer job env update; 0 replacements) with a pinned amd64 image and future-dated sweep cron; three synthetic paper events published to the temporary topic; one manual Scheduler run; ambient ADC | OIDC push reached the service on every delivery. Three defects found and fixed during the run: no `User-Agent` (Gamma 403), push parser rejected real envelope fields `message_id`/`publish_time`/`deliveryAttempt` (HTTP 400, retried by Pub/Sub), and books over 50 levels were rejected instead of truncated to the best 50. Final image: event 1 durably rejected (exit window expired during fixes), event 2 rejected by the pre-fix book parser, event 3 filled from a fresh quote and closed by the single sweep on its time exit. Ledger persisted across three revision deploys; HTTP results were 9×400 (pre-fix), 3×204 push, 1×204 sweep; dead-letter queue empty. Ten public Gamma/CLOB GETs (one 403), exactly the operator-raised cap of 10; no model calls or orders; about 30 minutes; estimated cost ~$0. Cleanup: ledger versions, all temporary resources, config keys, and four image versions deleted; default preview returned to 10 unchanged. The Pub/Sub API stayed enabled after a failed disable attempt, which led to `disable_on_destroy=False`. Settlement, dead-letter delivery, and concurrent-revision writers were not exercised. |
| 2026-10-12 | Harness `events.publish()` to temporary topic `eda-verify-1791816992`; one pull subscription filtered on `attributes.record_type = "trade_plan_ready"` and one unfiltered pull subscription | Published one real `turn_outcome` and one synthetic `trade_plan_ready` fixture. The filtered subscription received only `trade_plan_ready`; the unfiltered subscription received both, each with `record_type` and `schema_version=1` attributes. Both subscriptions and the topic were deleted and confirmed absent. This verifies the Pub/Sub filter boundary, not the undeployed Pulumi subscription; that remains pending the next deploy. |
| 2026-10-14 | `pulumi up` on `local-dev` repinning the rebuilt Harness image (`sha256:81485042…`) and switching job args to `run --journal /mnt/journal/run --max-cycles 2`; one `gcloud beta run jobs execute chrysopoeia-cycle-local --region us-central1 --project PROJECT_ID --wait` | The prior args `cycle --snapshot /mnt/journal/snapshot.json` had failed `invalid snapshot` against a stale 2026-09-27 snapshot. The retargeted job exited 0: two bounded cycles, both abstained, `stop_reason=max_cycles`, recorded model cost $0.33056625, no iteration errors. Vertex Google Search grounding ran in the deployed image (query counts 8 and 4). Both `turn_outcome` events reached the shared outbox sink (`outbox_enqueued` → `outbox_acknowledged`), confirming the deployed direct-publishing path; no `trade_plan_ready` event was produced. No consumer or subscription is deployed, so the subscription filter replacement remains untested. |
| 2026-10-14 | `pulumi up` on `local-dev` repinning the rebuilt Harness image (`sha256:0089b841…`, plan-check tool-schema fix); two `gcloud beta run jobs execute chrysopoeia-cycle-local --args=run,--journal=/mnt/journal/verify*… --wait` attempts, then one `--max-cycles 1` run | The first two executions failed closed on transient Vertex `503 UNAVAILABLE` (the first also reached the 15 m task timeout mid-second-turn). The third completed: one model-produced accepted plan, with `trade_plan_ready` and `turn_outcome` published to `chrysopoeia-events` from the deployed container and a harness paper fill recorded. Confirms the deployed direct-publishing and accepted-plan path; no Consumer or subscription is deployed, so the subscription `trade_plan_ready` filter replacement remains untested. Temporary `verify*` journals were removed. |

## Deferred services

No service below is required for the current deployment. Add one only after a
measured need and explicit approval.

| Need | Candidate | Boundary |
| --- | --- | --- |
| Shared authoritative records | Cloud SQL | Session storage is not the financial ledger |
| Document retrieval | Vertex AI RAG Engine | Provenance-linked evidence only |
| Long-term lessons | Vertex AI Memory Bank | Never authoritative for balances, risk, or lifecycle |
| Managed agent runtime | Vertex AI Agent Engine | Alternative runtime/deployment boundary |
| Independent consumer runtime | Pub/Sub-triggered Cloud Run | Implemented as the optional paper Consumer; live execution consumers remain future work |
| Secrets | Secret Manager | Credentials never enter prompts or session state |

Any authenticated execution remains prohibited under
[`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).
