# Google Cloud Architecture

Chrysopoeia uses Google Cloud's Gemini Enterprise Agent Platform where managed
context infrastructure is useful. ADK remains the application framework.

## Services

| Need | Google Cloud service | Chrysopoeia use |
| --- | --- | --- |
| Agent orchestration | Agent Development Kit (ADK) | Trader, reviewer, and deterministic workflow |
| Runtime | Agent Platform Runtime | Managed deployment, identity, tracing, and scaling |
| Scheduling | Cloud Scheduler | Emit authenticated, idempotent graph triggers |
| Session state | Agent Platform Sessions | Interactive and scheduled cycle histories |
| Authoritative data | Cloud SQL for PostgreSQL | Trading records, metrics, lifecycle events, and lesson provenance |
| RAG and vector search | Agent Platform RAG Engine with `RagManagedDb` | PDFs, official documentation, market research, and procedural playbooks |
| Long-term memory | Agent Platform Memory Bank | Extracted and consolidated agent lessons and user preferences |
| Embeddings | Vertex AI text embeddings | Semantic indexing and retrieval through RAG Engine |
| Evaluation | Agent Platform Evaluation and Example Store | Compare agent versions and memory-enabled behavior |
| Untrusted code | Agent Platform Sandbox | Later strategy experiments, never order execution |
| Secrets | Secret Manager | Later live-trading credentials |

There is no separate current Google product called ADP in this design. The two
relevant names are ADK, the open-source framework, and Gemini Enterprise Agent
Platform, the managed Google Cloud platform.

## Data Boundaries

Use two complementary storage paths:

1. **Authoritative relational data:** Cloud SQL for PostgreSQL stores snapshots,
   proposals, reviews, orders, fills, positions, resolutions, metrics, and
   lifecycle decisions.
2. **Semantic context:** RAG Engine and Memory Bank. These retrieve documents and
   lessons but never determine balances, exposure, fills, or agent retirement.

Vector retrieval is required for this project, but a vector match is evidence,
not truth.

## Corpora

Create separate RAG corpora so retrieval scope is explicit:

- `platform-reference`: ADK, Agent Platform, and Polymarket documentation.
- `market-research`: approved external reports and captured research, with
  source URL, publication time, market/category, and expiry metadata.
- `strategy-lessons`: sanitized procedural playbooks derived only from resolved
  outcomes and reviewed evaluations.

The PDFs under `docs/reference/` belong in `platform-reference`. Upload source
documents to Cloud Storage, then import them into RAG Engine. Keep the source
files and corpus object IDs so every retrieved chunk remains traceable.

## Retrieval

For each proposal or review:

1. Apply metadata filters for corpus, market/category, source date, and status.
2. Run vector retrieval with a small result limit.
3. Reject expired or provenance-free chunks.
4. Preserve citations and retrieval scores in the cycle record.
5. Give traders and reviewers independently retrieved context.

Use `RagManagedDb`, RAG Engine's default managed vector database, first. It
requires no separate vector infrastructure and supports KNN and ANN. Move to
Agent Platform Vector Search only when corpus scale or measured latency and
recall require it.

## Memory

Memory Bank and RAG serve different jobs:

- RAG retrieves shared external knowledge and versioned procedural playbooks.
- Memory Bank extracts and consolidates evolving agent lessons and user
  preferences across sessions.

Memory generation happens after completed cycles or resolutions. Persist
provenance in the relational ledger before sending sanitized material to Memory
Bank or the `strategy-lessons` corpus.

## Initial Cloud Setup

- Select one supported region; `europe-west3` is GA for RAG Engine and is the
  default European choice unless deployment requirements dictate otherwise.
- Enable Agent Platform, Cloud Storage, and Cloud SQL Admin APIs.
- Create a PostgreSQL Cloud SQL instance in the runtime region with private IP,
  automated backups, point-in-time recovery, and encrypted connections.
- Use Application Default Credentials locally and workload identity in runtime.
- Grant the application service account only the required Agent Platform and
  storage permissions, plus `roles/cloudsql.client` for database connectivity.
- Read the database password or IAM database configuration from Secret Manager;
  never place credentials in source, prompts, session state, or logs.
- Use ADK's `DatabaseSessionService` with a PostgreSQL SQLAlchemy URL when
  database-backed ADK sessions are required. Keep its session tables separate
  from the authoritative trading schema; ADK session state is not the ledger.
- Configure a RAG corpus using the default `RagManagedDb` and a Vertex AI text
  embedding model.
- Do not create standalone Vector Search, Spanner, queues, or Kubernetes for the
  first implementation.
