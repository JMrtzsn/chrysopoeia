# Harness Proposals

The live-trading direction below is approved as design scope, not as permission
to submit orders. Other proposals remain unapproved. `../../.agents-cli-spec.md`
and `../ROADMAP.md` are the scope and ordering sources of truth.

## Approved live-trading direction

Polymarket first, binary YES-only, dedicated operator-owned EOA with no more than
$10 trading collateral, official Python SDK behind an isolated adapter. The
agent proposes the trade; the harness validates the reviewed, immutable plan and
produces `trade_plan_ready`. Independent consumers own paper outcomes or actual
orders, position monitoring, venue reconciliation, and separate ledgers. Orders
run automatically only after deterministic guards and explicit live-mode
opt-ins. No per-order approval. Execution consumers fail closed on blocked or
unavailable geoblock checks and never bypass venue restrictions.

Before live activation, complete paper trade plans and exits, bounded hard
limits, an idempotent event handoff, startup reconciliation, safe retry handling,
and a kill switch. No always-on harness or manager is assumed. Consumer/venue
exit monitoring and protection guarantees remain gated on verified venue/SDK
semantics. Position size remains the hard loss bound.
Passing implementation gates still requires separate operator approval for each
bounded live verification.

## Current in-process paper trade plans and exits

The harness emits a strict `trade_plan_ready` event after review and hard-policy
acceptance. Its in-process paper consumer validates the event and supplied
snapshot, then stores reviewer-approved entry terms, immutable exit brackets,
and achieved paper fills separately. While `chrysopoeia run` is
active, it evaluates profit, risk, time, and resolution exits against fresh,
depth-aware executable bids and fees. It supports full closes only, leaves a
position open when depth is insufficient, and journals closes so replay
recovers the correct state. This is an in-process paper simulation with no
signing or live orders. External transport and independently deployed consumers
remain deferred.

## Research tools

The trader now has bounded read-only venue discovery, snapshot capture, and
deterministic plan-check tools. Give it additional research tools for markets available through
configured venues. Candidate capabilities: web search, financial/economic data,
company records, and category-specific sources when needed. Search, FRED,
CoinGecko, and SEC EDGAR are candidate providers, not locked dependencies.

Normalize and validate results with provenance before the trader/reviewer can
cite them. Decide provider scope, whether the evidence includes source metadata
only or bounded observations too, and per-cycle call/cost limits before building.
Each shipped provider needs offline contract tests and a bounded live check.

## Binary outcome sides

Allow a proposal to select either outcome of a binary market. Keep the output
about canonical outcomes, not venue tokens; let each adapter map the outcome to
its venue representation. Apply the same citation, review, risk, fee, depth,
exposure, and settlement controls to either side. Polymarket is the first
adapter, not the domain model.

## Trade-plan event and terms

For the first working version, target public binary prediction markets through
the existing Polymarket adapter. Each opening proposal is a full trade plan:
canonical outcome, estimated probability, stake, acceptable entry price,
citations, and an exit plan. The exit plan states a profit target, a risk exit
(or explicitly accepts hold-to-resolution risk), and a time/resolution
condition. The adapter maps the outcome to a venue instrument; the harness
validates the proposal/review and hard policy. Only accepted plans produce a
`trade_plan_ready` event; abstentions and rejections do not. Its minimal envelope
contains version/type, stable `event_id` across redelivery, creation time, market
and snapshot identity, outcome, stake, maximum entry price, immutable ROI/time
exit plan, review approval and policy/evidence references, and expiry/market end.
It is a verified request, not an order, fill, position, or execution result.

Persist the entry-approved exit plan with the paper position. Paper closing is a
deterministic simulation against a fresh executable quote; a target is not a
guaranteed fill. Evaluate ROI net of fees and executable depth, not against a
mid-price. Consumers fetch fresh executable quotes rather than treating the
proposal snapshot as a current execution price.
Use a second venue to test portability before generalizing beyond binary
prediction markets.

## Independent event consumers

Paper simulation and future GCP/other execution listeners consume the same event
contract. Delivery may repeat, so each deduplicates by `event_id` and owns its
own ledger, effects, and outcomes. No consumer shares the producer journal or
has authority to alter the approved plan. Platform deployment and request
adapters never import the harness package.

The harness invocation may come from the existing CLI or a future HTTP/request
adapter calling the same core. Event transport (Pub/Sub, HTTP, local stream, or
other), persistence and delivery guarantees, and live order mechanisms are
intentionally deferred. Exit monitoring/protection is consumer/venue behavior;
its guarantees must be specified before live activation. The current cycle and
`run` do not publish or subscribe: the local paper consumer receives the event
in-process.

## Later position-management details

Support partial reductions and model-proposed changes to an existing exit plan
only as later work. Current bracket terms are immutable after entry approval.
Paper policy quotes full exits and records simulated P&L. A future execution
consumer owns actual close execution and reconciliation.

Partial paper closes require retained entry terms and remaining cost basis. Hard
exit limits belong to deterministic policy. Live consumer acceptance additionally
requires venue reconciliation tests and bounded verification of the changed
execution boundary.
