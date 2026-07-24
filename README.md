# Chrysopoeia

Chrysopoeia is an interactive, self-improving Polymarket trading system. It
creates and versions trader agents, has reviewer agents challenge their trades,
paper trades approved proposals, evaluates results, and retires agents that fail
objective performance or risk rules. The user triggers or supervises the system;
the user is not expected to design trading algorithms.

![Chrysopoeia architecture](docs/architecture.svg)

## Operating Loop

Chrysopoeia separates two decision-action cycles (DACs):

- **Research DAC:** discover -> research -> propose -> paper trade -> evaluate
  agents and strategies.
- **Execution DAC:** consume an approved proposal -> deterministic risk check ->
  execute -> reconcile -> independent post-trade review.

Live execution remains outside the initial scope. Any later execution boundary
must retain hard limits and a kill switch that no agent can override.

1. A user or schedule triggers an evaluation cycle.
2. One or more trader agents research markets and propose trades or successor
   strategies.
3. One or more reviewer agents challenge the thesis, evidence, price, and risk.
4. Deterministic Python checks eligibility, exposure, liquidity, sizing, and
   approval requirements.
5. A single execution boundary paper trades approved proposals.
6. The system reconciles fills and resolved markets, then measures P&L,
   drawdown, Brier score, calibration, and policy violations.
7. Deterministic lifecycle rules promote, pause, or retire each versioned trader
   agent. Reviewer analysis explains the decision but cannot override the rules.
8. Retained evidence, decisions, outcomes, and distilled lessons inform newly
   generated agent versions.

Context is assembled separately for traders, reviewers, and deterministic
controls. Sessions hold one cycle's working state; durable records remain the
source of truth; only consolidated, provenance-linked lessons become memory.
See `docs/context-engineering.md`.

## User Journey

The user supplies goals and limits, not trading algorithms. On first run the
coordinator asks for any missing choices, then creates:

- A paper account with the configured bankroll and risk policy.
- An initial trader-agent version and reviewer-agent version.
- A watchlist or market-discovery scope.
- An inactive schedule; nothing runs automatically until the user enables it.

The user can then issue natural-language commands through the ADK CLI or web UI:

- `Set up paper trading for active crypto markets.`
- `Watch these Polymarket URLs: ...`
- `Find liquid markets resolving within 30 days.`
- `Run one trading cycle now.`
- `Explain the proposals and reviewer decisions.`
- `Show positions, P&L, drawdown, and agent performance.`
- `Evaluate underperforming agents and propose successors.`
- `Run every hour.`
- `Pause all trading.`

Each command is converted into validated structured state. A command such as
`Run one trading cycle now` starts the same decision workflow used by the
scheduler:

1. Resolve the configured watchlist or discovery scope.
2. Filter closed, stale, illiquid, or unsupported markets in ordinary Python.
3. Capture one immutable market and portfolio snapshot.
4. Retrieve relevant RAG evidence and validated lessons.
5. Ask active trader agents for structured proposals.
6. Ask reviewer agents for independent structured decisions.
7. Apply deterministic risk and sizing rules.
8. Simulate approved orders and persist the complete audit trail.
9. Return a concise report to the user.

The coordinator may return `no trade`. Starting a cycle never guarantees an
order. Scheduling repeats the trigger, not an open-ended autonomous prompt.

The normal operating mode uses a cheap deterministic scan every five minutes.
It invokes RAG and model-backed trader or reviewer nodes only when market,
evidence, position, or time thresholds open the opportunity gate. Decision,
lifecycle, and learning workflows are separate versioned ADK graphs. See
`docs/agent-graphs.md`.

## Initial Delivery

- Use public Polymarket data and paper trading only; require no wallet secrets.
- Support interactive triggers first, then scheduled evaluation cycles.
- Let the system generate trading approaches; do not require user-authored
  algorithms.
- Provide a versioned skill catalog that agents discover and load on demand;
  keep permanent agent instructions minimal rather than injecting every trading
  method into every prompt.
- In the target architecture, construct each sub-agent with an explicit
  role-specific tool allowlist; expose MCP only where that role requires it, and
  never give research or reviewer agents execution tools.
- Retain citations with forecasts and reviews.
- Use RAG and vector retrieval for official documentation, external research,
  and validated procedural lessons.
- Simulate fills against executable order-book depth, spread, and fees.
- Store agent versions, prompts, model settings, proposals, reviews, decisions,
  fills, metrics, lifecycle events, and lessons in Cloud SQL for PostgreSQL.
- Compare agents against simple market and no-trade benchmarks.
- Start calibration adjustments only after 30 resolved forecasts.

## Risk Defaults

- Paper bankroll: $1,000.
- Maximum exposure per market: 1% of bankroll.
- Maximum total exposure: 10% of bankroll.
- Minimum net edge: 5 percentage points.

## Boundaries

- Trader agents research, forecast, propose trades, and propose successor
  strategies. They never call the execution API directly.
- Reviewer agents critique and recommend approval, revision, or rejection. They
  cannot place orders or bypass policy.
- Deterministic Python controls eligibility, risk, sizing, execution, accounting,
  and agent lifecycle decisions.
- Agents do not rewrite themselves in place. A proposed successor is a new,
  auditable version that begins in paper trading.
- Memory cannot place trades, override policy, or determine lifecycle state.
  Authoritative records and deterministic metrics always take precedence.
- An agent may be retired only after a configured minimum sample size, except
  for immediate risk-policy violations or hard loss limits.
- Live trading, private keys, authenticated APIs, and geoblock workarounds are
  outside the initial delivery. Later live trading must use one isolated
  execution tool, hard limits, a kill switch, and explicit ADK confirmation.

## Development

Development follows `specify -> study -> scaffold -> build -> evaluate -> deploy
-> publish -> observe`. See `.agents-cli-spec.md` for the product specification
and `docs/development-lifecycle.md` for gates. This repository is currently a
hand-built prototype and has not yet been enhanced by Agents CLI.

```sh
uv sync
uv run adk run chrysopoeia
uv run adk web --port 8000
```

See `AGENTS.md` for development constraints and verification commands.
See `docs/gcp-architecture.md` for the Google Cloud deployment and RAG design.
