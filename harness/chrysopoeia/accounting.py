"""Durable local paper-accounting: append journal, derived book, settlement.

The journal (JSON Lines, one record per line, in an operator-chosen directory)
is the only durable truth; the book is derived by replaying it. Agents never
read or mutate the journal; only these deterministic functions do. Turn
admission is idempotent, so a repeated or recovered turn cannot create a second
position.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import NoReturn

from chrysopoeia.trading import ExitPlan, TradePlanReady, parse_trade_plan

SCHEMA_VERSION = 1
JOURNAL_NAME = "chrysopoeia.jsonl"
EVENT_TYPES = {
    "session_opened",
    "turn_admitted",
    "turn_finished",
    "fill_recorded",
    "mark_recorded",
    "settled",
    "position_closed",
    "session_halted",
    "session_closed",
}
TURN_OUTCOMES = {"filled", "abstained", "rejected", "failed", "abandoned"}
RESOLUTIONS = {"resolved_yes", "resolved_no"}
OPEN_STATES = {"open"}
HALTED_STATE = "halted_on_loss"


class JournalError(Exception):
    """Raised when the journal is corrupt, ambiguous, or misused."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or not value.isascii():
        raise ValueError(f"{name} must be a non-empty ASCII identifier")


def journal_path(directory: Path) -> Path:
    return Path(directory) / JOURNAL_NAME


def append_record(directory: Path, record_type: str, payload: dict) -> dict:
    """Append one JSON record atomically and return it."""
    if record_type not in EVENT_TYPES:
        raise ValueError(f"unknown record type {record_type}")
    record = {
        "schema_version": SCHEMA_VERSION,
        "record_type": record_type,
        "recorded_at": _now(),
        **payload,
    }
    line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    journal = journal_path(directory)
    journal.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.write(descriptor, line) != len(line):
            raise JournalError(f"cannot append complete record to journal {journal}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return record


def _fail_corrupt(journal: Path, line: int) -> NoReturn:
    raise JournalError(
        f"corrupt journal {journal} near line {line}; operator must stop or skip"
    )


def _records(journal: Path) -> list[tuple[int, dict]]:
    try:
        text = journal.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise JournalError(f"cannot read journal {journal}: {exc}") from None
    if text and not text.endswith("\n"):
        _fail_corrupt(journal, len(text.splitlines()))
    records = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            _fail_corrupt(journal, number)
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != SCHEMA_VERSION
            or record.get("record_type") not in EVENT_TYPES
        ):
            _fail_corrupt(journal, number)
        records.append((number, record))
    return records


@dataclass(frozen=True)
class Position:
    market_id: str
    snapshot_id: str
    entered_at: str
    price: float
    amount: float
    shares: float
    fee: float
    total_cost: float
    exit_plan: ExitPlan | None = None
    trade_plan: TradePlanReady | None = None
    quote_snapshot_id: str | None = None

    @property
    def fee_rate(self) -> float:
        if self.amount <= 0:
            raise JournalError("position has a non-positive amount")
        return self.fee / self.amount


@dataclass
class Book:
    bankroll: float = 0.0
    maximum_loss: float = 0.0
    target_win_rate: float | None = None
    window_end: str | None = None
    window_minutes: float | None = None
    realized_pnl: float = 0.0
    settled_trades: int = 0
    closed_trades: int = 0
    winning_trades: int = 0
    model_cost_usd: Decimal = Decimal(0)
    positions: dict[str, Position] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    mark_values: dict[str, float] = field(default_factory=dict)
    admitted_turns: dict[str, dict] = field(default_factory=dict)
    finished_turns: dict[str, str] = field(default_factory=dict)
    filled_turns: set[str] = field(default_factory=set)
    status: str = "empty"

    @property
    def open_exposure(self) -> float:
        return sum(position.total_cost for position in self.positions.values())

    @property
    def open_turns(self) -> dict[str, dict]:
        return {
            turn_id: record
            for turn_id, record in self.admitted_turns.items()
            if turn_id not in self.finished_turns
        }

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            self.mark_values.get(position.market_id, position.total_cost)
            - position.total_cost
            for position in self.positions.values()
        )

    @property
    def bankroll_now(self) -> float:
        return self.bankroll + self.realized_pnl - self.open_exposure

    def cumulative_loss_exceeded(self) -> bool:
        return self.realized_pnl <= -self.maximum_loss


