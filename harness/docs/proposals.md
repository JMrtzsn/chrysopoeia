# Harness Proposals

The live-trading direction below is approved as design scope, not as permission
to submit orders. Other proposals remain unapproved. `../../.agents-cli-spec.md`
and `../ROADMAP.md` are the scope and ordering sources of truth.

## Approved live-trading direction

Polymarket first, binary YES-only, local execution, dedicated operator-owned EOA
with no more than $10 trading collateral, official Python SDK behind an isolated
adapter. Orders run automatically only after deterministic guards and explicit
live-mode opt-ins. No per-order approval. The harness fails closed on blocked or
unavailable geoblock checks and never bypasses venue restrictions.

Before live activation, complete paper trade plans and exits, bounded hard
limits, startup reconciliation, durable order intent, safe retry handling, and
a kill switch. V1 does not intentionally rest orders; stops are best-effort
while the local process is running and executable bids are available. Position
size remains the hard loss bound. Passing implementation gates still requires
separate operator approval for each bounded live verification.

## First milestone: paper trade plans and exits

1. Add structured entry terms and exit policy to the proposal: canonical outcome
   (YES only initially), estimated probability, stake, maximum entry price,
   profit target, risk exit, and time/resolution behavior. Represent ROI after
   fees and costs; validate ranges deterministically.
2. Persist the approved plan and actual fill terms with each position. Do not
   conflate proposed levels with achieved fills.
3. Capture fresh executable bid depth for open YES positions. Evaluate exits in
   the harness loop; convert a triggered exit into a separate trader proposal
   and reviewer decision, then let deterministic policy quote and journal the
   close. Untriggered positions continue toward the planned time/resolution path.
   Calculate net ROI as `(executable liquidation proceeds after fees - entry
   cost) / entry cost`; use depth-aware bids, never mid-price.
4. Make replay/recovery correct for full and partial fills/closes. A stop is a
   trigger, not a guaranteed execution price; size the position for the maximum
   loss if exit liquidity disappears.
5. Acceptance: offline tests cover profit/risk/time triggers, fees and depth,
   resolution, rejected reviews, partial/pending closes, and crash recovery. Run
   bounded public-price verification only; do not add signing or live orders in
   this milestone.

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
validates terms and records actual fill price and time. Don't expose venue token
IDs or order semantics the paper executor cannot honor.

Persist the approved exit plan with the position. A later close is a separate
reviewed decision against a fresh executable exit quote; a target is not a
guaranteed fill. Evaluate ROI net of fees and executable depth, not against a
mid-price. A stop can be crossed or unfillable if the market gaps or has no bids;
the stake/risk cap remains the hard loss bound. Use a second venue to test
portability before generalizing beyond binary prediction markets.

## Later position-management details

Support reviewed close and partial-reduction decisions against a fresh snapshot.
The entry's persisted exit plan tells the loop when a close should be considered;
the trader proposes and the reviewer approves or rejects. The venue adapter must
capture bid-side depth; deterministic policy quotes the exit, calculates realized
P&L, and updates the journal. Resolution remains the terminal path for positions
explicitly held to resolution.

Define retained entry terms, close triggers, and remaining cost basis for partial
closes. Hard exit limits belong to deterministic harness policy. Acceptance
needs replayable accounting tests and bounded public-price verification with
paper accounting only.
