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
    close_position,
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
from chrysopoeia.trading import ExitPlan, MarketSnapshot, OperatingConfig, quote_exit


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
                    exit_plan=(
                        ExitPlan(**fill["exit_plan"])
                        if isinstance(fill.get("exit_plan"), dict)
                        else None
                    ),
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
    paper_fee_rate: float,
    paper_fee_source: str,
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
            paper_fee_rate=paper_fee_rate,
            paper_fee_source=paper_fee_source,
        )
        quote = quote_exit(fresh, position.shares)
        record_mark(
            journal,
            replay(journal),
            market_id,
            quote.price,
            quote.net_proceeds,
        )
        marked.append(
            {
                "market_id": market_id,
                "entry_price": position.price,
                "mark_price": quote.price,
                "mark_value": quote.net_proceeds,
                "mark_captured_at": fresh.captured_at,
            }
        )
    return marked


def evaluate_exits(
    journal: Path,
    market_ids: Iterable[str],
    *,
    now: datetime,
    fetch: Fetch,
    paper_fee_rate: float,
    paper_fee_source: str,
    load: Callable[..., MarketSnapshot] = load_market_snapshot,
) -> list[dict[str, object]]:
    """Mark positions and execute triggered full closes from one fresh quote each."""
    if now.tzinfo is None:
        raise ValueError("exit evaluation time must include a UTC offset")
    evaluated = []
    current = now.astimezone(timezone.utc)
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
            now=current,
            fetch=fetch,
            paper_fee_rate=paper_fee_rate,
            paper_fee_source=paper_fee_source,
        )
        quote = quote_exit(fresh, position.shares)
        record_mark(
            journal,
            replay(journal),
            market_id,
            quote.price,
            quote.net_proceeds,
        )
        plan = position.exit_plan
        reason = None
        if plan is not None:
            roi = (quote.net_proceeds - position.total_cost) / position.total_cost
            if plan.exit_by is not None and current >= datetime.fromisoformat(
                plan.exit_by.replace("Z", "+00:00")
            ):
                reason = "time"
            elif plan.stop_loss_roi is not None and roi <= plan.stop_loss_roi:
                reason = "stop_loss"
            elif roi >= plan.take_profit_roi:
                reason = "take_profit"
        if reason is not None:
            close_position(
                journal,
                market_id,
                reason,
                fresh.snapshot_id,
                quote.price,
                quote.gross_proceeds,
                quote.fee,
                current.isoformat(),
            )
            check_halt(journal, replay(journal))
        evaluated.append(
            {
                "market_id": market_id,
                "mark_price": quote.price,
                "net_proceeds": quote.net_proceeds,
                "exit_reason": reason,
            }
        )
    return evaluated


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
