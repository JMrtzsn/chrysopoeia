# Paper accounting

**Status:** Implemented for the local, single-operator paper harness. The
product spec defines scope; `../chrysopoeia/accounting.py` and its tests define
record validation and replay behavior.

## Authority

For paper mode, `chrysopoeia.jsonl` is the authoritative financial record. Each
append is a versioned event; the book is derived by replay. Invalid or corrupt
records fail closed. Agents do not read or mutate the journal. The future
`trade_plan_ready` event is a verified plan/request, not a position or fill.
Each consumer owns a separate ledger and reconciles its own effects.

The journal records session configuration, admitted/finished turns, paper
fills, marks, closes, settlements, loss halts, session closure, and model cost. It is
local to the operator-selected directory; there is no multi-user or distributed
ledger.

## Positions and outcomes

- A fill opens one YES position per market. It records the entry snapshot, time,
  actual fill terms, and the entry-approved exit plan. Proposed limits are kept
  separate from achieved fill terms.
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
- `chrysopoeia run --journal DIR ...` owns a bounded multi-cycle session.

Authenticated execution, non-YES positions, plan changes after entry, and
partial paper exits are not part of the current accounting contract. Event
publishing/subscription and consumer ledgers are not implemented. The planned
paper consumer will preserve this bracket behavior but will not share this
producer journal.
