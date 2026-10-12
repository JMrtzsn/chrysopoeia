# Harness roadmap

`.agents-cli-spec.md` defines product scope and acceptance. This roadmap orders
approved harness work only. Paths are relative to `harness/` unless noted.
Verification policy and harness evidence are in `docs/verification.md`.
The platform consumes a released harness artifact. Event adapters and consumers
are coordinated harness/platform work recorded in both roadmaps.

Operator-approved cross-work-unit direction (2026-10-06): use the supported
Vertex `gemini-3.5-flash` model and its non-global pricing, with the `us` model
endpoint configured separately from the platform compute region.

## Complete

- Runtime-neutral paper-cycle contracts with ADK at the runtime edge; validated
  configuration and local `inspect`/`validate` commands.
- Public Polymarket discovery and capture, canonical snapshot evidence, and a
  snapshot-driven cycle with abstention, review, risk checks, and depth/fee-aware
  paper fills.
- Deterministic model-cost gates and offline evaluation/pre-commit checks.
- Durable local journal for sessions, turns, fills, marks, settlement, model
  costs, and book inspection. Admission is idempotent; interrupted turns recover
  without repeating model work. Venue resolution and price marks are
  read-only/public. Live verified 2026-09-15 and 2026-09-30.
- Bounded `chrysopoeia run`: harness-selected markets, persisted session limits,
  max-cycle/cost/loss/deadline/stop controls, recovery, and target win-rate/net
  P&L report. Live verified 2026-09-30.
- Reviewer-approved entry/exit plans and the in-process paper bracket simulator
  (`d944289`): fresh executable bids, full closes, journal recovery, and
  resolution handling. Live verified 2026-10-05.
- The `trade_plan_ready` event producer and idempotent in-process paper consumer
  (`690d8f9`): `cycle` returns the reviewed, policy-accepted event; `run`
  consumes it locally while preserving bracket behavior.
- Standalone local paper consumer (`31d2642`): `consume` reads an existing event,
  obtains a fresh public quote, rechecks the plan, and writes the local journal
  idempotently. Live verified 2026-10-07.
- Optional journal-backed producer outbox and the former Platform Pub/Sub publisher
  (`3d942a5`): accepted plans are durably pending until publish confirmation and
  CLI acknowledgement. Bounded live verification passed 2026-10-08; no subscriber
  or consumer is included. Evidence is in `docs/verification.md`.
- Shared `trade_plan_ready` v1 schema in `../contracts/` (`3b495d1`), consumed
  as data by the independent paper consumer in `../consumer/`. Harness work for
  event consumption ends at the schema, event, and outbox.
- The bounded trader-tool loop (`292b762`): deterministic market discovery,
  snapshot retrieval, and trade-plan checks with fail-closed limits. Live
  verified with the checked-in Vertex model 2026-10-06.
- One bounded live paper cycle through a non-Gemini provider (OpenRouter via ADK
  registry). Live verified 2026-09-27.
- Bounded trader-tool loop through OpenRouter/LiteLLM using
  `openai/gpt-4.1-mini` at the explicitly recorded rates. Live verified
  2026-10-08; evidence is in `docs/verification.md`.

The recorded commands and evidence for harness milestones are in
`docs/verification.md`.

## Next

1. **Outcome events:** versioned schemas for abstained, reviewer-rejected,
   policy-rejected, and plan-ready turns, published through the same outbox.
2. **Citable research tools:** bounded providers normalized into provenance-
   carrying evidence shared by trader and reviewer; no execution authority.
3. **Trading-history context source:** read-only BigQuery-backed evidence tool,
   after outcome data exists; see the spec's approved future item.
4. **Additional venues and NO-side positions:** separate milestones after the
   Polymarket YES-only live path in `../consumer/ROADMAP.md` is verified. Any
   event-contract change is a new schema version.
5. **Future CCXT crypto-trading integration:** after the Polymarket YES-only
   live path is verified, plan this milestone and decide whether to select CCXT,
   which exchange to support, and whether to cover spot or derivatives. CCXT is
   not selected or installed by this roadmap item.

See `docs/proposals.md` for the accepted live-trading design and other unapproved
feature proposals; proposals do not expand this roadmap.

## Deferred

- RAG/memory, lifecycle and version management.
- Authenticated order submission until all spec gates pass and each bounded live
  verification is separately approved.
- A meta-harness/control plane unless multiple independent harnesses exist.

## Updating this roadmap

- Change only harness-owned work. Cross-work-unit changes require approval in
  both plans.
- Start a milestone only with explicit user approval and an agreed contract.
- Externally observable changes require offline checks and bounded live
  verification against the changed boundary. A failed or unavailable check
  leaves the milestone incomplete.
- Mark work complete only after acceptance evidence exists and the change is
  committed. Do not add speculative abstractions or plugin systems.
