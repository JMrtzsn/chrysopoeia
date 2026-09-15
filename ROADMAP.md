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

## Next

1. **Bounded market discovery and opportunity gate — In progress.** The
   explicitly operator-triggered, public read-only metadata sample of up to 75
   markets and capture handoff are implemented locally without a whole-universe
   ranking, scheduler, model calls, or persistence. Keep this item here until
   offline gates and the mandatory bounded live discovery/capture check pass and
   acceptance evidence is recorded.
2. **Second concrete adapter proof.** Only on an actual need, add either another
   model adapter with explicit pricing or another venue adapter. Stable core
   contracts are sufficient; do not add a generic plugin framework.
   Claude-on-Vertex is a candidate, not committed scope.
3. **Multi-cycle portfolio and paper accounting design.** Define cross-cycle
   positions, bankroll, realized and unrealized P&L, maximum-loss enforcement,
   and market-resolution needs. This design determines persistence requirements
   rather than assuming them in advance.
4. **Durable local session, turn, and accounting records.** Implement
   immediately when milestone 3 requires cross-process state, using atomic
   records with inspection and resume support. This is conditional on the
   accounting design, not the current priority.
5. **Idempotent turn admission and recovery.** After durable records exist, and
   only if repeated or unattended cycles are needed, prevent duplicate fills or
   records and define terminal versus resumable states and recovery behavior.

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
