# Optional Google Cloud Deployment Profile

Selected profile (operator-approved 2026-09-15): **persistent base + scripted
ephemeral sessions**, cost-sensitive, single operator, Level 2 scope.

- Persistent (Pulumi program in `infra/`): one versioned GCS journal bucket and
  one least-privileged runner service account
  (`roles/aiplatform.user` project-wide, `roles/storage.objectAdmin` on that
  bucket). Nothing else. State is a local file backend.
- Ephemeral (`infra/script/session.sh`): a spot e2-small Debian VM per
  operator session, running the harness directly (no container image), with
  the journal bucket mounted via gcsfuse at `/mnt/journal`; the VM and local
  commands share one authoritative journal. Exit path is an explicit teardown;
  idle cost after teardown is exactly zero; per-session compute is minutes of
  one small vCPU.
- Deferred per the adoption triggers below: Cloud Scheduler, Cloud Run jobs,
  Cloud SQL, RAG Engine, Memory Bank, managed runtime, and any multi-tenant
  or public-facing posture (Level 3 requires explicit design before anything
  exists).

The harness itself never provisions or mutates cloud resources and must not
run `gcloud`. Application Default Credentials (ADC) provide authentication to
configured Google APIs. ADC does not provision APIs, billing, IAM, databases,
networks, or an agent runtime; `infra/` (Pulumi program and session script) is
the only sanctioned operator tooling for cloud changes.

Application Default Credentials (ADC) provide authentication to configured
Google APIs. ADC does not provision APIs, billing, IAM, databases, networks, or
an agent runtime, and the harness must not run `gcloud` or change them.

## Adoption Triggers

Adopt this profile only with explicit approval and a measured requirement for
one or more of:

- durable authoritative trading/audit records;
- idempotent remote triggers or managed scheduling;
- managed runtime identity, scaling, tracing, or recovery;
- provenance-filtered document retrieval or consolidated long-term memories;
- controlled behavior evaluation against a managed model endpoint.

No service below is a Phase 1 harness requirement. Select only the services
needed; do not scaffold the entire profile preemptively.

## Candidate Services

| Future need | Candidate service | Boundary |
| --- | --- | --- |
| Managed agent runtime | Agent Platform Runtime | Deployment, identity, tracing, scaling |
| Scheduled triggers | Cloud Scheduler | Emits authenticated idempotent triggers; no trading logic |
| Conversation sessions | Agent Platform Sessions | Working history, never authoritative ledger |
| Authoritative records | Cloud SQL for PostgreSQL | Snapshots, decisions, fills, metrics, versions, provenance |
| Document retrieval | Agent Platform RAG Engine with `RagManagedDb` | Source-linked context, never balances or policy |
| Long-term memory | Agent Platform Memory Bank | Consolidated lessons/preferences, never authority |
| Evaluation | Agent Platform Evaluation/Example Store | Optional managed behavior comparison |
| Secrets | Secret Manager | Future service credentials; never prompts/session state |

ADK remains the current agent-runtime adapter. The optional platform may still
use ADK and Google Cloud, but neither is mandated by core harness contracts.
Configure models through the selected runtime adapter; the current ADK adapter
supplies its supported model connectors.

## Data Boundaries

If durable platform capabilities are approved, keep these paths distinct:

1. **Authoritative relational data:** Cloud SQL stores immutable or versioned
   snapshots, proposals, reviews, decisions, orders/fills, positions,
   resolutions, metrics, lifecycle events, and lesson provenance.
2. **Semantic context:** RAG Engine and Memory Bank retrieve documents or
   lessons. A vector match is evidence, not truth, and never determines balance,
   exposure, fill, execution authorization, or lifecycle state.
3. **Session state:** ADK session storage holds conversation-scoped working data,
   not the trading ledger.

Vector retrieval is optional. Add it only when bounded canonical snapshot
evidence no longer meets an approved use case and retrieval quality can be
evaluated.

## Optional RAG And Memory Design

If approved, separate corpora by trust and retention scope, for example:

- `platform-reference`: ADK, platform, and venue documentation;
- `market-research`: approved reports with URL, publication time, category, and
  expiry metadata;
- `strategy-lessons`: sanitized procedures derived from resolved outcomes and
  reviewed evaluations.

Filter by source scope and date before a small vector retrieval, reject expired
or provenance-free chunks, preserve citations/scores, and retrieve trader and
reviewer context independently. Start with managed `RagManagedDb`; consider
separate vector infrastructure only after measured scale, latency, or recall
requires it.

Memory generation occurs after completed cycles or resolutions. Persist lineage
in the authoritative store before publishing sanitized content. RAG retrieves
shared knowledge; Memory Bank consolidates evolving lessons/preferences. Neither
can place trades or override deterministic policy.

## Approved Setup Constraints

If this profile is selected later:

- choose one supported region and least-privilege runtime identity;
- obtain approval before enabling APIs, billing resources, networking, or paid
  evaluations;
- use private connectivity, encryption, backups, and point-in-time recovery for
  authoritative storage where required;
- keep ADK session tables separate from the authoritative trading schema;
- keep credentials in Secret Manager or approved environment configuration,
  never source, prompts, session state, traces, or logs;
- add only the selected runtime/storage/retrieval services—no speculative
  Kubernetes, queues, or vector infrastructure.