def replay(directory: Path) -> Book:
    """Rebuild the book from the journal; refuse a corrupt record."""
    journal = journal_path(directory)
    records = _records(journal)
    book = Book()
    sessions = 0
    for number, record in records:
        kind = record["record_type"]
        if kind == "session_opened":
            sessions += 1
            if sessions > 1:
                _fail_corrupt(journal, number)
            if not _positive(record.get("bankroll")) or not _positive(
                record.get("maximum_loss")
            ):
                _fail_corrupt(journal, number)
            book.bankroll = float(record["bankroll"])
            book.maximum_loss = float(record["maximum_loss"])
            target = record.get("target_win_rate")
            window = record.get("window_end")
            try:
                parsed_window = (
                    datetime.fromisoformat(window) if isinstance(window, str) else None
                )
            except ValueError:
                parsed_window = None
            if (target is None) != (window is None) or (
                target is not None
                and (
                    not isinstance(target, (int, float))
                    or isinstance(target, bool)
                    or not 0 <= target <= 1
                    or not isinstance(window, str)
                    or not window.strip()
                    or parsed_window is None
                    or parsed_window.tzinfo is None
                )
            ):
                _fail_corrupt(journal, number)
            book.target_win_rate = float(target) if target is not None else None
            book.window_end = window
            duration = record.get("window_minutes")
            if duration is not None and not _positive(duration):
                _fail_corrupt(journal, number)
            book.window_minutes = float(duration) if duration is not None else None
            book.status = "open"
        elif kind == "turn_admitted":
            turn_id = record.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id.strip():
                _fail_corrupt(journal, number)
            if turn_id in book.admitted_turns:
                _fail_corrupt(journal, number)
            book.admitted_turns[turn_id] = record
        elif kind == "fill_recorded":
            turn_id = record.get("turn_id")
            if turn_id is not None and (
                not isinstance(turn_id, str)
                or turn_id not in book.admitted_turns
                or turn_id in book.finished_turns
            ):
                _fail_corrupt(journal, number)
            try:
                position = _position_from_record(record)
            except (JournalError, KeyError, TypeError):
                _fail_corrupt(journal, number)
                raise
            if book.status != "open" or position.market_id in book.positions:
                _fail_corrupt(journal, number)
            book.positions[position.market_id] = position
            book.marks.pop(position.market_id, None)
            book.mark_values.pop(position.market_id, None)
            if turn_id is not None:
                book.filled_turns.add(turn_id)
        elif kind == "turn_finished":
            turn_id = record.get("turn_id")
            outcome = record.get("outcome")
            if (
                not isinstance(turn_id, str)
                or turn_id not in book.admitted_turns
                or turn_id in book.finished_turns
                or outcome not in TURN_OUTCOMES
            ):
                _fail_corrupt(journal, number)
            book.finished_turns[turn_id] = outcome
            try:
                cost = Decimal(str(record.get("model_cost_usd", "0")))
            except InvalidOperation:
                _fail_corrupt(journal, number)
            if not cost.is_finite() or cost < 0:
                _fail_corrupt(journal, number)
            book.model_cost_usd += cost
        elif kind == "mark_recorded":
            market_id = record.get("market_id")
            mark = record.get("mark_price")
            if not isinstance(market_id, str) or market_id not in book.positions:
                _fail_corrupt(journal, number)
            if not _fraction(mark):
                _fail_corrupt(journal, number)
            book.marks[market_id] = float(mark)
            value = record.get("mark_value")
            if value is None:
                book.mark_values[market_id] = book.positions[market_id].shares * float(mark)
            elif (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or value < 0
            ):
                _fail_corrupt(journal, number)
            else:
                book.mark_values[market_id] = float(value)
        elif kind == "settled":
            try:
                market_id, _resolution, pnl = _settlement_from_record(record)
            except JournalError:
                _fail_corrupt(journal, number)
                raise
            if market_id not in book.positions or book.status != "open":
                _fail_corrupt(journal, number)
            book.realized_pnl += pnl
            book.settled_trades += 1
            book.winning_trades += pnl > 0
            del book.positions[market_id]
            book.marks.pop(market_id, None)
            book.mark_values.pop(market_id, None)
        elif kind == "position_closed":
            market_id = record.get("market_id")
            position = book.positions.get(market_id) if isinstance(market_id, str) else None
            reason = record.get("reason")
            proceeds = record.get("gross_proceeds")
            fee = record.get("exit_fee")
            pnl = record.get("realized_pnl")
            shares = record.get("shares")
            price = record.get("price")
            triggered_at = record.get("triggered_at")
            if (
                position is None
                or book.status != "open"
                or position.exit_plan is None
                or not isinstance(reason, str)
                or reason not in {"take_profit", "stop_loss", "time"}
                or not isinstance(proceeds, (int, float))
                or isinstance(proceeds, bool)
                or not isfinite(proceeds)
                or proceeds <= 0
                or not isinstance(fee, (int, float))
                or isinstance(fee, bool)
                or not isfinite(fee)
                or not 0 <= fee <= proceeds
                or not isinstance(pnl, (int, float))
                or isinstance(pnl, bool)
                or not isfinite(pnl)
                or not isinstance(shares, (int, float))
                or isinstance(shares, bool)
                or not isfinite(shares)
                or abs(shares - position.shares) > 1e-9
                or not isinstance(record.get("snapshot_id"), str)
                or not record["snapshot_id"].strip()
                or not isinstance(triggered_at, str)
                or not isinstance(price, (int, float))
                or isinstance(price, bool)
                or not isfinite(price)
                or not 0 < price < 1
                or abs(price * shares - proceeds) > 1e-8
                or abs(pnl - (proceeds - fee - position.total_cost)) > 1e-9
            ):
                _fail_corrupt(journal, number)
            try:
                triggered = datetime.fromisoformat(triggered_at.replace("Z", "+00:00"))
            except ValueError:
                _fail_corrupt(journal, number)
            if triggered.tzinfo is None:
                _fail_corrupt(journal, number)
            roi = (proceeds - fee - position.total_cost) / position.total_cost
            plan = position.exit_plan
            valid_trigger = (
                (reason == "take_profit" and roi >= plan.take_profit_roi)
                or (reason == "stop_loss" and plan.stop_loss_roi is not None and roi <= plan.stop_loss_roi)
                or (
                    reason == "time"
                    and plan.exit_by is not None
                    and triggered >= datetime.fromisoformat(plan.exit_by.replace("Z", "+00:00"))
                )
            )
            if not valid_trigger:
                _fail_corrupt(journal, number)
            book.realized_pnl += float(pnl)
            book.closed_trades += 1
            book.winning_trades += pnl > 0
            del book.positions[market_id]
            book.marks.pop(market_id, None)
            book.mark_values.pop(market_id, None)
        elif kind == "session_halted":
            if book.status != "open":
                _fail_corrupt(journal, number)
            book.status = HALTED_STATE
        elif kind == "session_closed":
            if book.status != "open" and book.status != HALTED_STATE:
                _fail_corrupt(journal, number)
            book.status = "closed"
    if sessions == 0:
        book.status = "empty"
    return book


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _fraction(value: object) -> bool:
    return (
        _positive(value)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value < 1
    )


