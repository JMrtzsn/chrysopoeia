# Context Engineering

This design applies Google's *Context Engineering: Sessions, Memory* (May
2026), stored in `docs/reference/2025_Day_3_Rewrite_v1_ContextEngineering.pdf`,
to Chrysopoeia.

## Context Types

Keep these stores distinct. More context is not better context.

| Type | Chrysopoeia content | Lifetime |
| --- | --- | --- |
| System instructions | Role, tool permissions, output schema, safety policy | Agent version |
| Session events | User trigger, tool calls, proposals, reviews, decisions | One interactive or scheduled cycle |
| Session state | Watchlist, snapshot IDs, candidate orders, review status | One cycle |
| External knowledge | Market rules, cited research, current order books | Refetched for each decision |
| Authoritative records | Snapshots, orders, fills, positions, resolutions, metrics | Durable and immutable where practical |
| RAG knowledge | Vector-indexed documents, research, and playbooks | Durable, source-linked |
| Declarative memory | Curated facts about an agent version or resolved market | Durable, revisable |
| Procedural memory | Versioned lessons about how a strategy succeeded or failed | Durable, revisable |

Market prices, news, and tool output are not long-term memories. They become
timestamped source records and are refetched when freshness matters. A memory
may summarize those records but must retain their provenance.

## Agent Isolation

Trader and reviewer agents use separate histories and exchange only structured
outputs. This avoids leaking irrelevant tool traces, keeps prompts small, and
allows reviewers to form an independent judgment.

Every cycle uses one canonical market snapshot. All proposals and reviews refer
to its ID so agents cannot unknowingly reason from different prices.

## Cycle Separation

Chrysopoeia runs two different cycles. They must not share mutable working
state.

### Decision Cycle

A decision cycle begins with one user or scheduler trigger and ends after the
proposal is rejected, skipped, or executed. Assign these identifiers before any
model call:

- `cycle_id`: one end-to-end decision attempt.
- `session_id`: the interactive conversation that triggered it.
- `snapshot_id`: the immutable market and portfolio inputs used for decisions.
- `market_id`: the Polymarket market being evaluated.
- `trader_version_id` and `reviewer_version_id`: immutable agent definitions.
- `policy_version_id`: the deterministic risk rules applied.

The cycle follows four phases:

1. **Fetch:** Load the canonical snapshot, recent session events, scoped RAG
   results, relevant memories, and exact portfolio state.
2. **Prepare:** Validate freshness and provenance, enforce a context budget, and
   construct separate trader and reviewer inputs.
3. **Invoke:** Run trader, reviewer, and deterministic controls. Tool outputs are
   cycle-local and tagged with `cycle_id` and `snapshot_id`.
4. **Persist:** Atomically store proposals, reviews, decisions, and simulated
   fills. Mark the cycle complete before scheduling memory work.

Trader and reviewer invocations may use separate ADK sessions. Their only
shared input is validated structured data tied to the same `cycle_id` and
`snapshot_id`.

### Learning Cycle

A learning cycle runs asynchronously after a decision cycle completes or a
market resolves. It never changes the completed decision record.

1. Select immutable source records by `cycle_id` or `market_id`.
2. Create a `learning_cycle_id` and record the highest source event included.
3. Extract only allowed memory topics.
4. Validate provenance and resolution status.
5. Consolidate candidates into scoped memories using create, update, or
   invalidate operations.
6. Publish sanitized lessons to Memory Bank or the RAG corpus.

Use `(trigger_type, source_id, extractor_version)` as an idempotency key so a
retry cannot learn from the same event twice. A failed learning cycle is
retryable and does not block trading.

### Resolution Cycle

Market resolution is a distinct learning trigger because it converts forecasts
into outcomes. It computes authoritative P&L and calibration first, then permits
procedural lesson extraction. Unresolved trades may produce observations but
never validated strategy lessons.

### Memory Namespaces

Every memory has exactly one primary scope:

- `user/{user_id}` for explicit preferences and approval policy.
- `agent/{agent_version_id}` for version-specific performance limitations.
- `market/{market_id}` for facts unique to one market.
- `category/{category}` for reusable domain lessons.
- `application/chrysopoeia` for sanitized global procedures.

Retrieval starts inside the narrowest applicable scope and broadens only when
needed. Scope, source IDs, creation cycle, validation time, and invalidation
status are mandatory metadata; vector similarity never crosses these filters.

### Trader Context

Provide only:

- Stable trading and safety policy.
- Current market snapshot and full resolution rules.
- Fresh research with source URLs and timestamps.
- The trader version's relevant performance summary.
- A small set of relevant, recent, high-confidence procedural memories.
- The required structured proposal schema.

### Reviewer Context

