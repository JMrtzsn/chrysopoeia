# Paper accounting

Implemented for the local, single-operator paper harness.
`../chrysopoeia/accounting.py` and its tests define record validation and
replay.

## Authority

- `chrysopoeia.jsonl` is the authoritative paper record. Each append is a
  versioned event; the book is derived by replay. Invalid or corrupt records
  fail closed. Agents never read or write the journal.
- It records session configuration, admitted/finished turns, fills, marks,
  closes, settlements, loss halts, session closure, and model cost, in an
  operator-selected local directory. There is no multi-user or distributed
  ledger.
- `trade_plan_ready` is a plan, not a fill. The journal-backed path consumes it
  once and stores the plan separately from the achieved fill. Independent and
  future execution consumers keep their own ledgers.
- Decided-turn outcomes hold up to five plan-check attempts with deterministic
  reasons and the validated submitted plan (`null` if its schema was invalid).
  Replay treats v1 outcomes without `plan_checks` as an empty list.

## Positions and outcomes

- A fill opens one position per market on the selected outcome (YES/Up or
  NO/Down); v1 plans are YES-only, NO buys use v2. The journal keeps the plan
  `snapshot_id`, the fresh `quote_snapshot_id`, time, actual fill terms, and the
  approved exit plan, separate from the proposed terms. Older fills without
  `quote_snapshot_id` and legacy fills without a plan (YES) stay valid.
- Marks are bid-depth, fee-adjusted liquidation values from public captures; a
  failed or too-shallow capture adds no mark.
- Settlement needs an unambiguous venue resolution. A winning held outcome pays
  shares less fees; otherwise the total cost is lost.
- On a take-profit, stop-loss, or time trigger, the simulator closes the whole
  position against fresh executable bids. Insufficient depth leaves it open for
  the next iteration. Close P&L includes exit fees and counts toward the loss
  halt.
- Exits run only while `chrysopoeia run` is active. A stop is a trigger, not a
  guaranteed price, and this loop is not a live-position monitor.

## Turns and sessions

Turn IDs derive from snapshot and market identity; re-admission is a no-op.
Recovery marks an unfinished turn `filled` if its fill was journaled, otherwise
`abandoned`, and never repeats model work. A market with an open position cannot
be admitted again.

A `run` session persists bankroll, loss limit, target win rate, and window. It
stops at the deadline, cycle/cost limit, stop request, or loss halt, and reports
completed-trade win rate and net P&L. The target never weakens risk limits or
forces trades.

## Commands

| Command | Effect |
| --- | --- |
| `chrysopoeia book --journal DIR` | Replay and display the book |
| `chrysopoeia mark --journal DIR` | Capture prices for open positions |
| `chrysopoeia settle --journal DIR --market MARKET` | Settle from venue resolution |
| `chrysopoeia cycle --journal DIR ...` | Admit one turn and record its outcome |
| `chrysopoeia run --journal DIR ...` | Run a bounded multi-cycle session |
| `chrysopoeia consume --event EVENT.json --journal DIR` | Consume one strict `trade_plan_ready` into an open session |
| `outbox-pending`, `outbox-ack` | Manual delivery recovery |

`consume` skips completed event IDs before any I/O, fetches a fresh public
Polymarket quote, and records one fill or a deterministic rejection. Quote
failures happen before admission, leave no fill, and are retryable.

`CHRYSOPOEIA_EVENT_SINK` enables oldest-first delivery of accepted plans and
decided-turn outcomes to one topic; event-producing commands then require a
journal, and subscribers filter on `record_type`.

Not in scope: authenticated execution, plan changes after entry, partial exits,
and subscriptions or external consumer ledgers.
