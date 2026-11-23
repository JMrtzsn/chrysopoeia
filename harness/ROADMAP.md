# Harness roadmap

Completed items are removed; see git history.

`.agents-cli-spec.md` defines product scope and acceptance. This roadmap orders
approved harness work only. Paths are relative to `harness/` unless noted.
Verification policy and harness evidence are in `docs/verification.md`.
The platform consumes a released harness artifact. Event adapters and consumers
are coordinated harness/platform work recorded in both roadmaps.

Operator-approved cross-work-unit direction (2026-10-06): use the supported
Vertex `gemini-3.5-flash` model and its non-global pricing, with the `us` model
endpoint configured separately from the platform compute region.

## Next

**Decision (operator, 2026-11-19): the research forecaster is retired as a
strategy.** Esports-only paper results (Nov 12–18): 11 settled trades, 5 wins,
−$18.03 on $49.98 staked; model cost $18.51 for 62 turns. Public research is
information the market already prices. The code stays until item 2 reports. A
model is used only where it adds reading capacity the market lacks, never as
the probability source.

1. **Bounded cycle wall-clock** (deprioritized 2026-11-19: needed only if the
   research loop is revived). Since 2026-11-17 most scheduled cycles stall
   after a model `function_call` and are killed at the Cloud Run 900 s task
   timeout. Scope: find the stalled call; add per-call timeouts on model,
   research, and venue calls plus a cycle deadline below the task timeout that
   records a journal outcome. Acceptance: an offline test where a hanging stub
   ends the cycle with a recorded timeout outcome, plus one bounded live cycle
   that finishes under the deadline.
2. **Market-structure signal study** (operator-requested 2026-11-19; no
   trading, no paper fills, no cloud resources). Question: does Polymarket
   misprice markets in ways a model can find by reading, after fees and
   spread? One daily scan of public market data covers two signal types:
   - **Inconsistent related markets.** Within an event, mutually exclusive
     outcomes are checked deterministically (asks summing below 1, or bids
     above 1, after fees); no model. Across events, the model proposes
     implication pairs as structured claims; code checks `P(A) <= P(B)` on
     executable books.
   - **Rules versus price.** The model reads each market's resolution text
     once (cached by market ID and rules hash), extracts condition, deadline,
     and source as structured fields, and flags only a cited disagreement
     between literal rules and price. Prices, edge, and fees are computed by
     code.

   Each flag is appended to a local study journal (market, claim, quote,
   executable price and size, fee, expiry). After settlement a scorer computes
   hit rate, hypothetical net P&L, and model cost per flag. Bounds: public
   read-only APIs, cached model calls, a fixed daily market cap, a hard $1/day
   model-cost cap, local on-demand runs. External text is untrusted evidence.

   **Kill rule:** after 3 weeks or 100 settled flags, whichever is later,
   continue only if mean net return per flag and the lower bound of a 90%
   bootstrap interval are above 0, and model cost is below hypothetical net
   profit. Otherwise record the result here and retire the forecaster code.
   Acceptance: offline tests for constraint checks, claim schema, cost cap, and
   scorer on fixtures; then one bounded live daily scan with recorded cost. A
   positive result needs a separate approved item to paper-trade the signals.
3. **Model comparison and switch** (operator-requested 2026-11-19). Question:
   did `gemini-3.5-flash` cause the forecaster's loss?
   - **Baseline (no model cost):** score all 62 archived esports turns
     (Nov 12–18) against same-time market price and result (Brier, log loss).
   - **Replay:** confirm journals kept full research inputs, then rerun them
     on 2–3 stronger models via existing adapters. No live search; recorded
     inputs only.
   - **Bounds:** at most 3 candidates, one replay per turn per model, $10
     total cap, fixture-tested offline scoring.
   - **Decision rule:** switch the `[models]` roles in `configs/platform.toml`
     and `chrysopoeia.toml` only if a candidate beats both the market and
     Flash on Brier with a 90% bootstrap interval excluding no improvement
     over the market. Trading resumes only as a separately approved paper
     trial. If none beats the market, record that and close. Item 2 does not
     wait for this item.

The Observer journey health work is tracked in `../observer/ROADMAP.md`.

## Older

Earlier approved items still open. Automated runs now target CS2/Dota 2 match
winners (operator approval 2026-11-07); BTC 5m automation is retired.

2. **Live accepted-plan delivery:** verify a model-produced `trade_plan_ready`
   event reaches the deployed Consumer and produces a paper fill. Local
   delivery is verified (2026-10-15); the deployed path is not.
3. **Liquidity-aware sizing and profitability by amount** (operator-approved
   2026-10-19; offline implementation complete 2026-10-26). Distinguishes the
   policy allowance from measured book capacity that still meets the net-edge
   requirement, per selected token, comparing candidate stakes (shares, VWAP,
   worst price, slippage, fees, expected net profit/ROI, marginal edge). Never
   increases the allowed stake to match depth. Remaining: separately approved
   bounded public-book verification and image redeploy.
4. **Additional research providers:** financial/company-data sources (e.g.
   FRED, CoinGecko, SEC EDGAR) remain open until separately selected and
   verified.
5. **Trading-history context source:** read-only BigQuery-backed evidence tool,
   after outcome data exists; see the spec's approved future item.
6. **Additional venues:** separate milestones after the Polymarket paper path is
   verified. Event-contract changes use new schema versions.
7. **Future CCXT crypto-trading integration:** CCXT is used only for public
   OHLCV. Any crypto venue execution needs its own plan, risk, and activation
   gates.
8. **Outcome-driven market contexts and agent-approved profile iteration**
   (operator-approved 2026-10-21). The context-profile loop, catalog,
   curator/reviewer flow, 20-finalized-plan activation gate, platform image,
   enabled profile, and Consumer outcome events are in place. Remaining steps
   (each separately approved, coordinated with Platform item 5):
   4. **Accumulate evidence:** run bounded cycles until one context has ≥20
      finalized outcomes under its active profile version
      (`completed_trade_count`; synthetic outcomes excluded). The first
      campaign (2026-10-25/26) yielded 2 completed trades and resumes after
      item 3 ships.
   5. **First revision turn:** verify a curator/reviewer revision is recorded,
      activated only for later turns, and that archive aggregates match the
      journal; record evidence in `docs/verification.md`.

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
- Remove work once acceptance evidence exists and the change is committed. Do
  not add speculative abstractions or plugin systems.
