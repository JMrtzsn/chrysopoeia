# Harness architecture

Solid paths are implemented; dashed paths are proposed. Product scope and
acceptance remain in [`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).

```mermaid
flowchart TD
    Operator --> Loop["Harness loop<br/>limits, cadence, stop conditions"]
    Loop --> Discover["Discover and select market"]
    Discover --> Venue["Polymarket adapter<br/>public metadata and depth"]
    Venue --> Snapshot["Canonical market snapshot"]
    Snapshot --> Research["Vertex Gemini Google Search<br/>one bounded call"]
    Research --> Evidence["Normalized grounding metadata<br/>URL + title + excerpt"]
    Evidence --> State
    Snapshot --> State[("ADK cycle state")]

    State --> Trader["Trader ADK agent"]
    Trader --> ContextTool["Read-only tools<br/>find_markets + get_market + check_trade_plan"]
    ContextTool --> Trader
    Trader --> Proposal["Structured proposal or abstention"]
    Proposal --> Gate["Validate identity and citations"]
    Gate -->|abstain| Outcome["Terminal outcome"]
    Gate -->|trade| Reviewer["Independent reviewer ADK agent"]
    State -->|same validated evidence| Reviewer
    Reviewer --> Policy["Deterministic policy<br/>review, edge, exposure, depth, fees"]
    Policy -->|allowed| Ready["trade_plan_ready<br/>verified plan, not a fill"]
    Ready --> Outbox[("Optional journal outbox")]
    Outbox -->|"confirmed direct delivery"| Publisher["Harness event sink"]
    Ready --> PaperConsumer["In-process or standalone local development consumer"]
    Publisher --> IndependentConsumer["Independent paper-only consumer<br/>separate ledger"]
    PaperConsumer --> Quote["Independent depth/fee quote and paper simulation"]
    Policy -->|blocked| Outcome
    Quote --> Journal[("Local journal<br/>turns, positions, marks, closes, settlement, cost")]
    Outcome --> Journal
    Loop --> Lifecycle["Paper lifecycle simulation while this loop runs"]
    Lifecycle --> ExitQuote["Fresh executable bid-depth quote"]
    ExitQuote --> ExitPolicy["Deterministic ROI/time trigger and full-close policy"]
    ExitPolicy -->|triggered and full depth available| Journal
    Lifecycle --> Journal
    Journal --> Loop
    Journal --> Report["Cycle/session report"]

    Ready -. "same contract" .-> ExecutionConsumer["Future GCP/other execution consumer"]
    PaperConsumer --> PaperLedger[("Local paper ledger")]
    ExecutionConsumer -. "fresh quote + bounded order" .-> LiveVenue["Venue order/fill state"]
    ExecutionConsumer -.-> LiveLedger[("Consumer-owned execution ledger")]
    Platform["Platform deployment/trigger adapter"] -.-> ExecutionConsumer

    subgraph Planned["Proposed additional research tools"]
        Tool["Typed ADK tool"]
        Core["Research normalization and validation"]
        Integration["Provider integration"]
        Source["External source"]
        Tool --> Core --> Integration --> Source
        Source --> Integration --> Core
    end
    Trader -. "future provider request" .-> Tool
    Core -. "validated evidence" .-> State
    Core -. "bounded result" .-> Tool
    Tool -. "tool response" .-> Trader

    classDef planned fill:#fff,stroke:#777,stroke-dasharray:5 5;
    class Tool,Core,Integration,Source,ExecutionConsumer,LiveVenue,LiveLedger planned;
    style Planned fill:#fff,stroke:#777,stroke-dasharray:5 5;
```

## Responsibilities

- The bounded harness loop owns market selection and proposal cadence. Its
  deterministic exit evaluation is a paper simulation and runs only while that
  loop is active; it is not a live-position supervisor.
- ADK owns model calls and tool-call mechanics. Typed Python functions registered
  in `tools` are the in-process tool boundary.
- The trader proposes or abstains. The reviewer sees the same validated
  evidence and complete entry/exit bracket, but not trader history. Neither has
  execution tools. The approved bracket is immutable after entry.
- Deterministic Python validates identity/citations and applies risk and cost
  policy. The in-process paper consumer validates the accepted event, independently
  simulates entry fills, and updates the local paper journal. Paper exit triggers
  do not call the models again.
- One bounded harness invocation produces
  `trade_plan_ready` only after reviewer approval and deterministic hard-policy
  acceptance. The event is a verified request/plan, never an order, fill, open
  position, or completed execution. Every decided turn also emits a strict
  `turn_outcome` containing the proposal rationale, bounded deterministic plan-
  check attempts, optional review, policy result, reason, and model cost; failed
  and abandoned turns do not. Plan-check rejection reasons distinguish no check,
  no passing check, and a proposal changed after its last passing check.
- The minimal event envelope contains version and type, stable `event_id`,
  creation time, market and snapshot identity, outcome, stake, maximum entry
  price, immutable ROI/time exit plan, review approval and policy/evidence
  references, and expiry/market end. Redelivery keeps the same `event_id`.
- The standalone `consume` command reads one bounded strict JSON event and
  requires an existing open local journal session. The local paper consumer and
  future execution consumers deduplicate by `event_id`,
  fetch fresh executable quotes, and own their effects, outcomes, and ledgers.
  They keep plan and achieved fill terms separate. The in-process path uses its
  supplied capture; the standalone local path fetches a fresh public quote and
  records its `quote_snapshot_id` without changing the original plan
  `snapshot_id`. Future external consumers must fetch fresh quotes and own
  separate ledgers.
- A producer-only `cycle` returns the serialized JSON event with no fill. The
  journal-backed local `run`/`cycle` path passes that event once to the in-process
  paper consumer, then returns and stores the event separately from its achieved
  fill. With `CHRYSOPOEIA_EVENT_SINK` set, journal-backed `turn_outcome` and
  accepted `trade_plan_ready` events are appended in journal order, published
  directly to loopback HTTP or Pub/Sub, and
  acknowledged only after confirmation. Pending events drain oldest-first before
  work and between run cycles. `outbox-pending` returns canonical payloads and
  `outbox-ack` records delivery; both are idempotent by `event_id`. The outbox is
  delivery state, not a financial ledger. The selected optional producer
  transport is selected by the sink with this journal-backed at-least-once
  outbox. Unset performs no publishing, Pub/Sub import, or network call.
- Outcomes are always validated and journaled before turn finalization. One topic
  carries all outbox event types with `record_type` and `schema_version` message
  attributes; independent subscriptions filter the types they consume.
- No always-on harness or manager process is required. CLI or future request
  adapters invoke the same core. The deployed paper consumer is independently
  implemented in `consumer/`; live order mechanisms remain deferred. Any live
  consumer/venue exit monitoring and protection guarantees
  must be specified before live activation.
- In event-driven terms: the journal outbox is a transactional outbox, delivery
  is at-least-once, and consumers are idempotent by `event_id`. BigQuery read
  models remain future work.
- Venue adapters provide normalized public market data. Market-data access never
  grants execution authority.

## Context and evidence

Two-sided paper proposals carry `outcome=YES|NO`, while their probability remains
P(YES/Up). Production captures load both token books. Python selects the actual
side for edge, depth, fills, marks, exits and settlement. NO plans and outcomes
use the v2 contracts; existing v1 YES records remain readable. In a v2
`trade_plan_ready`, probability is the chosen token's win probability. The
independent consumer checks token/outcome pairing against public venue metadata.

The model provider is BYOK and applies to every role through the selected ADK
boundary (`adk-gemini` for Vertex, `adk-registry` for other providers). The
context/research role selects a research provider from its configured model: a
Gemini model uses the bounded Google Search grounding tool, an OpenRouter model
uses the OpenRouter web search plugin (Exa), and any other model runs without
research. Provider output is normalized into the same snapshot-bound external
evidence records, bounded by result count and URL/title/excerpt limits; a failed
or uncitable research step leaves canonical snapshot evidence available. The
platform independently owns deployment resource placement; its Cloud Run region
does not select the model endpoint.

The trader may discover a bounded candidate list, capture up to five canonical
snapshots, and dry-run up to five candidate plans through the same deterministic
checker used by the final gate. Discovery scans at most 75 markets ending within
30 days in Gamma's descending 24-hour volume order and runs at most once per cycle. The
trader can also call bounded financial-history tools for named US stock symbols
and CCXT crypto pairs. These fetch public OHLCV and compute deterministic
statistics (returns, means, volatility, moving averages, RSI, stochastic %K/%D,
and ATR); the results are snapshot-bound external evidence, not forecasts or
trade instructions. Stock history uses Yahoo Finance's public chart endpoint
(keyless, unofficial, raw OHLCV without split/dividend adjustment); crypto history
uses CCXT's public OHLCV interface without exchange credentials or order methods.
`analyze_polymarket_history` adds up to ten resolved outcomes from the current
recurring series, filtered to settlements available at snapshot capture time. Binary
markets with Yes/No or Up/Down outcomes are supported; the first outcome is the
YES side the harness can buy. The local `polymarket-eval` command scores each
market's first pre-close P(YES), trade or abstain, with Brier against the
Gamma-resolved outcome and the same-time CLOB YES price. The reviewer remains tool-less. After snapshot capture,
deterministic orchestration
runs the context agent once. It keeps at most eight unique public HTTPS grounding
chunks, maps bounded support text into excerpts, discards free-text answers, and
continues with canonical evidence if research fails or returns no grounding. A local
`--evidence` bundle is a snapshot-bound development/testing input, not a research
provider.

The current evidence record identifies its source URL, title, optional bounded
excerpt, capture/retrieval time, source kind, and snapshot. Citations must resolve to evidence IDs for the
current snapshot; raw URLs and unknown IDs do not resolve. The reviewer gets the
same validated evidence and proposal, without trader history.

Before provider output becomes citable, deterministic normalization must bound
and validate source identity, schema, freshness, size, and provenance. External
content is untrusted data, never instructions. Research tools do not grant
authorization.

| State | Authority |
| --- | --- |
| Agent instructions | Guidance only; cannot authorize or enforce policy |
| ADK session state | Working context for the current cycle |
| Paper journal | Authoritative paper records; see [accounting](accounting.md) |
| `trade_plan_ready` event | Verified plan/request; never evidence of an order, fill, or position |
| Consumer ledger | Owned by that consumer; deduplicates redelivery and records its own effects/outcomes |
| Live venue state | Authority for actual accepted orders and fills; the execution consumer reconciles it |
| External content | Untrusted; citable only after deterministic validation |

RAG, long-term memory, and context catalogs are deferred. They cannot become
authoritative for balances, fills, risk, permissions, or lifecycle decisions.

## Keeping this map current

- Update with changes to major components, trust boundaries, state flow, tool
  surfaces, or execution authority; keep implemented and proposed paths distinct.
- Check the flow against [`../chrysopoeia/loop.py`](../chrysopoeia/loop.py) and
  neighboring modules (`agent.py`, `paper_cycle.py`, `trading.py`,
  `polymarket.py`, and `accounting.py`).
- Update `../ROADMAP.md` where work status/order changes. This map is not a
  second product specification.
