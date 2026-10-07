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
- The bounded trader-tool loop (`292b762`): deterministic market discovery,
  snapshot retrieval, and trade-plan checks with fail-closed limits. Live
  verified with the checked-in Vertex model 2026-10-06.
- One bounded live paper cycle through a non-Gemini provider (OpenRouter via ADK
  registry). Live verified 2026-09-27.

The recorded commands and evidence for harness milestones are in
`docs/verification.md`.

## Next

1. **Standalone local paper consumer:** add a local CLI that reads an existing
   `trade_plan_ready` JSON event, obtains a fresh public quote, rechecks the plan,
   and writes the local paper journal idempotently. It must require no platform,
   GCP, Pub/Sub, or always-on service.
2. **OpenRouter tool-loop verification:** the `adk-registry`/LiteLLM adapter is
   supported and had a bounded one-call smoke on 2026-09-27, but the checked-in
   default is Vertex and the bounded trader-tool loop has not been verified with
   an OpenRouter model. Select the OpenRouter model ID and matching explicit
   prices, then run a bounded verification with `OPENROUTER_API_KEY` supplied
   only through the ambient environment; never request or record its value.
3. **Optional external event transport and GCP/other consumers:** only after the
   standalone local consumer, select transport and delivery guarantees and, if
   needed, deploy an independent consumer adapter. Specify quote freshness,
   idempotency, ledger ownership, recovery, and exit monitoring/protection before
   any live activation. Platform work is ordered in `../platform/ROADMAP.md`.
4. **Polymarket live execution foundation:** verify the official Python SDK and
   supported EOA/order flow; implement isolated execution, structural limits,
   preflight, reconciliation, and kill switch in the consumer. Keep live mode
   disabled until all spec gates pass.
5. **Bounded live activation:** only after gates pass, run separately approved
   smallest-possible live order and exit verification with the dedicated $10
   wallet through the independently deployed event consumer.
6. **Citable research tools:** bounded providers normalized into provenance-
   carrying evidence shared by trader and reviewer; no execution authority.
7. **Additional venues and NO-side positions:** separate milestones after the
   Polymarket YES-only live path is verified.
8. **Future CCXT crypto-trading integration:** after the Polymarket YES-only
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
