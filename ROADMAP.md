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

0. **Managed deployment, Level 2 (single operator).** Selected profile
   (`docs/gcp-architecture.md`): container-first Pulumi base — versioned
   journal bucket, least-privileged runner SA, Artifact Registry repository,
   and one Cloud Run job whose every execution runs one bounded paper cycle
   (zero idle cost, no boot scripts). Offline gate passed (`pulumi preview`:
   8 resources). Pending: approved live base apply, one image build/push, and
   one bounded live execution (one journaled cycle) before any of this
   counts complete.
0a. **Unattended multi-cycle operation** (Cloud Scheduler + loops) — only
   after the Level 2 sessions above are verified, since idempotent recovery
   and turn-level resumability are not complete.
1. **Non-Gemini provider live proof.** A bounded live run against a non-Gemini
   provider (e.g. ollama with `google-adk[extensions]`) before calling that
   registry-provider boundary proven. The registry routing itself is
   live-verified for Gemini; no generic plugin framework exists.

## Deferred

- Cloud SQL, RAG Engine, Memory Bank, and managed runtime services (still gated
  on adoption triggers in `docs/gcp-architecture.md`).
- Multi-tenant or public-facing deployment (Level 3): requires explicit design
  before anything exists.
- Autonomous scheduling/scanning and managed queues, deadlines, or cancellation.
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
