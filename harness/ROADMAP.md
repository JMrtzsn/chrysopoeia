# Harness roadmap

`.agents-cli-spec.md` defines product scope and acceptance. This roadmap orders
approved harness work only. Paths are relative to `harness/` unless noted.
Verification policy and harness evidence are in `docs/verification.md`.
The platform consumes a released harness artifact. Live trade management is a
coordinated harness/platform work item recorded in both roadmaps.

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
- One bounded live paper cycle through a non-Gemini provider (OpenRouter via ADK
  registry). Live verified 2026-09-27.

The recorded commands and evidence for harness milestones are in
`docs/verification.md`.

## Next

1. **Paper trade plans and exits:** add an entry/exit-plan contract to opening
   proposals; persist it with the position; evaluate profit, risk, and
   time/resolution exits from fresh public quotes; journal simulated closes and
   recovery. This local simulator is not the live position manager. No
   authenticated orders.
2. **Trade-intent and manager contract:** define the durable approved-intent
   handoff, event ledger, idempotency/recovery rules, venue reconciliation, and
   required manager availability. The agent/harness creates approved plans; a
   separate deterministic process manages actual orders and positions. Platform
   deployment is ordered in `../platform/ROADMAP.md`. Operator-approved
   architecture direction, 2026-10-05; implementation remains gated on this
   agreed contract.
3. **Polymarket live execution foundation:** verify the official Python SDK and
   supported EOA/order flow; implement the isolated manager execution boundary,
   structural limits, preflight, durable intent/reconciliation, and kill switch.
   Keep live mode disabled until all spec gates pass.
4. **Bounded live activation:** only after gates pass, run separately approved
   smallest-possible live order and exit verification with the dedicated $10
   wallet through the separately deployed deterministic manager.
5. **Citable research tools:** bounded providers normalized into provenance-
   carrying evidence shared by trader and reviewer; no execution authority.
6. **Additional venues and NO-side positions:** separate milestones after the
   Polymarket YES-only live path is verified.

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