def _position_from_record(record: dict) -> Position:
    raw_plan = record.get("exit_plan")
    if raw_plan is None:
        exit_plan = None
    elif isinstance(raw_plan, dict):
        try:
            exit_plan = ExitPlan(**raw_plan)
        except (TypeError, ValueError):
            raise JournalError("invalid position exit plan") from None
    else:
        raise JournalError("invalid position exit plan")
    raw_trade_plan = record.get("trade_plan")
    try:
        trade_plan = (
            parse_trade_plan(raw_trade_plan)
            if isinstance(raw_trade_plan, dict)
            else None
        )
    except ValueError:
        raise JournalError("invalid position trade plan") from None
    position = Position(
        market_id=record["market_id"],
        snapshot_id=record["snapshot_id"],
        entered_at=record["recorded_at"],
        price=float(record["price"]),
        amount=float(record["amount"]),
        shares=float(record["shares"]),
        fee=float(record["fee"]),
        total_cost=float(record["total_cost"]),
        exit_plan=exit_plan,
        trade_plan=trade_plan,
        quote_snapshot_id=record.get("quote_snapshot_id"),
    )
    for name in ("price", "amount", "shares", "fee", "total_cost"):
        value = getattr(position, name)
        if (
            not isinstance(value, float)
            or value != value
            or value in (float("inf"), float("-inf"))
        ):
            raise JournalError(f"non-finite {name}")
    if position.price <= 0 or position.amount <= 0 or position.shares <= 0:
        raise JournalError("invalid position economics")
    if abs(position.amount + position.fee - position.total_cost) > 1e-9:
        raise JournalError("inconsistent fill totals")
    if position.trade_plan is not None and (
        position.trade_plan.market_id != position.market_id
        or position.trade_plan.snapshot_id != position.snapshot_id
        or position.trade_plan.stake != position.amount
        or position.price > position.trade_plan.max_entry_price
        or position.trade_plan.exit_plan != position.exit_plan
        or (
            isinstance(record.get("turn_id"), str)
            and position.trade_plan.event_id != record["turn_id"]
        )
    ):
        raise JournalError("fill does not match its trade plan")
    if position.quote_snapshot_id is not None and (
        not isinstance(position.quote_snapshot_id, str)
        or not position.quote_snapshot_id.strip()
    ):
        raise JournalError("invalid quote snapshot identity")
    return position