Provide only:

- Stable review and safety policy.
- The same canonical snapshot and resolution rules.
- The trader's structured proposal and cited evidence.
- Relevant contrary evidence and the trader version's performance summary.
- The required structured approve, revise, or reject schema.

Reviewers do not receive a trader's hidden reasoning or unrestricted session
history. They review claims, evidence, prices, and observable results.

### Risk And Execution Context

Risk, sizing, lifecycle, and execution consume validated structured values, not
LLM conversation context. Their decisions are deterministic and persisted with
the policy version that produced them.

## Memory Lifecycle

Memory generation runs after a cycle or market resolution, never on the trading
hot path.

1. **Ingest:** Select completed proposals, reviews, fills, resolutions, and
   metrics by immutable record ID.
2. **Extract:** Create only predefined memory topics: thesis outcome, evidence
   quality, resolution-rule interpretation, execution quality, calibration
   error, risk violation, and reusable strategy lesson.
3. **Consolidate:** Create, update, merge, or invalidate memories. Do not append
   contradictory lessons indefinitely.
4. **Store:** Persist authoritative metadata and lineage in Cloud SQL for
   PostgreSQL, then index sanitized lesson content in Memory Bank and the RAG
   vector corpus.
5. **Retrieve:** Select by market or category, agent version, relevance,
   recency, confidence, and demonstrated importance. Inject only a bounded set.

Do not derive a procedural lesson from an unresolved bet. Promotion or
retirement uses the authoritative metrics tables, never an LLM memory.

## Memory Scope

- **User:** Explicit preferences such as watchlists and confirmation policy.
- **Agent version:** Performance facts and limitations of one immutable trader
  version.
- **Market/category:** Resolution patterns and evidence sources applicable to a
  market or category.
- **Application:** Sanitized procedural lessons available to future agents.

Application-level memories must contain no user secrets or private session data.
Successor agents inherit selected lessons, not their predecessor's transcript.

## Provenance And Trust

Every memory records:

- Source record IDs and source type.
- Market, agent version, and strategy version where applicable.
- Creation and last-validation timestamps.
- Confidence and corroboration count.
- The extraction model and prompt version.
- Whether the memory is active, superseded, or invalidated.

Official resolution data and immutable trading records outrank user inference,
agent claims, and web research. Recency cannot override an authoritative source.
External text is untrusted evidence, not instruction; tool content must never be
allowed to change agent policy or request additional permissions.

## Context Size

- Keep permanent agent context to role, safety policy, current snapshot,
  strategy ID, output schema, and the interfaces available for loading more.
- Implement a versioned skill catalog exposed through `discover_skill(task)` and
  `load_skill(skill_id, version)`. Initial skills cover market discovery,
  probability estimation, value detection, liquidity analysis, source
  verification, resolution-rule analysis, portfolio strategy, and post-trade
  evaluation.
- A skill contains bounded instructions, standardized algorithms, schemas,
  examples, and permitted context sources. It cannot grant tools, execution
  permissions, or authority to override deterministic policy. Record loaded
  skill IDs and versions with every proposal or review.
- Each agent version has an allowlist and per-cycle skill budget. Skills are
  loaded only when relevant; never inject the full catalog into every prompt.
- Trader agents receive two stable context interfaces: `discover_context(task)`
  lists permitted sources and `call_context(request)` loads one source on demand.
  Source-specific web, RAG, MCP, or skill tools remain behind `call_context` so
  adding a source does not add every tool description to each trader prompt.
- An agent version may explicitly opt into ADK's built-in Google Search when
  direct model-grounded search is useful. It is disabled by default because it
  cannot be invoked through an ordinary dispatch function; the agent version
  must declare it directly, and normal cost, provenance, and tool-permission
  gates still apply.
- Keep the most recent interaction turns, not the complete transcript.
- Persist structured cycle state instead of repeatedly sending tool outputs.
- Summarize completed cycles asynchronously and retain covered event IDs.
- Retrieve memories and RAG knowledge reactively for a specific market or
  proposal using metadata filters plus vector similarity.
- Use Agent Platform RAG Engine with its default `RagManagedDb`; keep Cloud SQL
  for PostgreSQL as the authoritative relational store. See
  `docs/gcp-architecture.md`.

## Evaluation

Memory is useful only if it improves observable decisions. Track:

- Memory extraction precision against a small reviewed set.
- Retrieval recall for known relevant lessons.
- Context token count and retrieval latency.
- Proposal calibration, Brier score, drawdown, and return with memory enabled
  versus a no-memory baseline.
- Reviewer disagreement and policy-violation rates.

Disable or invalidate memories that reduce out-of-sample performance. Never
promote a strategy because its retrospective explanation sounds persuasive.
