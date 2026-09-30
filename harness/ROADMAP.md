# Harness Roadmap

`../.agents-cli-spec.md` is authoritative for product scope and acceptance. This
roadmap only orders approved harness work and cannot expand that scope.
Development and live-verification gates remain in
`../docs/development-lifecycle.md`. Paths below are relative to `harness/` unless
otherwise stated.

The only coupling between the harness and platform flows is a released harness
artifact (wheel/image version). Neither roadmap depends on the other's tasks.

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
  `../docs/development-lifecycle.md`; spec: Phase 1 Acceptance Criteria).
- [x] Agents CLI and A2A prototype surface (`agents-cli-manifest.yaml`,
  `chrysopoeia/fast_api_app.py`; spec: Adapter And Configuration Model).
- [x] Bounded public market discovery and capture handoff over a deterministic
  75-market sample (`chrysopoeia/polymarket.py`, `chrysopoeia/cli.py`; spec:
  Core Capability Boundaries). Live-verified 2026-09-15; see Recorded Live
  Verification in `../docs/development-lifecycle.md`.
- [x] Durable local session, turn, and accounting records
  (`chrysopoeia/accounting.py`, `chrysopoeia/cli.py`; contract:
  `../docs/portfolio-accounting.md`). The `book` inspection CLI and
  `cycle --journal` admission, exposure, fill recording, halt checking, and
  `book_after` reporting are live-verified 2026-09-15, including the full
  abstain→review→reject→fill route and same-market preemption; see Recorded
  Live Verification in `../docs/development-lifecycle.md`.
- [x] Idempotent turn admission (`chrysopoeia/accounting.py`): deterministic
  `turn-<sha24>` IDs, no-op repeats, and pre-model same-market preemption,
  also covered by the 2026-09-15 live verification.
- [x] Venue-derived resolution and paper settlement
  (`chrysopoeia/polymarket.py`, `chrysopoeia/cli.py`: `settle`): read-only
  Gamma resolution capture normalized to canonical `resolved_yes|resolved_no`,
  deterministic settlement against open positions, cumulative-loss halt on
  settlement, refusal of unresolved or ambiguous markets. Live-verified
  2026-09-15 against a real resolved market; see Recorded Live Verification in
  `../docs/development-lifecycle.md`.
- [x] Venue price marking (`chrysopoeia/cli.py`: `mark`): re-capture of open
  positions feeds journal marks so unrealized P&L reflects live venue data.
  Live-verified 2026-09-15; see Recorded Live Verification in
  `../docs/development-lifecycle.md`.
- [x] Non-Gemini provider live proof: one bounded paper cycle over OpenRouter
  (`openrouter/openai/gpt-4o`) through `adk-registry`/LiteLlm, authenticated
  with a provider-standard env-var key (`OPENROUTER_API_KEY`) and priced
  per-model under `[cost.models]`. The auth policy now permits env-var keys
  for providers without ambient authentication. Live-verified 2026-09-27; see
  Recorded Live Verification in `../docs/development-lifecycle.md`.
- [x] Turn-level recovery (`chrysopoeia/accounting.py`, `chrysopoeia/cli.py`):
  every admitted turn ends in exactly one `turn_finished`; fills link to their
  turn; open turns are resolved `filled` or `abandoned` before admission
  without model calls; finished-turn repeats are no-ops; appends fsync.
  Live-verified 2026-09-30; see Recorded Live Verification in
  `../docs/development-lifecycle.md`.

## Next

1. **Bounded autonomous trading loop.** Add a paper-only harness CLI entrypoint
   that repeats discover → capture → cycle → mark → settle under hard maximum
   cycles, operator-set capital and trading window, target win rate, cost budget,
   loss halt, and kill switch/stop file or signal bounds. Trading logic, market
   selection, cadence, recovery, and halting remain inside the harness. Stop at
   the window deadline and report achieved settled-trade win rate versus target
   plus P&L net of costs; the target never weakens risk limits or forces trades.
2. **Research tools.** Add bounded information-search, financial-data, and
   company-data inputs that produce validated, normalized, provenance-carrying
   evidence the trader and reviewer can cite. These tools carry no execution
   authority.
3. **Later venue adapters.** Add each venue beyond the current Polymarket adapter
   as its own milestone with canonical normalization and contract tests; research
   data tools are not venues.

## Deferred

- RAG/memory plus lifecycle and version management.
- Authenticated execution is the eventual goal but remains prohibited; it
  requires confirmation, least-privilege IAM, hard limits, a kill switch,
  idempotency, and reconciliation.
- A meta-harness/control plane, unless multiple independent harnesses exist.

See [Agent Graphs](../docs/agent-graphs.md) for future graph prerequisites.

## Updating This Roadmap

- Change only work owned by `harness/`.
- Start a milestone only with explicit user approval and an agreed contract.
- Every externally observable feature addition or change requires both offline
  checks and bounded live verification against the real changed boundary, as
  defined in `../docs/development-lifecycle.md`. A failed or unavailable live check
  leaves the feature incomplete and blocks any commit recommendation.
- Mark work **Complete** only after acceptance evidence exists and the change is
  committed.
- Do not add speculative abstractions or plugin systems.
