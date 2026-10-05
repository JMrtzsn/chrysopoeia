# Harness Proposals

The live-trading direction below is approved as design scope, not as permission
to submit orders. Other proposals remain unapproved. `../../.agents-cli-spec.md`
and `../ROADMAP.md` are the scope and ordering sources of truth.

## Approved live-trading direction

Polymarket first, binary YES-only, dedicated operator-owned EOA with no more than
$10 trading collateral, official Python SDK behind an isolated adapter. The
agent proposes the trade; the harness validates and records the reviewed,
immutable trade intent. A separate deterministic manager owns actual orders,
position monitoring, and venue reconciliation. Orders run automatically only
after deterministic guards and explicit live-mode opt-ins. No per-order approval.
The manager fails closed on blocked or unavailable geoblock checks and never
bypasses venue restrictions.

Before live activation, complete paper trade plans and exits, bounded hard
limits, a durable intent handoff, manager availability, startup reconciliation,
safe retry handling, and a kill switch. The on-demand Cloud Run Job is not an
always-on manager. Whether venue-native conditional orders can protect positions
while the manager is down, or manager-side monitoring is required, remains gated
on verified venue/SDK semantics. Position size remains the hard loss bound.
Passing implementation gates still requires separate operator approval for each
bounded live verification.

## First milestone: paper trade plans and exits

1. Add structured entry terms and an immutable exit bracket to the opening
   proposal: canonical outcome (YES only initially), estimated probability,
   stake, maximum entry price, profit target, risk exit (or explicit acceptance
   of hold-to-resolution risk), and time/resolution behavior. Represent ROI after
   fees and costs; validate ranges deterministically.
2. Persist the approved plan and actual fill terms with each position. Do not
   conflate proposed terms with achieved entry fills.
3. The reviewer approves the complete bracket before paper entry. The local
   deterministic simulator evaluates paper exits while `chrysopoeia run` is
   active; this is not the live trade manager and makes no actual orders. Capture
   fresh executable bid depth for open paper positions. Calculate net ROI as
   `(executable liquidation proceeds after fees - entry cost) / entry cost`; use
   depth-aware bids, never mid-price.
4. Support full closes only. If bids cannot fill the whole position, leave it
   open and retry on the next loop iteration. A stop is a trigger, not a
   guaranteed execution price; size the position for the maximum loss if exit
   liquidity disappears. Paper exits are evaluated only while the harness loop
   runs.
5. Journal close and recovery atomically: after a restart, replay shows the
   position open if no close event was written, or closed if the event was
   written. Resolution remains the fallback for positions explicitly held to
   resolution.
6. Acceptance: offline tests cover profit/risk/time triggers, fees and depth,
   resolution, rejected entry reviews, full-close depth failures, and crash
   recovery. Run bounded public-price verification only; do not add signing or
   live orders in this milestone.

## Research tools

Give the trader bounded, read-only research tools for markets available through
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

## Trade intent and terms

For the first working version, target public binary prediction markets through
the existing Polymarket adapter. Each opening proposal is a full trade plan:
canonical outcome, estimated probability, stake, acceptable entry price,
citations, and an exit plan. The exit plan states a profit target, a risk exit
(or explicitly accepts hold-to-resolution risk), and a time/resolution
condition. The adapter maps the outcome to a venue instrument; the harness
validates the proposal/review and persists an immutable intent. In paper mode,
the simulator records simulated fills. In live mode, the separate deterministic
manager consumes the intent and records actual venue acknowledgements/fills; the
harness must not label an intent as a fill. Don't expose venue token IDs or order
semantics the paper simulator cannot honor.

Persist the entry-approved exit plan with the paper position. Paper closing is a
deterministic simulation against a fresh executable quote; a target is not a
guaranteed fill. Evaluate ROI net of fees and executable depth, not against a
mid-price. Live closing belongs to the execution manager, not the model cycle.
Use a second venue to test portability before generalizing beyond binary
prediction markets.

## Deterministic live trade manager

The manager is a separate process from the ADK proposal/review runtime. It
consumes durable approved trade intents, applies deterministic hard limits,
executes or supervises venue orders, monitors positions, reconciles uncertain
submissions and fills, and records lifecycle events. It has no model calls or
authority to alter the approved plan. The platform owns its deployment and
availability; the harness artifact supplies its deterministic venue-facing
contract without platform imports of the harness package.

Before implementation, agree on the durable intent/outbox and event schema,
idempotency and restart behavior, venue-native order support, required monitoring
latency, and manager availability contract. If exits depend on software
monitoring, the manager must remain available while positions are open. The
current on-demand Cloud Run Job cannot provide that guarantee. Keep paper
simulation separate so it remains testable without credentials or live effects.

## Later position-management details

Support partial reductions and model-proposed changes to an existing exit plan
only as later work. Current bracket terms are immutable after entry approval.
Paper policy quotes full exits and records simulated P&L. The live manager's
venue adapter owns actual close execution and reconciliation.

Partial paper closes require retained entry terms and remaining cost basis. Hard
exit limits belong to deterministic policy. Live manager acceptance additionally
requires venue reconciliation tests and bounded verification of the changed
execution boundary.
