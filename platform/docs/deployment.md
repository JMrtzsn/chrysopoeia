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
- This job is not an HTTP server. Paper fills and exits are simulated in-process
  only while the paper loop runs. Optional `pubsub_topic` Pulumi configuration
  creates a topic and only a topic-scoped `roles/pubsub.publisher` grant for the
  runner. It also enables the Harness journal outbox and Platform publisher
  adapter. Absent configuration leaves the existing CLI execution unchanged.
- A future HTTP/request adapter calls the same harness core as the CLI. The
  platform remains a deployment/trigger adapter and never imports harness code.
  Independent paper and execution consumers use the same `trade_plan_ready`
  contract and own separate ledgers and outcomes.
- Google API authentication uses the runner's ambient identity. Harness code
  never provisions cloud resources or invokes `gcloud`/`pulumi`.

The adapter drains old pending events before `cycle`/`run`, invokes the Harness
CLI, then drains new events. It publishes the exact pending JSON line as Pub/Sub
data and acknowledges through the Harness CLI only after publish confirmation.
Failures exit nonzero without acknowledging, so retries may duplicate delivery;
future consumers must deduplicate by `event_id`. The adapter never parses the
journal or imports Harness modules. No subscriber or authenticated trading is
part of this milestone.

Before setting `pubsub_topic`, provision an active subscription separately and
choose its retention policy. This code creates no subscription and cannot
guarantee delivery to a future subscriber when no subscription is active;
Pub/Sub does not retain topic messages for a subscription created later.

The single-operator deployment is Level 2. Multi-tenant or public use requires
separate design and approval.

## Change and verification boundary

Run Pulumi preview and applies from `platform/`; see
[`../AGENTS.md`](../AGENTS.md) and [`../ROADMAP.md`](../ROADMAP.md). Live applies,
image publication, and job executions require approval and bounded verification
per [`../../harness/docs/verification.md`](../../harness/docs/verification.md).
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

## Deferred services

No service below is required for the current deployment. Add one only after a
measured need and explicit approval.

| Need | Candidate | Boundary |
| --- | --- | --- |
| Shared authoritative records | Cloud SQL | Session storage is not the financial ledger |
| Document retrieval | Vertex AI RAG Engine | Provenance-linked evidence only |
| Long-term lessons | Vertex AI Memory Bank | Never authoritative for balances, risk, or lifecycle |
| Managed agent runtime | Vertex AI Agent Engine | Alternative runtime/deployment boundary |
| Independent consumer runtime | Pub/Sub-triggered Cloud Run or another runtime | Producer transport is selected; consumer effects and exit-protection guarantees remain future work |
| Secrets | Secret Manager | Credentials never enter prompts or session state |

Any authenticated execution remains prohibited under
[`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).
