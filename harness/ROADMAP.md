# Harness roadmap

`.agents-cli-spec.md` defines product scope and acceptance. This roadmap orders
approved harness work only. Paths are relative to `harness/` unless noted.
Verification policy and harness evidence are in `docs/verification.md`.
The platform consumes a released harness artifact; the roadmaps are otherwise
independent.

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

1. **Research tools:** bounded search, financial-data, and company-data inputs
   normalized into provenance-carrying evidence the trader and reviewer can
   cite. They carry no execution authority.
2. **Additional venues:** one adapter milestone at a time, with canonical
   normalization and contract tests. Research providers are not venues.

See `docs/proposals.md` for unapproved feature proposals; proposals do not expand
this roadmap.

## Deferred

- RAG/memory, lifecycle and version management.
- Authenticated execution, which remains prohibited pending the spec's explicit
  prerequisites.
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
