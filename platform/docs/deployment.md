# Managed GCP deployment

**Status:** Deployed for one operator. Local harness use does not require Google
Cloud.

## Deployed shape

- `harness/` builds a wheel and container image. `platform/` builds/publishes the
  image and deploys the Pulumi program in `infra/`.
- Pulumi owns a versioned journal bucket, runner service account, Artifact
  Registry repository, and one Cloud Run job. Live images are pinned by digest,
  never a floating tag.
- The job runs the selected `chrysopoeia` CLI entrypoint on demand. The bucket is
  mounted at `/mnt/journal`; journal semantics belong to the harness.
- The harness owns market selection, cadence, recovery, and stopping. The
  platform launches the process but does not drive cycles.
- Re-running the job starts a fresh bounded session only when given a new
  journal. The stored args reuse `/mnt/journal/run`, so a second execution
  resumes the finished session and stops at once at its cycle cap. Override per
  execution, for example
  `gcloud beta run jobs execute chrysopoeia-cycle-local --region us-central1 --args=run,--journal=/mnt/journal/run-$(date +%s),--max-cycles=2`.
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

Harness drains old pending events before `cycle`/`run` and between run cycles,
publishes all canonical event types to one topic with `event_id`, `record_type`,
and `schema_version` attributes, and acknowledges
only after confirmation. Failures leave events pending and may duplicate
delivery, so consumers deduplicate by `event_id`. Platform retains topic and IAM
only; it has no publisher wrapper. No authenticated trading is part of this
milestone.

With neither consumer setting, no consumer resources exist. Setting
`consumer_image_digest` without `pubsub_topic` is a configuration error. With both
settings, messages retain for seven days, retry with bounded backoff, and
dead-letter after ten attempts. Recover by reading the retained dead-letter
subscription, correcting the transient cause, and republishing the original
message data unchanged; stable `event_id` deduplication makes replay safe.

The single-operator deployment is Level 2. Multi-tenant or public use requires
separate design and approval.

## Change and verification boundary

Run Pulumi preview and applies from `platform/`; see
[`../AGENTS.md`](../AGENTS.md) and [`../ROADMAP.md`](../ROADMAP.md). Live applies,
image publication, and job executions require approval and bounded verification
per [`../../harness/docs/verification.md`](../../harness/docs/verification.md).
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
