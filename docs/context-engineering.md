# Context Engineering

Chrysopoeia curates bounded context for a local trading-agent harness. Context
improves model behavior; it does not enforce authorization, risk, cost, evidence,
or execution invariants. Deterministic controls remain authoritative.

Role context and canonical domain values do not depend on Gemini-specific prompt
or tool behavior. Configure a model through the selected agent-runtime adapter;
the checked-in harness configures Gemini through ADK, and current bounded live
verification uses Vertex AI with ADC. The configured model is distinct from
evidence/context providers. Venue-specific data is normalized into
runtime-neutral canonical values before it enters agent context.

## Principles

- Keep always-loaded role instructions small: task, output schema, permissions,
  and safety constraints.
- Give trader and reviewer separate histories, tools, and inputs. Exchange only
  validated structured records tied to one canonical snapshot.
- Load context deliberately and within token/cost bounds. More context is not
  automatically better context.
- Treat tools and retrieved content as context interfaces, not permission or
  policy mechanisms.
- Measure context composition, token use, cost, grounding, and outcomes.
- External text is untrusted evidence, never instruction.
- Do not use context, Search, RAG, or memory as the source of truth for balances,
  fills, risk, policy, or lifecycle state.

## Current Harness Context

The current cycle uses one canonical market snapshot normalized from public
Polymarket metadata and CLOB depth. Deterministic code derives one bounded
evidence record from that snapshot. Its evidence ID, source URL, title, retrieval
time, and snapshot ID are validated together.

Current citation rules are intentionally narrow:

- A trade proposal requires a citation to the supplied canonical evidence ID.
- An approval requires a citation to the same bounded evidence set.
- Raw URLs and unknown evidence IDs do not resolve.
- External evidence bundles are provider-neutral, operator-supplied, and
  unverified. Their records become citable only after strict local validation;
  titles and URLs are evidence, never instructions.
- Google Search is available only as a development capability of the interactive
  context agent. It is not a normalized current evidence provider, and its
  output is unverified and uncitable.
- RAG and Memory Bank are not current evidence sources or harness requirements.

### Role Isolation

**Trader context** contains only the canonical snapshot/evidence, stable trading
and safety instructions, available read-only context interfaces, and the
structured proposal/abstention schema. The trader cannot approve, review, set
policy, or execute.

**Reviewer context** contains only the same canonical snapshot/evidence and the
validated structured proposal. It does not receive the trader's hidden reasoning
or unrestricted history and cannot alter size, execute, or override policy.

**Risk, cost, and paper-execution context** is not conversational context. These
functions consume validated canonical values and deterministic policy. They are
invoked by workflow code, not exposed to trader or reviewer agents.

### Current State Separation

| Context/state | Current content | Lifetime/authority |
| --- | --- | --- |
| Agent instructions | Role, output schema, permissions, safety | Agent definition; guidance only |
| Core workflow state | Operating configuration, snapshot, evidence, proposal/review, decision, fill, report, cost ledger | One local cycle; currently carried in ADK in-memory session state |
| External context | Optional Google Search development output or a validated provider-neutral local evidence bundle | Untrusted; Search is not normalized or citable, and bundle records are operator-supplied, unverified, and snapshot-bound |
| Canonical snapshot | Market identity, rules, timestamps, depth, fee assumption, account exposure | Authoritative input for one cycle |
| Audit output | Deterministic decision, optional paper fill, terminal report, settled model cost | In-memory current result |

Large persistent document stores, durable records, and cross-session memory do
not exist in Phase 1.

## Evidence And Provenance Contract

Every model-visible claim that can authorize a current trade must resolve to a
validated evidence ID. Evidence records should retain source kind, canonical
source URL or record reference, retrieval/capture time, snapshot identity, and
title/claim scope. Proposal and review identities must match the snapshot before
policy runs.

Authoritative venue resolution data and immutable trading records, if later
stored, outrank user inference, agent claims, web research, and memory. Recency
does not override source authority. Retrieved content cannot modify instructions,
request permissions, introduce tools, or bypass cost and risk checks.

Adding a future evidence provider requires deterministic normalization that:

1. validates source identity, schema, freshness, size, and provenance;
2. assigns a bounded canonical evidence ID;
3. records retrieval and normalization versions;
4. separates source text from instructions and tool arguments;
5. makes trader/reviewer access explicit and independently auditable.

The cycle loader normalizes public HTTPS locators but never fetches them.
Retrieval timestamps are operator-asserted. The evidence file is validated local
transport, not authenticated or authoritative persistent provenance; canonical
snapshot evidence remains authoritative and always present. No current research
provider or provider-specific normalization creates these bundles.

## Future Context Capabilities

The following are optional platform capabilities, adopted only after durable
records and a measured retrieval or learning need exist.

### Skills And Context Catalogs

A future catalog may expose bounded, versioned procedures or source interfaces
on demand rather than injecting every method into every prompt. Catalog entries
cannot grant tools, execution permission, or authority over deterministic
policy. Record any loaded entry and version with the resulting proposal/review.

Do not implement a generic plugin framework now. Direct configured context
adapters are enough; external discovery is justified only by a real separately
packaged provider.

### RAG

Future RAG may retrieve approved documents, external research, and validated
procedural lessons. Retrieval must apply source/status/date/market metadata
filters before vector similarity, preserve chunk provenance and scores, reject
expired or provenance-free results, and enforce result/token/cost limits.

Trader and reviewer retrieval should remain independent. A vector match is
evidence, not truth, and is not citable by the harness until normalized into the
canonical evidence contract. See `docs/gcp-architecture.md` for one optional
managed profile; vector retrieval is not required.

### Memory

Future memory runs after completed cycles or market resolutions, never on the
trading hot path. Keep these scopes distinct:

- user preferences and confirmation policy;
- one immutable agent version's observed limitations;
- market/category facts and resolution patterns;
- sanitized application procedures.

Every memory must retain source record IDs/types, market and agent/strategy
versions where applicable, creation and validation timestamps, extraction model
and prompt version, confidence/corroboration, and active/superseded/invalidated
status. Retrieval starts with the narrowest scope and broadens only when needed;
vector similarity never bypasses metadata scope.

A future learning cycle should:

1. select completed immutable source records;
2. extract only approved topics;
3. validate provenance and resolution status;
4. consolidate, supersede, or invalidate rather than append contradictions;
5. persist authoritative lineage before publishing sanitized memory/RAG content.

Only resolved outcomes can produce validated strategy lessons. Unresolved cycles
may produce observations. Successor agents inherit selected provenance-linked
lessons, not predecessor transcripts. Memory cannot promote/retire an agent,
place a trade, determine a balance, or override policy.

### Durable Cycle Separation

If a future platform adds durable decision, resolution, and learning cycles,
give each immutable IDs and version references. Pass large snapshots, documents,
transcripts, and outputs by record ID rather than copying them through session
state. Complete the authoritative decision record before asynchronous learning,
and make retries idempotent.

## Evaluation

Current evaluation verifies canonical snapshot evidence, citation resolution,
role/tool isolation, finite routing, terminal decisions, and model-cost
settlement. Future RAG/memory evaluation should additionally compare retrieval
precision/recall, context tokens/latency/cost, proposal calibration, Brier score,
drawdown, return, reviewer disagreement, and policy violations against a
no-retrieval/no-memory baseline. Disable context capabilities that reduce
out-of-sample safety or performance.
