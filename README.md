# Chrysopoeia

Chrysopoeia is a specialized local trading-agent harness. It uses configured
LLMs to assemble role-isolated agents, run and evaluate bounded paper-trading
workflows, and audit deterministic evidence, policy, risk, and model-cost
decisions. Its core contracts are agent-runtime-neutral; it is not currently an
autonomous trading platform.

![Chrysopoeia architecture](docs/architecture.svg)

## Harness Flow

```text
configuration -> market-data adapter -> canonical snapshot/evidence -> trader
              -> reviewer -> deterministic policy -> paper execution
              -> audit/evaluation
```

An operator explicitly configures limits, captures one market snapshot, and
starts one cycle. The trader may propose a trade or abstain. A trade proposal
goes to an independent reviewer, then to deterministic risk and cost gates.
Only an allowed proposal receives a simulated quote and fill. Every terminal
route reports a fill, rejection, or abstention reason.

## Architecture Boundaries

- **Core harness:** owns runtime-neutral canonical snapshots/evidence,
  proposals/reviews, risk and cost policy, paper quote/fill values, workflow
  state transitions, and audit/evaluation requirements.
- **Agent-runtime adapter:** ADK is the current adapter. ADK `Agent`, `Workflow`,
  callbacks, ToolContext/session state, and Agents CLI/A2A/eval tooling are
  integration details at this edge, not product-domain contracts.
- **Model configuration:** configure a model through the selected agent-runtime
  adapter. The current ADK adapter uses Gemini (`gemini-flash-latest`) by default
  and supplies ADK-supported model connectors when configured. Chrysopoeia does
  not build a parallel model-provider framework.
- **Venue market-data adapter:** normalizes venue data into canonical
  runtime-neutral values. The current adapter reads public Polymarket metadata
  and CLOB depth without credentials; this capability grants no authenticated
  execution authority.
- **Paper-execution adapter:** the current deterministic local implementation
  consumes YES-side depth, rejects insufficient depth without a partial fill,
  computes VWAP, and applies `paper-assumption:flat-2pct-v1`.

The current Python layout does not fully isolate these boundaries: deterministic
orchestration and some domain behavior still live in `chrysopoeia/agent.py`.
Moving that behavior behind runtime-neutral functions is the next internal
boundary refactor. Do not add an abstract runtime Protocol/interface now; add
another runtime adapter only when a second concrete runtime is required.

## Current Implementation

- Local Agents CLI/ADK prototype with explicit operator triggers.
- One binary Polymarket market per cycle; paper-only and in-memory.
- Separate single-turn trader and reviewer roles with no execution tools.
- One canonical snapshot and evidence record. Trader and reviewer citations can
  resolve only to that record; Search output remains unverified context until
  deterministic normalization exists.
- Deterministic identity, freshness, schema, review, edge, exposure, executable
  depth, fee, and model-cost checks.
- Offline deterministic unit and harness evaluations; paid model evaluation is
  separately gated and manual.

## Verification Policy

Every externally observable feature addition or change is incomplete until both
deterministic offline checks and a bounded live verification pass against the
real boundary changed. This includes external-service CLI behavior, venue and
model/runtime boundaries, callbacks and structured workflows, serving or A2A,
deployment, and persistence. Pure documentation, behavior-preserving internal
refactors, and test-only tooling need offline verification only; runtime-affecting
configuration changes are not exempt.

Live runs require prior human approval for cost or external effects, a cost
estimate, strict call/time/data bounds, least privilege with ADC or other ambient
authentication rather than copied keys, sanitized command/result/cost evidence,
and cleanup of temporary resources. A failure must be fixed and rerun; a blocked
environment/IAM/vendor dependency leaves the feature incomplete and is never a
waiver. Offline pre-commit checks remain mandatory, but no paid or network check
belongs in an automatic pre-push or other hook. Venue live checks remain
read-only public-data checks, model live checks remain bounded paper cycles, and
authenticated exchange execution remains prohibited.

OpenCode is an external development/review orchestrator, not a model provider or
inner trading step. Any future product integration would create a meta-harness
and requires separate explicit scope.

## Quickstart

