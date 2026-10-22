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
  Direct event delivery through the journal outbox is optional and disabled by
  default. `CHRYSOPOEIA_EVENT_SINK` sends `trade_plan_ready` and `turn_outcome`
  through one loopback HTTP endpoint or Pub/Sub topic; subscriptions filter by
  record type.
- Google Search grounding and financial-analysis results are normalized into
  citable snapshot-bound evidence. Paper exits are simulated by the bounded local
  loop. The independent paper-only Pub/Sub consumer owns separate
  entry/exit simulation and accounting. No always-on harness is required.
- The checked-in Vertex default is `gemini-3.5-flash` at the `us` model endpoint,
  priced at $1.65 input and $9.90 text output per million tokens. The model
  endpoint is separate from the Cloud Run resource region.
- The model provider is BYOK and applies to every role. Set
  `models.adapter = "adk-registry"` with provider model IDs (OpenRouter, Ollama,
  OpenAI, ...) and matching explicit prices; see the bundled
  [`configs/openrouter.toml`](harness/configs/openrouter.toml), selected with
  `--config` or `CHRYSOPOEIA_CONFIG`. Research is BYOK and selected by the
  `context` model: a Google model uses Google Search grounding; an OpenRouter
  model uses OpenRouter web search (Exa) with the same `OPENROUTER_API_KEY`;
  other models run without research, and the cycle proceeds on canonical
  snapshot evidence. Supply a provider API key only through its standard
  environment variable (e.g. `OPENROUTER_API_KEY`); never put it in config.
  Locally the ignored `.router_key` holds that credential as `NAME=value`, and
  live runs extract only the value into the environment. The checked-in default
  remains Vertex and does not auto-select another provider merely because its key
  exists.
- The trader has bounded, read-only financial-history tools: `analyze_stock_history`
  fetches daily US-equity candles; `analyze_crypto_history` fetches public OHLCV
  through CCXT (e.g. `coinbase`, `BTC/USD`, `1d`). Both return deterministic
  measurements including means/returns, volatility, SMA/EMA, RSI, stochastic
  %K/%D, and ATR as cited evidence. Stock history uses the keyless but unofficial
  Yahoo Finance chart endpoint and raw OHLCV (no split/dividend adjustment);
  crypto calls use public exchange endpoints only, with no exchange credentials
  or order methods. `analyze_polymarket_history` returns up to ten previously
  resolved windows from the current repeating Polymarket series, bounded to the
  snapshot time. These tools analyze instruments/markets; they do not add
  stock/crypto execution venues (Polymarket remains the only venue).

## Start locally

Paper plans can buy either outcome: `YES` = Yes/Up, `NO` = No/Down. The trader's
`probability` always means P(Yes/Up); the emitted NO v2 trade plan converts it to
the selected token's win probability. Capture obtains both real order books;
NO liquidity is never synthesized as `1 - YES price`. Existing v1 YES events
remain supported. This is buying outcome tokens, not short selling.

Run from `harness/`; requires Python 3.10+ and `uv`.

```sh
uv sync --all-groups --all-extras
uv run chrysopoeia validate --json
uv run adk run chrysopoeia
```

Required tests and lint/type checks are listed in `harness/AGENTS.md`.
Vertex model calls use the ambient Google project. If your default gcloud/ADC
project is not the Chrysopoeia project, set `GOOGLE_CLOUD_PROJECT` for local
model runs.
For CLI syntax, run `uv run chrysopoeia --help` or a subcommand's `--help`.
The main operator flow is `discover` → `capture` → `cycle`; `run` starts a
bounded journal-backed session. `book`, `mark`, and `settle` inspect or update
the paper journal. No cycle guarantees a trade.

