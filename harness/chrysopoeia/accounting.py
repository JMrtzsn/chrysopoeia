"""Durable local paper-accounting: append journal, derived book, settlement.

The journal (JSON Lines, one record per line, in an operator-chosen directory)
is the only durable truth; the book is derived by replaying it. Agents never
read or mutate the journal; only these deterministic functions do. Turn
admission is idempotent, so a repeated or recovered turn cannot create a second
position.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

SCHEMA_VERSION = 1
JOURNAL_NAME = "chrysopoeia.jsonl"
EVENT_TYPES = {
    "session_opened",
    "turn_admitted",
    "fill_recorded",
    "mark_recorded",
    "settled",
    "session_halted",
    "session_closed",
}
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
    # ponytail: single O_APPEND write; add rename journaling only if multi-host matters
    descriptor = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)
    return record


def _fail_corrupt(journal: Path, line: int) -> None:
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

    @property
    def fee_rate(self) -> float:
        if self.amount <= 0:
            raise JournalError("position has a non-positive amount")
        return self.fee / self.amount


@dataclass
class Book:
    bankroll: float = 0.0
    maximum_loss: float = 0.0
    realized_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    admitted_turns: dict[str, dict] = field(default_factory=dict)
    status: str = "empty"

    @property
    def open_exposure(self) -> float:
        return sum(position.total_cost for position in self.positions.values())

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            position.shares * self.marks.get(position.market_id, position.price)
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
            book.status = "open"
        elif kind == "turn_admitted":
            turn_id = record.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id.strip():
                _fail_corrupt(journal, number)
            if turn_id in book.admitted_turns:
                _fail_corrupt(journal, number)
            book.admitted_turns[turn_id] = record
        elif kind == "fill_recorded":
            try:
                position = _position_from_record(record)
            except (JournalError, KeyError, TypeError):
                _fail_corrupt(journal, number)
                raise
            if book.status != "open" or position.market_id in book.positions:
                _fail_corrupt(journal, number)
            book.positions[position.market_id] = position
        elif kind == "mark_recorded":
            market_id = record.get("market_id")
            mark = record.get("mark_price")
            if not isinstance(market_id, str) or market_id not in book.positions:
                _fail_corrupt(journal, number)
            if not _fraction(mark):
                _fail_corrupt(journal, number)
            book.marks[market_id] = float(mark)
        elif kind == "settled":
            try:
                market_id, _resolution, pnl = _settlement_from_record(record)
            except JournalError:
                _fail_corrupt(journal, number)
                raise
            if market_id not in book.positions or book.status != "open":
                _fail_corrupt(journal, number)
            book.realized_pnl += pnl
            del book.positions[market_id]
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
    position = Position(
        market_id=record["market_id"],
        snapshot_id=record["snapshot_id"],
        entered_at=record["recorded_at"],
        price=float(record["price"]),
        amount=float(record["amount"]),
        shares=float(record["shares"]),
        fee=float(record["fee"]),
        total_cost=float(record["total_cost"]),
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


def open_session(directory: Path, bankroll: float, maximum_loss: float) -> Book:
    """Start a new session in a fresh journal, or resume the only open one."""
    if (
        not _positive(bankroll)
        or not _positive(maximum_loss)
        or maximum_loss > bankroll
    ):
        raise ValueError(
            "bankroll and maximum_loss must be positive and loss no greater than bankroll"
        )
    book = replay(directory)
    if book.status == "empty":
        append_record(
            directory,
            "session_opened",
            {"bankroll": bankroll, "maximum_loss": maximum_loss},
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


def record_fill(directory: Path, book: Book, position: Position) -> dict:
    """Persist one accepted paper fill as an open position."""
    if book.status != "open":
        raise JournalError(f"session status {book.status} admits no further fills")
    if position.market_id in book.positions:
        raise JournalError(f"market {position.market_id} already has an open position")
    return append_record(
        directory,
        "fill_recorded",
        {
            "market_id": position.market_id,
            "snapshot_id": position.snapshot_id,
            "price": position.price,
            "amount": position.amount,
            "shares": position.shares,
            "fee": position.fee,
            "total_cost": position.total_cost,
        },
    )


def record_mark(directory: Path, book: Book, market_id: str, mark_price: float) -> dict:
    """Record a venue-captured mark for one open position."""
    if market_id not in book.positions:
        raise JournalError(f"no open position for market {market_id}")
    if not _fraction(mark_price):
        raise ValueError("mark_price must be a fraction between 0 and 1")
    return append_record(
        directory,
        "mark_recorded",
        {"market_id": market_id, "mark_price": mark_price},
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
