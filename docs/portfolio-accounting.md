# Multi-Cycle Portfolio And Paper Accounting Design

Status: design, not implemented. This document is the accounting contract
referenced by the harness roadmap. It defines cross-cycle accounting and derives
the persistence requirement from it; nothing here expands authenticated
execution or Phase 1 scope. The spec (`.agents-cli-spec.md`) remains authoritative.

## Problem

Today one cycle is stateless: `MarketSnapshot` carries a bankroll and assumed
current exposures supplied per run, and a `SimulatedFill` dies with the process.
Nothing tracks that a buy happened, how the position is marked later, whether
the maximum-loss budget is exhausted across cycles, or what happens when a
market resolves. Multi-cycle operation needs the financial session state to be
authoritative, inspectable, and miss simpler-with-recovery.

## Scope

- Multiple paper cycles across multiple markets with cross-cycle positions.
- Realized and unrealized P&L and bankroll evolution.
- Hard maximum cumulative loss across the session.
- Market resolution as the terminal settlement event.
- Durable local records selected by this design, not by habit.

## Accounting Primitives

### Position

A position is one YES entry created by one accepted paper fill. Chrysopoeia
paper-trades YES only today; the model extends mechanically to NO later.

```python
@dataclass(frozen=True)
class Position:
    position_id: str  # deterministic: snapshot_id:market_id:entered_at
    market_id: str
    snapshot_id: str  # entry-provenance: the fill's snapshot
    entered_at: str  # UTC ISO timestamp of the paper fill
    fill: SimulatedFill  # price, amount, shares, fee, total_cost
    status: PositionStatus  # open | closed
    exit: ClosingFill | None  # realized exit; None while open
```

### Book

The book is the only authoritative financial state. It is a monotonic ledger
plus derived aggregates, never a mutable balance that agents know about.

```python
@dataclass
class Book:
    config: OperatingConfig  # frozen at session start
    realized_pnl: float = 0.0  # settled economics only
    positions: list[Position] = []
    fills: list[PaperFillRecord] = []
```

Derived, never stored: `open_exposure = sum(open_positions.total_cost)`,
`bankroll_now = config.bankroll + realized_pnl - open_exposure - open_fee_debt`,
`unrealized_pnl = sum(shares * mark_price - total_cost)` over open positions.

### Marking

Unrealized P&L requires a mark price. Marks come only from captured canonical
snapshots (`polymarket capture MARKET` re-run on the same market ID, matched by
`market_identity`, not by snapshot ID). No agent, model, or memory may assert a
mark; a stale market (capture fails or book is empty) is marked at last known
price with `stale=True` recorded in the report. A market past its end_time that
has not resolved is not auto-settled; it keeps waiting on its resolution record.

### Realized P&L

Positions close only three ways:

1. **Resolution YES**: pay `shares * 1` gross, minus the same flat paper fee
   contract → `pnl = shares * (1 - fee_rate) - total_cost`.
2. **Resolution NO**: `pnl = 0 - total_cost` (full loss of cost incl. fee).
3. **Exit by capture** (optional later operator action): paper-fill an exit at
   the current book against YES asks for the NO side equivalent — deferred;
   resolution-only closing is today's scope (simulates hold-to-resolution,
   matching the strategy the agents are asked to express).

## Limits And Enforcement

- `maximum_loss` becomes cumulative session loss: `realized_pnl <=
  -config.maximum_loss` (or bankroll_now below the floor) **admits no further
  turns**: the session enters `halted_on_loss` and only inspection/exit is
  possible until the operator resets with a new explicit session.
- Per-market and total exposure checks (existing `check_risk`) get their
  `market_exposure`/`total_exposure` inputs from the book's open positions
  instead of operator-claimed CLI values. The book is authoritative; agents and
  operator flags can only *misreport* their own numbers, not the actual
  exposure.
- Cost gates stay channel-specific and unchanged (model-cost budget in
  `cost.py`; loss accounting is separately tracked here).

## Resolution Discovery

Resolution enters the same process as market data: the venue adapter gains a
**read-only, public** `resolution` capability via the existing Gamma/CLOB
endpoints (e.g. outcome flag on a closed market). It is normalized to canonical
domain values (`resolved_yes | resolved_no | expired_unresolved`) with
captured_at provenance, exactly like snapshot normalization today. Agents never
assert resolution; the deterministic settlement step consumes the normalized
venue fact.

## Persistence Requirement (derived, minimal)

Durable state exists because *only* these need to survive process death:

1. `Book` construction (config + realized P&L + positions + fills).
2. The in-flight turn, deterministically abandoned after process death unless
   its fill was already recorded. Recovered turns never re-run models.

Everything else (agent text, eval data, evidence) stays ephemeral/in-memory per
the Phase 1 contract. Therefore milestone 3's implementation is deliberately
small:

- A local **atomic journal file** (JSON Lines, one record per event, appended
  with one `O_APPEND` write followed by `fsync`) in an operator-chosen
  directory. Records: `session_opened`, `turn_admitted`, `fill_recorded`,
  `turn_finished`, `mark_recorded`, `settled`, `session_halted`,
  `session_closed`.
- The book is *derived* by replaying the journal; the journal is the truth, so
  corruption of one line cannot silently rewrite history (fail loudly, refuse
  to resume from a corrupt tail with a `skip`-or-`stop` operator choice).
- **Idempotent turn admission** (milestone 4): a turn ID
  (deterministic from snapshot_id + market_id) is recorded
  before the model-call step in a `turn_admitted` record; admission replay
  makes a duplicate trigger a no-op that returns the prior record. Terminal
  outcomes are recorded in `turn_finished`; admitted turns left unfinished are
  recovered as filled when a linked fill exists and abandoned otherwise,
  without replaying model steps.
- Inspection CLI: `chrysopoeia book --journal DIR` prints positions, P&L,
  exposure, halted state. No agent tool may read or mutate the journal mid-turn
  except through deterministic core functions.

Not in scope until demonstrated need: DatabaseStorage, Cloud SQL, multi-user.

## Workflow Changes

Turn flow after capture: `admit turn -> reserve exposure in-memory -> model
steps -> policy -> paper fill -> record fill`. On fill, the caller passes the
book-derived snapshot values; cycle code is unchanged except that
`market_exposure`/`total_exposure` come from the book and the report gains a
`book_after` summary block for the operator.

## Non-Goals

- No authenticated execution, live fills, or venue P&L reconciliation.
- NO-side or exit-by-capture paper trading (design accommodates, not built).
- Memory/RAG learning from P&L; memory remains strictly post-cycle,
  non-authoritative, per the existing contract.
- Optimization of agent strategy from realized results (evaluation framework
  might later, but accounting only reports).

## Acceptance (for implementing milestone 3)

- Deterministic offline tests: journal replay reconstructs the book; a filled
  position marked YES/NO realizes the documented fee-inclusive P&L; cumulative
  loss halt appears after crossing `maximum_loss`; exposure checks read book
  state, not CLI flags; duplicate turn admission is a clean no-op.
- Bounded live verification once against the model-involved resumable path
  (one paper cycle with journaling, real Vertex call) — the money path is
  deterministic, but the runtime integration is externally observable.