def _settlement_from_record(record: dict) -> tuple[str, str, float]:
    market_id = record.get("market_id")
    resolution = record.get("resolution")
    pnl = record.get("realized_pnl")
    if not isinstance(market_id, str) or not market_id.strip():
        raise JournalError("settlement market_id missing")
    if resolution not in RESOLUTIONS:
        raise JournalError("settlement resolution must be resolved_yes or resolved_no")
    if not isinstance(pnl, (int, float)) or isinstance(pnl, bool):
        raise JournalError("settlement realized pnl missing")
    return market_id, resolution, float(pnl)


def open_session(
    directory: Path,
    bankroll: float,
    maximum_loss: float,
    *,
    target_win_rate: float | None = None,
    window_end: datetime | None = None,
    window_minutes: float | None = None,
) -> Book:
    """Start a new session in a fresh journal, or resume the only open one."""
    if (
        not _positive(bankroll)
        or not _positive(maximum_loss)
        or maximum_loss > bankroll
    ):
        raise ValueError(
            "bankroll and maximum_loss must be positive and loss no greater than bankroll"
        )
    if (target_win_rate is None) != (window_end is None) or (
        target_win_rate is not None
        and (
            isinstance(target_win_rate, bool)
            or not isinstance(target_win_rate, (int, float))
            or not 0 <= target_win_rate <= 1
            or not isinstance(window_end, datetime)
            or window_end.tzinfo is None
            or (window_minutes is not None and not _positive(window_minutes))
        )
    ):
        raise ValueError("target_win_rate and UTC window_end must be supplied together")
    window_iso = window_end.astimezone(timezone.utc).isoformat() if window_end else None
    book = replay(directory)
    if book.status == "empty":
        append_record(
            directory,
            "session_opened",
            {
                "bankroll": bankroll,
                "maximum_loss": maximum_loss,
                **(
                    {
                        "target_win_rate": target_win_rate,
                        "window_end": window_iso,
                        **(
                            {"window_minutes": window_minutes}
                            if window_minutes is not None
                            else {}
                        ),
                    }
                    if target_win_rate is not None
                    else {}
                ),
            },
        )
        return replay(directory)
    if book.status != "open":
        raise JournalError(
            "cannot start a session in state "
            f"{book.status}; use a new journal directory provided by the operator"
        )
    if (
        abs(book.bankroll - bankroll) > 1e-9
        or abs(book.maximum_loss - maximum_loss) > 1e-9
        or book.target_win_rate != target_win_rate
        or (
            (book.window_minutes is None and book.window_end != window_iso)
            or (
                book.window_minutes is not None
                and book.window_minutes != window_minutes
            )
        )
    ):
        raise JournalError(
            "resumed session configuration differs from the requested configuration"
        )
    return book


