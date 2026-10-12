# Paper accounting

**Status:** Implemented for the local, single-operator paper harness. The
product spec defines scope; `../chrysopoeia/accounting.py` and its tests define
record validation and replay behavior.

## Authority

For paper mode, `chrysopoeia.jsonl` is the authoritative financial record. Each
append is a versioned event; the book is derived by replay. Invalid or corrupt
records fail closed. Agents do not read or mutate the journal. The future
`trade_plan_ready` event is a verified plan/request, not a position or fill. The
local paper journal stores that approved plan separately from its achieved fill.
The journal-backed local path consumes that event once and records its achieved
fill. The independent paper consumer and future execution consumers own separate
ledgers and reconcile their effects.

The journal records session configuration, admitted/finished turns, paper
fills, marks, closes, settlements, loss halts, session closure, and model cost. It is
local to the operator-selected directory; there is no multi-user or distributed
ledger.

## Positions and outcomes

- A fill opens one YES position per market. It records the original plan
  `snapshot_id`, the separate fresh `quote_snapshot_id`, time, actual fill terms,
  and the entry-approved exit plan. Proposed identity and limits remain intact
  and separate from achieved fill provenance and terms. Older journal fills
  without `quote_snapshot_id` remain valid.
- Public venue captures supply bid-depth, fee-adjusted liquidation marks for
  unrealized P&L; a failed or insufficient-depth capture adds no mark.
- Only an unambiguous venue resolution settles a position. YES resolution pays
  shares less the fee; NO resolution loses total cost. Unresolved or ambiguous
  markets are not settled.
- The paper simulator can close the entire position against fresh executable
  bids when an approved take-profit, stop-loss, or time trigger fires. If depth
  cannot close all shares, it stays open for the next loop iteration. Close P&L
  includes exit fees and counts toward the paper cumulative-loss halt. Partial
  paper closes are not implemented.
- Paper entry fills and exits are currently simulated in-process. Exits run only
  while `chrysopoeia run` is active. A stop is a trigger,
  not a guaranteed execution price. This bounded loop must not be treated as a
  live-position monitor.

## Turns and sessions

Turn IDs are deterministic from snapshot and market identity. Repeated
admission is a no-op. Recovery marks an unfinished turn `filled` when its fill
was journaled, otherwise `abandoned`; it never repeats model work. A market with
an open position cannot be admitted for another trade.

The bounded `run` session persists bankroll, loss limit, target win rate, and
window. It stops at the configured deadline, cycle/cost limit, stop request, or
loss halt, and reports completed-trade win rate and net P&L. The target does not
weaken risk limits or force trades.

## Commands

- `chrysopoeia book --journal DIR` replays and displays the book.
- `chrysopoeia mark --journal DIR` captures prices for open positions.
- `chrysopoeia settle --journal DIR --market MARKET` settles from venue
  resolution.
- `chrysopoeia cycle --journal DIR ...` admits one turn and records its outcome.
- `chrysopoeia consume --event EVENT.json --journal DIR` consumes one strict,
  bounded `trade_plan_ready` file into an existing open session. It deduplicates
  completed event IDs before public I/O, obtains a fresh public Polymarket quote,
  and records either one paper fill or a deterministic rejection. Quote failures
  occur before admission, leave no fill, and are retryable.
- `chrysopoeia run --journal DIR ...` owns a bounded multi-cycle session.
- `outbox-pending` and `outbox-ack` remain available for manual delivery
  recovery. Setting `CHRYSOPOEIA_EVENT_SINK` enables oldest-first direct delivery
  and requires the journal for event-producing commands.

Authenticated execution, non-YES positions, plan changes after entry, and
partial paper exits are not part of the current accounting contract. Event
publishing is optional through the Harness event sink; subscriptions and
external consumer ledgers are not implemented here. The local development consumer
preserves this bracket behavior in the current journal; future external
consumers do not share it.