Operating settings are config-only: `[session]` sets capital, loss, cycle/time,
cost, and cadence limits; `[risk]` sets exposure limits and optional existing
exposures for standalone `cycle`; `[venue]` must set
`series = "btc-updown-5m"`. Unknown/missing settings fail validation. Old
operating flags such as `--max-cycles`, `--bankroll`, `--interval-seconds`, and
discovery `--limit` are rejected. Invocation inputs (`--config`, `--journal`,
targets, input/output files, `--stop-file`, `--json`) remain flags. The default
profile allows one `run` cycle; `configs/platform.toml` allows two with a $1.50
session cost ceiling. `[session].cost_budget` limits the journal-backed `run`
session; `cycle` uses the configured operating/daily cost limits, not run's
cycle/deadline controls. Existing journals still enforce persisted
capital/target/window compatibility on resume. Use a new journal for a new
session.

BTC 5m Up/Down is the only automated venue market during development. Every
bundled profile binds `[venue].series`, and the trader's discovery tool uses the
same series, so `discover` and `run` cannot select other markets. Explicit
`capture`/`cycle` targets remain available for verification. The benchmark
`configs/btc5m.toml` sets 20 cycles and a $15 ceiling; see
[collection instructions](harness/docs/collection.md). Do not start paid
sessions without approved bounds.

`[research] enabled` (optional, default `true`) controls the pre-trader
web-research step. `configs/btc5m.toml` and `configs/platform.toml` set it to
`false`: BTC 5m evidence comes from the snapshot and 1-minute OHLCV analysis,
and grounded search dominated cost. Disabling it also removes the research
allowance from the reservation (about $0.70 to $0.28 per failed turn).

`[venue]` also accepts `forecast_offset_seconds` (0–299, default 0) and
`window_baseline` (default `false`). The BTC profiles forecast 120 seconds into
the window and attach a deterministic baseline evidence record (window open,
last price, delta, remaining time, volatility, and a normal-approximation P(Up)).
The offset is a minimum elapsed time, not an exact schedule.

To score forecasts after their markets resolve (any binary Yes/No or Up/Down
Polymarket market; Up is treated as the YES side):

```sh
uv run chrysopoeia polymarket-eval --journal /path/to/journal
# only one recurring series, e.g. the BTC 5m benchmark:
uv run chrysopoeia polymarket-eval --journal /path/to/journal \
  --series-url https://polymarket.com/event/btc-updown-5m-1792212300
```

The metric is the Brier score of the agent's first pre-close P(YES) per market,
including abstentions, against Gamma's resolved outcome; it is compared with the
CLOB YES price at the same forecast time. Lower is better (0.25 = always 50/50).
Trades and trade coverage are reported separately. Open markets are counted as
pending. No platform resources, keys, or orders are involved.

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
| Domain events / event notification | One topic carries `trade_plan_ready`, context-tagged `turn_outcome` v3, and optional Consumer `consumer_outcome` lifecycle events; subscriptions filter by `record_type` |
| Transactional outbox | Harness and Consumer journals retain events until confirmed delivery |
| At-least-once delivery + idempotent consumer | Pub/Sub retries; consumers deduplicate by stable `event_id` |
| Dead-letter queue | Consumer subscription dead-letters after ten attempts |
| CQRS read model / projections | Raw Pub/Sub-to-BigQuery archive is deployed; bounded context-history reads are optional and live verification is pending |
| Decision (outcome) logging | `turn_outcome` records context identity, decisions, review/policy results, and evidence; Consumer lifecycle outcomes are archived separately |
| Retrieval-augmented context / closed learning loop | Bounded prior outcomes can be added as untrusted evidence; automatic profile creation/revision remains future work |

This is not event sourcing: each unit's own ledger stays authoritative; analytics
copies are never used for balances, risk, or lifecycle decisions.

## Repository boundaries

`harness/` owns the producer and versioned event schema. `consumer/` validates
that schema as data and owns paper effects in a separate ledger. `platform/`
owns conditional GCP resources and consumes pinned image digests; it imports
neither package. See each folder's `AGENTS.md` for work-unit rules.