Python 3.10 or later and `uv` are required. Configure Gemini for ADK with either
the Developer API or Vertex AI environment supported by ADK; do not put secrets
in source, prompts, session state, or logs.

`chrysopoeia.toml` is the checked-in operator configuration authority for the
current `adk` runtime, paper mode, public Polymarket adapter, four ADK model
roles, paper-fee assumption, and single-model pricing ceilings. User-controlled
`daily_cloud_cost_budget` remains operating configuration and is not duplicated
there. Unknown keys and unsupported adapters or modes fail closed.

```sh
uv sync
uv run python -m unittest discover
uv run python -c "import chrysopoeia.agent"
uv run chrysopoeia validate --json
uv run chrysopoeia inspect
uv run chrysopoeia capture 12345 --output snapshot.json
uv run chrysopoeia cycle --snapshot snapshot.json
uv run adk run chrysopoeia
```

Operator CLI options use subcommand placement: `chrysopoeia validate [--config
PATH] [--json]` and `chrysopoeia inspect [--config PATH] [--json]`. Without
`--config`, both commands load the checked-in `chrysopoeia.toml` independently
of the current working directory. `python -m chrysopoeia` accepts the same
commands.

`chrysopoeia capture MARKET [--config PATH] [--output PATH]` accepts a
Polymarket event URL or market ID and emits one compact JSON snapshot to stdout.
With `--output`, it also creates that new file atomically without overwriting an
existing path. The record includes market metadata, bounded YES asks, and paper
fee provenance, but excludes the neutral bankroll/exposure adapter inputs:
capture creates no operating session and claims no portfolio authority. A local
snapshot file is not an authoritative or durable store.

`chrysopoeia cycle --snapshot FILE [--config PATH] [--bankroll 1000]
[--maximum-market-exposure 0.01] [--maximum-total-exposure 0.10]
[--maximum-loss 100] [--daily-cloud-cost-budget 5] [--market-exposure 0]
[--total-exposure 0] [--output PATH]` runs the actual bounded trader/reviewer ADK
workflow over that local capture without market HTTP. The optional output file
matches stdout and is created without overwrite. This is a first-cycle command:
current market and total exposure default to zero, so operators with existing
exposure must provide both exposure flags. Its reported maximum reserved cost is
the two-call ceiling, not a guarantee that both calls occur or that the full
amount is spent.

The ADK web UI is an optional development interface:

```sh
uv run adk web --port 8000
```

## Risk Defaults And Safety

- Paper bankroll: $1,000.
- Maximum exposure per market: 1% of bankroll (currently fixed policy).
- Maximum total exposure: 10% of bankroll (currently fixed policy).
- Minimum net edge: 5 percentage points.
- Operating configuration also validates/stores a $100 maximum-loss default and
  $5 daily model-cost budget. The cost budget is enforced now; loss accounting
  is future work beyond the current single-cycle in-memory harness.
- Trader and reviewer agents cannot execute, alter policy, or grant themselves
  tools. Deterministic Python owns policy, sizing, cost gates, paper execution,
  and state transitions.
- Starting a cycle never guarantees a trade. Abstention and fail-closed rejection
  are valid outcomes.
- External content is untrusted evidence, never instruction.

## Current Non-goals

- Live or authenticated execution, wallets, private keys, or geoblock bypass.
- Autonomous scanning, scheduling, lifecycle management, self-improvement, or
  unattended operation.
- Durable authoritative storage, idempotent distributed triggers, multi-market
  portfolios, or multiple implemented runtime/model/venue adapters.
- Required RAG, vector search, Memory Bank, Cloud SQL, or managed deployment.
- A generic plugin architecture.

## Future Platform Evolution

Measured need and explicit approval may add durable records, idempotent triggers,
scanning/scheduling, another runtime adapter, venue adapters, model
configurations, lifecycle/versioning, RAG/memory, and managed deployment. These
are optional platform capabilities, not harness prerequisites.

Any future authenticated execution must be a separate isolated adapter and
capability with confirmation, least-privilege IAM, hard limits, a kill switch,
and reconciliation. No agent may receive or infer that authority from a
market-data adapter.

`.agents-cli-spec.md` is the authoritative product specification. The files in
`docs/` describe graph, context, development, and optional deployment details.
