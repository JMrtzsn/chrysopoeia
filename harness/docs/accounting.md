# Paper accounting

**Status:** Implemented for the local, single-operator paper harness. The
product spec defines scope; `../chrysopoeia/accounting.py` and its tests define
record validation and replay behavior.

## Authority

`chrysopoeia.jsonl` is the authoritative financial record. Each append is a
versioned event; the book is derived by replay. Invalid or corrupt records fail
closed. Agents do not read or mutate the journal.

The journal records session configuration, admitted/finished turns, paper
fills, marks, settlements, loss halts, session closure, and model cost. It is
local to the operator-selected directory; there is no multi-user or distributed
ledger.

## Positions and outcomes

- A fill opens one YES position per market. It records entry snapshot, time,
  price, amount, shares, fee, and total cost.
- Public venue captures supply marks for unrealized P&L; a failed capture adds
  no mark.
- Only an unambiguous venue resolution settles a position. YES resolution pays
  shares less the fee; NO resolution loses total cost. Unresolved or ambiguous
  markets are not settled.
- Settlement that crosses the configured cumulative-loss limit halts further
  turns. Closing or partially reducing positions before resolution is not
  implemented.

## Turns and sessions

Turn IDs are deterministic from snapshot and market identity. Repeated
admission is a no-op. Recovery marks an unfinished turn `filled` when its fill
was journaled, otherwise `abandoned`; it never repeats model work. A market with
an open position cannot be admitted for another trade.

The bounded `run` session persists bankroll, loss limit, target win rate, and
window. It stops at the configured deadline, cycle/cost limit, stop request, or
loss halt, and reports settled win rate and net P&L. The target does not weaken
risk limits or force trades.

## Commands

- `chrysopoeia book --journal DIR` replays and displays the book.
- `chrysopoeia mark --journal DIR` captures prices for open positions.
- `chrysopoeia settle --journal DIR --market MARKET` settles from venue
  resolution.
- `chrysopoeia cycle --journal DIR ...` admits one turn and records its outcome.
- `chrysopoeia run --journal DIR ...` owns a bounded multi-cycle session.

Authenticated execution, non-YES positions, and pre-resolution exits are not
part of the current accounting contract.