def cycle_turn_id(snapshot_id: str, market_id: str) -> str:
    """Return the deterministic turn identity for one snapshot/market pair."""
    _clean(snapshot_id, "snapshot_id")
    _clean(market_id, "market_id")
    identity = json.dumps([snapshot_id, market_id], separators=(",", ":"))
    return "turn-" + sha256(identity.encode()).hexdigest()[:24]


def admit_turn(directory: Path, turn_id: str, snapshot_id: str, market_id: str) -> dict:
    """Record turn admission idempotently; a repeat is a no-op returning the original."""
    _clean(turn_id, "turn_id")
    _clean(snapshot_id, "snapshot_id")
    _clean(market_id, "market_id")
    payload = {"turn_id": turn_id, "snapshot_id": snapshot_id, "market_id": market_id}
    book = replay(directory)
    existing = book.admitted_turns.get(turn_id)
    if existing is not None:
        for key, value in payload.items():
            if existing.get(key) != value:
                raise JournalError(
                    f"turn_id {turn_id} already admitted with a different identity"
                )
        return existing
    if book.status != "open":
        raise JournalError(f"session status {book.status} admits no further turns")
    return append_record(directory, "turn_admitted", payload)


def record_fill(directory: Path, position: Position, turn_id: str) -> dict:
    """Persist one accepted paper fill as an open position."""
    if position.exit_plan is None:
        raise JournalError("a new position requires an approved exit plan")
    book = replay(directory)
    if book.status != "open":
        raise JournalError(f"session status {book.status} admits no further fills")
    if position.market_id in book.positions:
        raise JournalError(f"market {position.market_id} already has an open position")
    _clean(turn_id, "turn_id")
    if turn_id not in book.admitted_turns:
        raise JournalError(f"turn_id {turn_id} was not admitted")
    if turn_id in book.finished_turns:
        raise JournalError(f"turn_id {turn_id} is already finished")
    return append_record(
        directory,
        "fill_recorded",
        {
            "turn_id": turn_id,
            "market_id": position.market_id,
            "snapshot_id": position.snapshot_id,
            "price": position.price,
            "amount": position.amount,
            "shares": position.shares,
            "fee": position.fee,
            "total_cost": position.total_cost,
            **(
                {"exit_plan": asdict(position.exit_plan)}
                if position.exit_plan is not None
                else {}
            ),
            **(
                {"trade_plan": asdict(position.trade_plan)}
                if position.trade_plan is not None
                else {}
            ),
            **(
                {"quote_snapshot_id": position.quote_snapshot_id}
                if position.quote_snapshot_id is not None
                else {}
            ),
        },
    )


def finish_turn(
    directory: Path, turn_id: str, outcome: str, *, model_cost_usd: str = "0"
) -> dict:
    """Record the one terminal outcome for an admitted turn."""
    _clean(turn_id, "turn_id")
    if outcome not in TURN_OUTCOMES:
        raise ValueError(f"unknown turn outcome {outcome}")
    try:
        cost = Decimal(model_cost_usd)
    except InvalidOperation:
        raise ValueError("model_cost_usd must be a non-negative decimal") from None
    if not cost.is_finite() or cost < 0:
        raise ValueError("model_cost_usd must be a non-negative decimal")
    book = replay(directory)
    if turn_id not in book.admitted_turns:
        raise JournalError(f"turn_id {turn_id} was not admitted")
    if turn_id in book.finished_turns:
        raise JournalError(f"turn_id {turn_id} is already finished")
    return append_record(
        directory,
        "turn_finished",
        {"turn_id": turn_id, "outcome": outcome, "model_cost_usd": str(cost)},
    )


def recover_open_turns(directory: Path) -> dict[str, str]:
    """Finish interrupted turns from journal facts without rerunning their work."""
    book = replay(directory)
    recovered = {}
    for turn_id in book.open_turns:
        outcome = "filled" if turn_id in book.filled_turns else "abandoned"
        finish_turn(directory, turn_id, outcome)
        recovered[turn_id] = outcome
    return recovered


