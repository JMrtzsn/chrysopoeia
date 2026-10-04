# Harness architecture

Solid paths are implemented; dashed paths are proposed. Product scope and
acceptance remain in [`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).

```mermaid
flowchart TD
    Operator --> Loop["Harness loop<br/>limits, cadence, stop conditions"]
    Loop --> Discover["Discover and select market"]
    Discover --> Venue["Polymarket adapter<br/>public metadata and depth"]
    Venue --> Snapshot["Canonical market snapshot"]
    Snapshot --> State[("ADK cycle state")]

    State --> Trader["Trader ADK agent"]
    Trader --> ContextTool["Current tools<br/>discover_context + Google Search"]
    ContextTool -. "unverified; not citable" .-> Trader
    Trader --> Proposal["Structured proposal or abstention"]
    Proposal --> Gate["Validate identity and citations"]
    Gate -->|abstain| Outcome["Terminal outcome"]
    Gate -->|trade| Reviewer["Independent reviewer ADK agent"]
    State -->|same validated evidence| Reviewer
    Reviewer --> Policy["Deterministic policy<br/>review, edge, exposure, depth, fees"]
    Policy -->|allowed| Quote["Depth/fee quote and paper fill"]
    Policy -->|blocked| Outcome
    Quote --> Journal[("Local journal<br/>turns, positions, marks, settlement, cost")]
    Outcome --> Journal
    Loop --> Lifecycle["Mark open positions and settle resolved markets"]
    Lifecycle --> Journal
    Journal --> Loop
    Journal --> Report["Cycle/session report"]

    subgraph Planned["Proposed citable research tools"]
        Tool["Typed ADK tool"]
        Core["Research normalization and validation"]
        Integration["Provider integration"]
        Source["External source"]
        Tool --> Core --> Integration --> Source
        Source --> Integration --> Core
    end
    Trader -. "research request" .-> Tool
    Core -. "validated evidence" .-> State
    Core -. "bounded result" .-> Tool
    Tool -. "tool response" .-> Trader

    classDef planned fill:#fff,stroke:#777,stroke-dasharray:5 5;
    class Tool,Core,Integration,Source planned;
    style Planned fill:#fff,stroke:#777,stroke-dasharray:5 5;
```

## Responsibilities

- The harness loop owns market selection, cadence, and session halting;
  deterministic accounting functions own journal admission and recovery. The
  platform may launch the loop but does not drive cycles.
- ADK owns model calls and tool-call mechanics. Typed Python functions registered
  in `tools` are the in-process tool boundary.
- The trader proposes or abstains. The reviewer sees the same validated
  evidence and proposal, but not trader history. Neither has execution tools.
- Deterministic Python validates identity/citations, applies risk and cost
  policy, simulates fills, updates the journal, and decides terminal outcomes.
- Venue adapters provide normalized public market data. Market-data access never
  grants execution authority.

## Context and evidence

The trader receives a normalized snapshot and canonical evidence. Google Search
is available as unverified context but cannot currently be cited. A local
`--evidence` bundle is a snapshot-bound development/testing input, not a research
provider.

The current evidence record identifies its source URL, title, capture/retrieval
time, source kind, and snapshot. Citations must resolve to evidence IDs for the
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
| Local journal | Authoritative financial records; see [accounting](accounting.md) |
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
