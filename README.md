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
  and model cost. The target architecture instead emits a reviewed and
  policy-accepted `trade_plan_ready` event for independent paper or execution
  consumers; that event boundary is not implemented yet.
- Google Search context is currently uncitable. Paper exits are simulated by the
  bounded local loop; citable research tools and event consumers remain planned
  work. No always-on harness or manager is required.
- The checked-in Vertex default is `gemini-3.5-flash` at the `us` model endpoint,
  priced at $1.65 input and $9.90 text output per million tokens. The model
  endpoint is separate from the Cloud Run resource region.

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
- [Harness roadmap](harness/ROADMAP.md) and [platform roadmap](platform/ROADMAP.md):
  independent work queues.
- [Harness proposals](harness/docs/proposals.md): unapproved feature proposals.

## Repository boundaries

`harness/` owns the agent loop, trading policy, paper accounting, CLI, and tests.
It publishes a wheel/image and never provisions cloud resources. `platform/`
owns Pulumi and the Cloud Run job, consumes a pinned harness image, and never
imports the harness package. See each folder's `AGENTS.md` for work-unit rules.
