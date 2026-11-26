# Managed GCP deployment

**Status:** Deployed for one operator. Local harness use does not require Google
Cloud.

## Deployed shape

- `harness/` builds a wheel and container image. `platform/` builds/publishes the
  image and deploys the Terraform root in `infra-tf/` (state in the
  versioned GCS bucket `PROJECT_ID-chrs-tfstate-local`). `Dockerfile` installs the
  locked dependencies in their own layer before copying the wheel and configs, so
  a code or config change reuses the cached dependency layer and pushes only
  small layers; changing `uv.lock` is still a full re-push.
- The image installs the exact `uv.lock` export produced by `build.sh`
  (`uv export --frozen --no-emit-project`) with `--no-deps`, then the wheel
  itself. Installing the wheel alone lets transitive dependencies drift and has
  changed agent behavior; keep the image dependency set identical to the lock
  that passed offline and live checks.
- Terraform owns a versioned journal bucket, runner service account, Artifact
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
  and digest update, not extra CLI setting flags.
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
  `time.format(sys.now())` (ISO-8601; Workflows has no strftime) and calls the
  native `googleapis.run.v2.projects.locations.jobs.run` connector with
  `skip_polling` and journal override `/mnt/journal/esports-<ISO stamp>`, so
  every tick is an independently capped $3 session. A closed session journal
  cannot be resumed, so one journal per tick is required. Secrets stay ambient;
  204/`URL_CRAWLED` scheduler log entries alongside the real 200 are normal.
  `scan_paused=true` pauses the schedule without deleting it. Idle ticks spend
  nothing but reach the 900-second task timeout and are marked FAILED (known
  cosmetic limitation). Worst case: ten $3 sessions/day.
- The native billing budget `Chrysopoeia spend budget (local)` is deployed:
  1000 SEK/month (≈$100; the billing account `BILLING_ACCOUNT_ID` uses SEK and
  rejects USD amounts with `INVALID_ARGUMENT`), filtered to this project,
  alerting at 50/90/100% to the default billing-account recipients. Terraform
  `google_billing_budget` sits behind `budget_amount_usd` (whole units) and
  `budget_currency` (default SEK). Local billing-budgets API calls need
  `gcloud config set billing/quota_project PROJECT_ID`; the Terraform provider
  sets `user_project_override` and `billing_project` because it ignores the
  ADC quota project.
- Re-running the job starts a fresh bounded session only when given a new
  journal. The stored args reuse `/mnt/journal/run`, so a second execution
  resumes the finished session and stops at once at its cycle cap. Override per
  execution, for example
  `gcloud beta run jobs execute chrysopoeia-cycle-local --region us-central1 --args=run,--journal=/mnt/journal/run-$(date +%s)`.
- This job is not an HTTP server. Paper fills and exits are simulated in-process
  only while the paper loop runs. Optional `pubsub_topic` Terraform variable
  creates a topic and only a topic-scoped `roles/pubsub.publisher` grant for the
  runner. It sets `CHRYSOPOEIA_EVENT_SINK=pubsub:projects/<project>/topics/<topic>`
  on the plain Harness CLI image. Absent configuration leaves execution unchanged.
- When both `consumer_image_digest` and `pubsub_topic` are set, Terraform adds the
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
  chrysopoeia-trigger-<operator>` stops or abandons a campaign.

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

When `pubsub_topic` is configured, Terraform also creates a protected BigQuery
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
both `[history].enabled = true` in the bundled Harness profile and the Terraform
`context_history_enabled = true` variable. Terraform then grants the runner project-level
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

Rows have no configured expiration. The dataset and both tables (`raw_events`, `open_positions`) have Terraform
`prevent_destroy`; the table also has provider deletion protection, and dataset destruction cannot delete its contents.
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
`observer_invoker_member`), Terraform creates five resources: service account
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
Keep their existing project, dataset ID, table ID, location, and Terraform
addresses. Normal runtime updates reuse them. Protection blocks accidental deletion
or replacement, including removal of `pubsub_topic`: `prevent_destroy`,
`deletion_protection`, the protections test in `gates.sh`, and the conftest
plan policy all block it. Do not disable these safeguards
to get past a deployment error.

Recreate only the intended runtime resources, not storage. Keep the current
Terraform state; the backend is the versioned, owner-only GCS bucket
`PROJECT_ID-chrs-tfstate-local` (object versions are the backup), named in the
operator-local, git-ignored `platform/infra-tf/backend.hcl`. The
retired Pulumi state is archived under `archive/pulumi-2026-11-18/` there. Do
not erase state to reset infrastructure. A normal full-stack destroy is blocked
by protected resources, rather than silently deleting history. Other storage,
including the paper journals bucket, still needs its own preservation review.

If state must be recreated, restore a prior object version first. If that is
not possible, add `import` blocks for the existing storage before any apply;
never create an empty replacement archive. Example:

```hcl
import {
  to = google_bigquery_dataset.event_archive[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local"
}
import {
  to = google_bigquery_table.raw_events[0]
  id = "projects/PROJECT_ID/datasets/chrysopoeia_events_local/tables/raw_events"
}
```

Import only into state that is missing these resources. Recover/import other
still-existing infrastructure too, then plan and require no storage
replacement or deletion before the separately approved apply. Use the existing
source, not generated replacement code. Recreating a subscription does not delete archived
rows, but its backlog and events published during a subscription gap are not
preserved automatically.

These controls prevent Terraform lifecycle deletion; they are not immutable/WORM
storage or a backup. Privileged SQL deletion, external table/project deletion,
and destructive in-place schema changes require separate access/backup controls.
No storage teardown is part of verification.

## Change and verification boundary

Plan and apply only through `platform/run.sh`; see
[`../AGENTS.md`](../AGENTS.md). Live applies,
image publication, and job executions require approval and bounded verification
per [`../../harness/docs/verification.md`](../../harness/docs/verification.md).
Running the platform is explicit and off by default:
`CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh deploy` runs `infra-tf/gates.sh`,
saves a plan, checks it with conftest (`infra-tf/policy/`), and applies only
that saved plan. `platform/run.sh drift` is a read-only
`plan -detailed-exitcode` (0 = no drift, 2 = drift) and needs no variable.
Image pins and other values live in the operator-local
`infra-tf/terraform.tfvars`.
The GCS-FUSE single-writer ceiling applies, so avoid deploying while a push or
sweep is in flight.
The optional Pub/Sub and Scheduler APIs use `disable_on_destroy=False`, so
removing the integration never disables a shared API.
For the approved temporary live test, choose a future cron in
`consumer_sweep_schedule` before applying, then manually trigger exactly one sweep. Restore the
operator-selected schedule afterward; shorter intervals reduce exit-monitoring
latency but increase invocation cost.
Do not change cloud resources outside Terraform:
`gcloud beta run jobs update --set-env-vars` replaces the full environment and
creates drift.
