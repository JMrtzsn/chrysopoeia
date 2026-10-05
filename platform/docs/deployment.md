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
- This job is not an HTTP server. Paper fills and exits are currently simulated
  in-process only while the paper loop runs; event publishing/subscription is not
  implemented. No always-on harness or manager is required by the target design.
- A future HTTP/request adapter calls the same harness core as the CLI. The
  platform remains a deployment/trigger adapter and never imports harness code.
  Independent paper and execution consumers use the same `trade_plan_ready`
  contract and own separate ledgers and outcomes.
- Google API authentication uses the runner's ambient identity. Harness code
  never provisions cloud resources or invokes `gcloud`/`pulumi`.

The single-operator deployment is Level 2. Multi-tenant or public use requires
separate design and approval.

## Change and verification boundary

Run Pulumi preview and applies from `platform/`; see
[`../AGENTS.md`](../AGENTS.md) and [`../ROADMAP.md`](../ROADMAP.md). Live applies,
image publication, and job executions require approval and bounded verification
per [`../../harness/docs/verification.md`](../../harness/docs/verification.md).
Do not change Cloud Run environment variables outside Pulumi:
`gcloud beta run jobs update --set-env-vars` replaces the full environment and
can desynchronize state.

## Recorded platform checks

| Date | Command / boundary | Result |
| --- | --- | --- |
| 2026-09-18 | Wheel-built image and Pulumi Cloud Run job; bounded `cycle` and `book` executions | Deployed harness accessed Vertex with the runner identity and journal bucket; succeeded after selecting Vertex-compatible model config. Operator-approved; under $0.02 Cloud Run cost. |
| 2026-09-27 | `pulumi refresh`; `pulumi up`; rebuild/pin image; three `gcloud beta run jobs execute chrysopoeia-cycle-<operator> --region <region> --wait` executions | Restored container deployment after discarding a VM experiment. Cached `cycle` was an idempotent no-op, `book` succeeded, fresh-capture `cycle` appended a turn. Journal bucket intentionally retained. |

## Deferred services

No service below is required for the current deployment. Add one only after a
measured need and explicit approval.

| Need | Candidate | Boundary |
| --- | --- | --- |
| Shared authoritative records | Cloud SQL | Session storage is not the financial ledger |
| Document retrieval | Vertex AI RAG Engine | Provenance-linked evidence only |
| Long-term lessons | Vertex AI Memory Bank | Never authoritative for balances, risk, or lifecycle |
| Managed agent runtime | Vertex AI Agent Engine | Alternative runtime/deployment boundary |
| Event transport/consumer runtime | Pub/Sub, HTTP, local stream, Cloud Run, or another runtime | Select only after delivery and consumer exit-protection guarantees are specified |
| Secrets | Secret Manager | Credentials never enter prompts or session state |

Any authenticated execution remains prohibited under
[`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).