def record_mark(
    directory: Path,
    book: Book,
    market_id: str,
    mark_price: float,
    mark_value: float | None = None,
) -> dict:
    """Record a venue-captured mark for one open position."""
    if market_id not in book.positions:
        raise JournalError(f"no open position for market {market_id}")
    if not _fraction(mark_price):
        raise ValueError("mark_price must be a fraction between 0 and 1")
    if mark_value is not None and (
        not isinstance(mark_value, (int, float))
        or isinstance(mark_value, bool)
        or not isfinite(mark_value)
        or mark_value < 0
    ):
        raise ValueError("mark_value must be finite and non-negative")
    return append_record(
        directory,
        "mark_recorded",
        {
            "market_id": market_id,
            "mark_price": mark_price,
            **({"mark_value": mark_value} if mark_value is not None else {}),
        },
    )


def settle(directory: Path, book: Book, market_id: str, resolution: str) -> dict:
    """Realize one open position against a venue-derived canonical resolution."""
    if resolution not in RESOLUTIONS:
        raise ValueError("resolution must be resolved_yes or resolved_no")
    position = book.positions.get(market_id)
    if position is None:
        raise JournalError(f"no open position for market {market_id}")
    if resolution == "resolved_yes":
        pnl = position.shares * (1.0 - position.fee_rate) - position.total_cost
    else:
        pnl = -position.total_cost
    return append_record(
        directory,
        "settled",
        {
            "market_id": market_id,
            "resolution": resolution,
            "realized_pnl": pnl,
            "snapshot_id": position.snapshot_id,
        },
    )


def close_position(
    directory: Path,
    market_id: str,
    reason: str,
    snapshot_id: str,
    price: float,
    gross_proceeds: float,
    exit_fee: float,
    triggered_at: str,
) -> dict:
    """Journal a full paper close at a depth-aware quote."""
    _clean(market_id, "market_id")
    book = replay(directory)
    position = book.positions.get(market_id)
    if position is None or book.status != "open":
        raise JournalError(f"no open position for market {market_id}")
    if position.exit_plan is None:
        raise JournalError(f"position for market {market_id} has no exit plan")
    _clean(snapshot_id, "snapshot_id")
    _clean(triggered_at, "triggered_at")
    if reason not in {"take_profit", "stop_loss", "time"}:
        raise ValueError("unknown position close reason")
    for value, name in ((price, "price"), (gross_proceeds, "gross_proceeds"), (exit_fee, "exit_fee")):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not 0 < price < 1 or gross_proceeds <= 0 or not 0 <= exit_fee <= gross_proceeds:
        raise ValueError("invalid close quote")
    try:
        triggered = datetime.fromisoformat(triggered_at.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("triggered_at must include a UTC offset") from None
    if triggered.tzinfo is None:
        raise ValueError("triggered_at must include a UTC offset")
    roi = (gross_proceeds - exit_fee - position.total_cost) / position.total_cost
    plan = position.exit_plan
    if not (
        (reason == "take_profit" and roi >= plan.take_profit_roi)
        or (reason == "stop_loss" and plan.stop_loss_roi is not None and roi <= plan.stop_loss_roi)
        or (
            reason == "time"
            and plan.exit_by is not None
            and triggered >= datetime.fromisoformat(plan.exit_by.replace("Z", "+00:00"))
        )
    ):
        raise JournalError("close does not match the approved exit plan")
    return append_record(
        directory,
        "position_closed",
        {
            "market_id": market_id,
            "snapshot_id": snapshot_id,
            "reason": reason,
            "triggered_at": triggered_at,
            "price": price,
            "shares": position.shares,
            "gross_proceeds": gross_proceeds,
            "exit_fee": exit_fee,
            "realized_pnl": gross_proceeds - exit_fee - position.total_cost,
        },
    )


def check_halt(directory: Path, book: Book) -> dict | None:
    """Append a halt record once cumulative realized loss crosses the budget."""
    if book.status != "open" or not book.cumulative_loss_exceeded():
        return None
    return append_record(
        directory, "session_halted", {"realized_pnl": book.realized_pnl}
    )


def close_session(directory: Path, book: Book) -> dict:
    """Close the session; only an operator closes a halted session."""
    if book.status == "closed":
        raise JournalError("session already closed")
    if book.status == "empty":
        raise JournalError("no session to close")
    return append_record(directory, "session_closed", {})
