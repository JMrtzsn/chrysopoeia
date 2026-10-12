# Chrysopoeia

Chrysopoeia is a trading-agent harness for finding and paper-trading public
markets under operator-set session limits. The operator sets limits, not market
picks or trade ideas. The current product selects Polymarket markets and runs
bounded decision cycles; citable research tools are planned. Authenticated
execution is not implemented.

## Current product

- A bounded local loop discovers public Polymarket markets, captures data,
  proposes or abstains, reviews proposals, applies deterministic risk/cost
  gates, and currently records in-process paper fills and outcomes.
- The journal records paper sessions, turns, positions, marks, exits, settlements,
  and model cost. `cycle` returns a reviewed and policy-accepted
  `trade_plan_ready` JSON event; `run` consumes it in-process, while `consume`
  consumes an existing event into the local paper journal using a fresh quote.
  The journal outbox and Platform Pub/Sub publisher are optional and disabled by
  default.
- Google Search context is currently uncitable. Paper exits are simulated by the
  bounded local loop. The independent paper-only Pub/Sub consumer owns separate
  entry/exit simulation and accounting. No always-on harness is required.
- The checked-in Vertex default is `gemini-3.5-flash` at the `us` model endpoint,
  priced at $1.65 input and $9.90 text output per million tokens. The model
  endpoint is separate from the Cloud Run resource region.
- OpenRouter is opt-in through an alternate `--config` with
  `models.adapter = "adk-registry"`, OpenRouter model IDs, and matching explicit
  prices. Supply its API key only through the shell `OPENROUTER_API_KEY`; never
  put it in config. The checked-in default remains Vertex and does not
  auto-select OpenRouter merely because that environment variable exists.

## Start locally

Run from `harness/`; requires Python 3.10+ and `uv`.

```sh
uv sync --all-groups --all-extras
uv run chrysopoeia validate --json
uv run adk run chrysopoeia
```

Required tests and lint/type checks are listed in `harness/AGENTS.md`.
For CLI syntax, run `uv run chrysopoeia --help` or a subcommand's `--help`.
The main operator flow is `discover` → `capture` → `cycle`; `run` starts a
bounded journal-backed session. `book`, `mark`, and `settle` inspect or update
the paper journal. No cycle guarantees a trade.

## Documentation map

- [Product specification](.agents-cli-spec.md): authoritative product scope,
  safety contract, and acceptance.
- [Harness architecture and evidence](harness/docs/architecture.md): implemented
  flow, tool boundary, citations, and ownership.
- External reference papers under `harness/docs/reference/` are background
  material, not product requirements.
- [Paper accounting](harness/docs/accounting.md): journal and position contract.
- [Harness verification](harness/docs/verification.md): live-check policy and
  recorded model/venue runs.
- [Platform deployment](platform/docs/deployment.md): Cloud Run shape, policy,
  and platform verification record.
- [Paper consumer](consumer/README.md): independent push/sweep and ledger contract.
- [Harness roadmap](harness/ROADMAP.md) and [platform roadmap](platform/ROADMAP.md):
  independent work queues.
- [Harness proposals](harness/docs/proposals.md): unapproved feature proposals.

## Event-driven architecture

The system is event-driven: each unit owns its state and publishes what happened.
Current and planned (see roadmaps) patterns:

| Pattern | Here |
| --- | --- |
| Domain events / event notification | `trade_plan_ready` today; outcome events (abstained, rejected, opened, closed, settled) planned |
| Transactional outbox | Harness journal outbox; publish after the durable write |
| At-least-once delivery + idempotent consumer | Pub/Sub retries; consumers deduplicate by stable `event_id` |
| Dead-letter queue | Consumer subscription dead-letters after ten attempts |
| CQRS read model / projections | Planned: Pub/Sub BigQuery subscriptions for analytics views |
| Decision (outcome) logging | Planned: successes and failures, including reviewer and policy rejections |
| Retrieval-augmented context / closed learning loop | Approved future item: past outcomes as untrusted, provenance-carrying evidence |

This is not event sourcing: each unit's own ledger stays authoritative; analytics
copies are never used for balances, risk, or lifecycle decisions.

## Repository boundaries

`harness/` owns the producer and versioned event schema. `consumer/` validates
that schema as data and owns paper effects in a separate ledger. `platform/`
owns conditional GCP resources and consumes pinned image digests; it imports
neither package. See each folder's `AGENTS.md` for work-unit rules.
