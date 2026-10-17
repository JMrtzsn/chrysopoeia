"""Bounded autonomous paper-trading session loop."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from chrysopoeia.accounting import Book, check_halt, open_session, replay
from chrysopoeia.configuration import HarnessConfig
from chrysopoeia.cycle_runner import reserved_ceiling
from chrysopoeia.events import configured_sink, drain
from chrysopoeia.operations import evaluate_exits, run_journal_turn, settle_positions
from chrysopoeia.polymarket import Fetch, _fetch, discover_markets, load_market_snapshot
from chrysopoeia.trading import OperatingConfig


class StopFlag:
    """Signal-safe mutable stop request."""

    requested = False

    def stop(self, *_: object) -> None:
        self.requested = True


@dataclass(frozen=True)
class LoopParams:
    journal: Path
    bankroll: float
    maximum_loss: float
    target_win_rate: float
    window_minutes: float
    max_cycles: int
    cost_budget: Decimal
    interval_seconds: float
    maximum_market_exposure: float = 0.01
    maximum_total_exposure: float = 0.10
    daily_cloud_cost_budget: float = 5.0
    stop_file: Path | None = None
    stop_flag: StopFlag | None = None


def _stop_reason(
    params: LoopParams, book: Book, current: datetime, window_end: datetime, cycles: int
) -> str | None:
    if current >= window_end:
        return "deadline"
    if cycles >= params.max_cycles:
        return "max_cycles"
    if (params.stop_file is not None and params.stop_file.exists()) or (
        params.stop_flag is not None and params.stop_flag.requested
    ):
        return "stopped"
    if book.status != "open":
        return "halted"
    return None


def _report(book: Book, reason: str, cycles: int) -> dict[str, object]:
    if book.target_win_rate is None:
        raise ValueError("loop session target win rate is missing")
    completed_trades = book.settled_trades + book.closed_trades
    win_rate = book.winning_trades / completed_trades if completed_trades else None
    model_cost = float(book.model_cost_usd)
    return {
        "stop_reason": reason,
        "cycles_run": cycles,
        "trades_filled": len(book.filled_turns),
        "settled_trades": book.settled_trades,
        "closed_trades": book.closed_trades,
        "winning_trades": book.winning_trades,
        "win_rate": win_rate,
        "target_win_rate": book.target_win_rate,
        "target_met": None if win_rate is None else win_rate >= book.target_win_rate,
        "realized_pnl": book.realized_pnl,
        "unrealized_pnl": book.unrealized_pnl,
        "model_cost_usd": model_cost,
        "net_pnl": book.realized_pnl + book.unrealized_pnl - model_cost,
        "window_end": book.window_end,
    }


async def run_loop(
    params: LoopParams,
    config: HarnessConfig,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], Awaitable[None]],
    fetch: Fetch = _fetch,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run a bounded session and return its final report and iteration records."""
    requested_end = now().astimezone(timezone.utc) + timedelta(
        minutes=params.window_minutes
    )
    book = open_session(
        params.journal,
        params.bankroll,
        params.maximum_loss,
        target_win_rate=params.target_win_rate,
        window_end=requested_end,
        window_minutes=params.window_minutes,
    )
    window_end = datetime.fromisoformat(book.window_end or "")
    operating = OperatingConfig(
        params.bankroll,
        1,
        params.maximum_market_exposure,
        params.maximum_total_exposure,
        params.maximum_loss,
        params.daily_cloud_cost_budget,
    )
    iterations: list[dict[str, object]] = []
    cycles = len(book.admitted_turns)
    while True:
        sink = configured_sink()
        if sink:
            drain(params.journal, sink)
        book = replay(params.journal)
        check_halt(params.journal, book)
        book = replay(params.journal)
        reason = _stop_reason(params, book, now(), window_end, cycles)
        if (
            reason is None
            and book.model_cost_usd + reserved_ceiling(config) > params.cost_budget
        ):
            reason = "cost_budget"
        if reason is not None:
            return _report(book, reason, cycles), iterations

        iteration: dict[str, object] = {"iteration": len(iterations) + 1, "errors": []}
        errors = iteration["errors"]
        assert isinstance(errors, list)
        for market_id in tuple(book.positions):
            try:
                settle_positions(params.journal, (market_id,), fetch=fetch)
            except Exception as exc:
                if "not resolved yet" not in str(exc):
                    errors.append(f"settlement unavailable: {market_id}")
        book = replay(params.journal)
        if book.status != "open":
            iterations.append(iteration)
            return _report(book, "halted", cycles), iterations
        for market_id in tuple(book.positions):
            try:
                evaluate_exits(
                    params.journal,
                    (market_id,),
                    now=now(),
                    fetch=fetch,
                    paper_fee_rate=config.venue.paper_fee_rate,
                    paper_fee_source=config.venue.paper_fee_source,
                )
            except Exception:
                errors.append(f"exit quote unavailable: {market_id}")
        book = replay(params.journal)
        try:
            candidates = discover_markets(limit=20, now=now(), fetch=fetch)
        except Exception:
            errors.append("discovery unavailable")
            candidates = ()
        admitted_markets = {
            str(record.get("market_id")) for record in book.admitted_turns.values()
        }
        selected = next(
            (
                item
                for item in candidates
                if item.market_id not in book.positions
                and item.market_id not in admitted_markets
            ),
            None,
        )
        if selected is None:
            iteration["status"] = "idle"
            iterations.append(iteration)
            await sleep(params.interval_seconds)
            continue
        try:
            snapshot = load_market_snapshot(
                selected.capture,
                book.bankroll,
                0,
                book.open_exposure,
                include_no_book=True,
                now=now(),
                fetch=fetch,
                paper_fee_rate=config.venue.paper_fee_rate,
                paper_fee_source=config.venue.paper_fee_source,
            )
        except Exception:
            errors.append(f"capture unavailable: {selected.market_id}")
            iteration["status"] = "failed"
            iterations.append(iteration)
            await sleep(params.interval_seconds)
            continue
        try:
            result = await run_journal_turn(params.journal, config, snapshot, operating)
            iteration["result"] = result
        except Exception:
            iteration["status"] = "failed"
        cycles = len(replay(params.journal).admitted_turns)
        iterations.append(iteration)
        await sleep(params.interval_seconds)
