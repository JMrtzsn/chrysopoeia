# Roadmap

`.agents-cli-spec.md` is authoritative for product scope and acceptance. This
roadmap only orders approved work and cannot expand that scope. Development and
live-verification gates remain in `docs/development-lifecycle.md`.

## Complete

- [x] Runtime-neutral core contracts with ADK at the runtime edge
  (`chrysopoeia/paper_cycle.py`, `chrysopoeia/trading.py`,
  `chrysopoeia/agent.py`; spec: Harness Definition And Ownership).
- [x] Validated configuration and offline `inspect`/`validate` CLI
  (`chrysopoeia/configuration.py`, `chrysopoeia/cli.py`; spec: Adapter And
  Configuration Model).
- [x] Public Polymarket capture with depth and fee provenance
  (`chrysopoeia/polymarket.py`; spec: Core Capability Boundaries).
- [x] Snapshot-driven paper cycle with abstention, review, risk, and fill routes
  (`chrysopoeia/paper_cycle.py`, `chrysopoeia/trading.py`; spec: Workflow).
- [x] Provider-neutral local `evidence_bundle` validation and cycle support
  (`chrysopoeia/context.py`, `chrysopoeia/cycle_runner.py`; spec: Core
  Capability Boundaries).
- [x] Deterministic cost gate, offline pre-commit gate, and mandatory bounded
  live-verification policy (`chrysopoeia/cost.py`, `.githooks/pre-commit`,
  `docs/development-lifecycle.md`; spec: Phase 1 Acceptance Criteria).
- [x] Agents CLI and A2A prototype surface (`agents-cli-manifest.yaml`,
  `chrysopoeia/fast_api_app.py`; spec: Adapter And Configuration Model).
- [x] Bounded public market discovery and capture handoff over a deterministic
  75-market sample (`chrysopoeia/polymarket.py`, `chrysopoeia/cli.py`; spec:
  Core Capability Boundaries). Live-verified 2026-09-15; see Recorded Live
  Verification in `docs/development-lifecycle.md`.
- [x] Durable local session, turn, and accounting records
  (`chrysopoeia/accounting.py`, `chrysopoeia/cli.py`; contract:
  `docs/portfolio-accounting.md`). The `book` inspection CLI and
  `cycle --journal` admission, exposure, fill recording, halt checking, and
  `book_after` reporting are live-verified 2026-09-15, including the full
  abstain→review→reject→fill route and same-market preemption; see Recorded
  Live Verification in `docs/development-lifecycle.md`.
- [x] Idempotent turn admission (`chrysopoeia/accounting.py`): deterministic
  `turn-<sha24>` IDs, no-op repeats, and pre-model same-market preemption,
  also covered by the 2026-09-15 live verification.
- [x] Venue-derived resolution and paper settlement
  (`chrysopoeia/polymarket.py`, `chrysopoeia/cli.py`: `settle`): read-only
  Gamma resolution capture normalized to canonical `resolved_yes|resolved_no`,
  deterministic settlement against open positions, cumulative-loss halt on
  settlement, refusal of unresolved or ambiguous markets. Live-verified
  2026-09-15 against a real resolved market; see Recorded Live Verification in
  `docs/development-lifecycle.md`.
- [x] Venue price marking (`chrysopoeia/cli.py`: `mark`): re-capture of open
  positions feeds journal marks so unrealized P&L reflects live venue data.
  Live-verified 2026-09-15; see Recorded Live Verification in
  `docs/development-lifecycle.md`.

## Next

1. **Second concrete adapter proof.** Implemented: a pluggable models adapter
   (`[models] adapter`: `adk-gemini` | `adk-registry`) routing model names
   through the ADK `LLMRegistry` (ollama/claude/gpt/openai prefixes) with
   optional per-model `[cost.models]` pricing enforced in the cost gate
   (`chrysopoeia/configuration.py`, `chrysopoeia/cost.py`,
   `chrysopoeia/cycle_runner.py`). Gemini-registry routing is live-verified
   2026-09-15; a bounded live run against a non-Gemini provider (e.g. ollama
   with `google-adk[extensions]`) remains before calling that provider
   boundary proven. No generic plugin framework was added.
2. **Multi-cycle portfolio and paper accounting design.** Design written in
   `docs/portfolio-accounting.md` (cross-cycle positions, book/ledger, marks,
   realized and unrealized P&L, cumulative maximum-loss halt, venue-derived
   resolution, and the derived journal-based persistence requirement). It
   awaits operator agreement; implementation is milestones 3–4.
3. **Durable local session, turn, and accounting records.** Implemented:
   `chrysopoeia/accounting.py` journal/replay/book, the `book` inspection CLI,
   and `cycle --journal` admission, exposure, fill recording, halt checking,
   and `book_after` reporting (`docs/portfolio-accounting.md` is the contract).
   Live-verified 2026-09-15; see Recorded Live Verification in
   `docs/development-lifecycle.md`. The configured default model alias
   `gemini-flash-latest` remains Gemini-API-only; a Vertex run needs a
   Vertex-native alias in the config — pending operator decision.
4. **Idempotent turn admission.** Largely implemented with milestone 3
   (deterministic turn IDs `turn-<sha24>`, no-op repeats, pre-model same-market
   preemption). Full turn-level recovery of interrupted cycles remains when
   unattended operation is actually needed.

## Deferred

- Autonomous scheduling/scanning and managed queues, deadlines, or cancellation.
- Cloud SQL, managed deployment, and production observability.
- RAG/memory plus lifecycle and version management.
- Authenticated execution; it requires confirmation, least-privilege IAM, hard
  limits, a kill switch, idempotency, and reconciliation.
- A meta-harness/control plane, unless multiple independent harnesses exist.

See [Agent Graphs](docs/agent-graphs.md) for future graph prerequisites and
[Optional Google Cloud Deployment Profile](docs/gcp-architecture.md) for
managed-platform boundaries.

## Updating This Roadmap

- Start a milestone only with explicit user approval and an agreed contract.
- Every externally observable feature addition or change requires both offline
  checks and bounded live verification against the real changed boundary, as
  defined in `docs/development-lifecycle.md`. A failed or unavailable live check
  leaves the feature incomplete and blocks any commit recommendation.
- Mark work **Complete** only after acceptance evidence exists and the change is
  committed.
- Do not add speculative abstractions or plugin systems.
