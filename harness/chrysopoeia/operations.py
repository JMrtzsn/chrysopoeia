"""Shared journal operations for one paper turn and venue maintenance."""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from chrysopoeia import accounting
from chrysopoeia.accounting import (
    JournalError,
    Position,
    admit_turn,
    check_halt,
    cycle_turn_id,
    finish_turn,
    record_mark,
    recover_open_turns,
    replay,
    settle,
)
from chrysopoeia.configuration import HarnessConfig
from chrysopoeia.paper_cycle import EvidenceRecord
from chrysopoeia.polymarket import (
    Fetch,
    MarketResolution,
    load_market_resolution,
    load_market_snapshot,
)
from chrysopoeia.trading import MarketSnapshot, OperatingConfig


class JournalWorkflowError(JournalError):
    """The journal rejected a completed turn result."""


class InvalidTurnInputError(ValueError):
    """An admitted turn received invalid local input."""


async def run_journal_turn(
    journal: Path,
    config: HarnessConfig,
    snapshot: MarketSnapshot,
    operating: OperatingConfig,
    *,
    run: Callable[..., Awaitable[dict[str, object]]] | None = None,
    load_evidence: Callable[[], Sequence[EvidenceRecord]] | None = None,
) -> dict[str, object]:
    """Run or recover one idempotent journal-backed paper turn."""
    from chrysopoeia.cycle_runner import reserved_ceiling

    if run is None:
        from chrysopoeia.cycle_runner import run_paper_cycle

        run = run_paper_cycle
    # ponytail: charge full reservation on failure; read the ADK cost ledger if over-reporting matters
    failed_cost = str(reserved_ceiling(config))

    recover_open_turns(journal)
    book = replay(journal)
    if snapshot.market_id in book.positions:
        raise JournalError(
            "market has an open journal position; settle it before restarting a cycle "
            "on the same market"
        )
    turn_id = cycle_turn_id(snapshot.snapshot_id, snapshot.market_id)
    prior = book.finished_turns.get(turn_id)
    if prior is not None:
        return {"status": prior}
    admit_turn(journal, turn_id, snapshot.snapshot_id, snapshot.market_id)
    try:
        evidence = load_evidence() if load_evidence is not None else None
    except (OSError, TypeError, ValueError) as exc:
        finish_turn(journal, turn_id, "failed")
        raise InvalidTurnInputError("invalid turn input") from exc
    try:
        result = await run(config, snapshot, operating, evidence=evidence)
        fill = result.get("fill")
        cost = result.get("actual_estimated_cost_usd", "0")
        if isinstance(fill, dict):
            accounting.record_fill(
                journal,
                Position(
                    market_id=snapshot.market_id,
                    snapshot_id=snapshot.snapshot_id,
                    entered_at=datetime.now(timezone.utc).isoformat(),
                    price=fill["price"],
                    amount=fill["amount"],
                    shares=fill["shares"],
                    fee=fill["fee"],
                    total_cost=fill["total_cost"],
                ),
                turn_id,
            )
            check_halt(journal, replay(journal))
            outcome = "filled"
        else:
            status = result.get("status")
            outcome = status if status in {"abstained", "rejected"} else "failed"
        finish_turn(journal, turn_id, outcome, model_cost_usd=str(cost))
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        state = replay(journal)
        if turn_id in state.open_turns:
            finish_turn(journal, turn_id, "failed", model_cost_usd=failed_cost)
        raise JournalWorkflowError("journal workflow rejected the fill") from exc
    except BaseException:
        state = replay(journal)
        if turn_id in state.open_turns:
            finish_turn(journal, turn_id, "failed", model_cost_usd=failed_cost)
        raise
    book = replay(journal)
    result["book_after"] = {
        "status": book.status,
        "realized_pnl": book.realized_pnl,
        "unrealized_pnl": book.unrealized_pnl,
        "open_exposure": book.open_exposure,
        "bankroll_now": book.bankroll_now,
        "open_positions": len(book.positions),
    }
    return result


def mark_positions(
    journal: Path,
    market_ids: Iterable[str],
    *,
    fetch: Fetch,
    load: Callable[..., MarketSnapshot] = load_market_snapshot,
) -> list[dict[str, object]]:
    """Capture and journal current prices for the selected open positions."""
    marked = []
    for market_id in market_ids:
        book = replay(journal)
        position = book.positions.get(market_id)
        if position is None:
            continue
        fresh = load(
            market_id,
            book.bankroll,
            position.total_cost,
            book.open_exposure,
            fetch=fetch,
            paper_fee_rate=0.0,
            paper_fee_source="paper-assumption:no-fee-v1",
        )
        record_mark(journal, replay(journal), market_id, fresh.price)
        marked.append(
            {
                "market_id": market_id,
                "entry_price": position.price,
                "mark_price": fresh.price,
                "mark_captured_at": fresh.captured_at,
            }
        )
    return marked


def settle_positions(
    journal: Path,
    market_ids: Iterable[str],
    *,
    fetch: Fetch,
    load: Callable[..., MarketResolution] = load_market_resolution,
) -> list[dict[str, str]]:
    """Settle selected positions from venue-derived resolutions."""
    settled = []
    for market_id in market_ids:
        record = load(market_id, fetch=fetch).as_dict()
        settle(journal, replay(journal), record["market_id"], record["resolution"])
        check_halt(journal, replay(journal))
        settled.append(record)
    return settled
