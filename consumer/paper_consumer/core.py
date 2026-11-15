from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Protocol

from jsonschema import Draft202012Validator, FormatChecker

MAX_OUTCOME_EVENTS_PER_FLUSH = 5


class InvalidEvent(ValueError):
    pass


class TransientFailure(RuntimeError):
    pass


class QuoteFailure(TransientFailure):
    """One position's venue quote is unreadable; retry that position later."""


@dataclass(frozen=True)
class Config:
    journal: Path
    bankroll: float = 1_000
    maximum_stake: float = 10
    maximum_market_exposure: float = 0.01
    maximum_total_exposure: float = 0.10
    minimum_edge: float = 0.05
    fee_rate: float = 0.02
    maximum_loss: float = 100

    def __post_init__(self) -> None:
        values = (
            self.bankroll,
            self.maximum_stake,
            self.maximum_market_exposure,
            self.maximum_total_exposure,
            self.minimum_edge,
            self.fee_rate,
            self.maximum_loss,
        )
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in values
        ):
            raise ValueError("consumer limits must be numeric")
        if not (
            self.bankroll > 0
            and 0 < self.maximum_stake <= self.bankroll
            and 0 < self.maximum_market_exposure <= self.maximum_total_exposure <= 1
            and 0 < self.minimum_edge < 1
            and 0 <= self.fee_rate < 1
            and 0 < self.maximum_loss <= self.bankroll
        ):
            raise ValueError("consumer limits are invalid")


@dataclass(frozen=True)
class Quote:
    snapshot_id: str
    market_id: str
    token_id: str
    market_end: str
    captured_at: str
    asks: tuple[tuple[float, float], ...]
    bids: tuple[tuple[float, float], ...]
    resolution: str | None = None
    outcome: str = "YES"


class Market(Protocol):
    def load(self, market_id: str, token_id: str, now: datetime) -> Quote: ...


class Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[object]: ...


class OutcomePublisher(Protocol):
    def publish(self, event: dict[str, object]) -> None: ...


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise InvalidEvent("invalid timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidEvent("invalid timestamp") from None
    if result.tzinfo is None:
        raise InvalidEvent("timestamp requires an offset")
    return result.astimezone(timezone.utc)


def _safe_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 500
        and not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _schema_path() -> Path:
    configured = os.environ.get("TRADE_PLAN_SCHEMA")
    if configured:
        return Path(configured)
    return Path(__file__).parents[2] / "contracts" / "trade_plan_ready.v1.schema.json"


@lru_cache(maxsize=1)
def _outcome_validator() -> Validator:
    configured = os.environ.get("CONSUMER_OUTCOME_SCHEMA")
    path = (
        Path(configured)
        if configured
        else Path(__file__).parents[2] / "contracts" / "consumer_outcome.v1.schema.json"
    )
    try:
        schema = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("consumer outcome schema is unavailable") from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _consumer_outcome(record: dict[str, object]) -> dict[str, object] | None:
    status = record.get("status")
    trade_plan_event_id = record.get("event_id")
    if (
        status not in {"rejected", "filled", "closed", "settled"}
        or not isinstance(trade_plan_event_id, str)
        or re.fullmatch(r"turn-[0-9a-f]{24}", trade_plan_event_id) is None
    ):
        return None
    recorded_at = record.get("recorded_at")
    identity = json.dumps(
        [trade_plan_event_id, status, recorded_at], separators=(",", ":")
    )
    event: dict[str, object] = {
        "schema_version": 1,
        "record_type": "consumer_outcome",
        "event_id": "consumer-outcome-" + sha256(identity.encode()).hexdigest()[:24],
        "trade_plan_event_id": trade_plan_event_id,
        "market_id": record.get("market_id"),
        "status": status,
        "recorded_at": recorded_at,
    }
    if status == "rejected":
        event["reason"] = record.get("reason")
    elif status == "filled":
        event.update(
            token_id=record.get("token_id"),
            quote_snapshot_id=record.get("quote_snapshot_id"),
            price=record.get("price"),
            stake=record.get("stake"),
            fee=record.get("fee"),
            total_cost=record.get("total_cost"),
            shares=record.get("shares"),
        )
    elif status == "closed":
        event.update(
            quote_snapshot_id=record.get("quote_snapshot_id"),
            proceeds=record.get("proceeds"),
            pnl=record.get("pnl"),
            price=record.get("price"),
            fee=record.get("fee"),
        )
    else:
        event.update(
            quote_snapshot_id=record.get("quote_snapshot_id"),
            proceeds=record.get("proceeds"),
            pnl=record.get("pnl"),
            resolution=record.get("resolution"),
        )
    if list(_outcome_validator().iter_errors(event)):
        raise ValueError("invalid consumer outcome event")
    return event


def load_validator() -> Validator:
    try:
        path = _schema_path()
        schema = json.loads(path.read_text())
        v2_path = path.with_name("trade_plan_ready.v2.schema.json")
        if v2_path.exists():
            schema = {"anyOf": [schema, json.loads(v2_path.read_text())]}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("trade plan schema is unavailable") from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def replay(self) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
        terminal: dict[str, dict[str, object]] = {}
        open_positions: dict[str, dict[str, object]] = {}
        try:
            for record in self.records():
                if record["record_type"] == "consumer_outcome_ack":
                    continue
                event_id = record["event_id"]
                assert isinstance(event_id, str)
                previous = terminal.get(event_id)
                if (previous is None and record["status"] in {"closed", "settled"}) or (
                    previous is not None
                    and not (
                        previous["status"] == "filled"
                        and record["status"] in {"closed", "settled"}
                    )
                ):
                    raise ValueError
                if previous is not None and (
                    record["market_id"] != previous["market_id"]
                    or abs(
                        Decimal(str(record["pnl"]))
                        - (
                            Decimal(str(record["proceeds"]))
                            - Decimal(str(previous["total_cost"]))
                        )
                    )
                    > Decimal("1e-9")
                ):
                    raise ValueError
                terminal[event_id] = record
                if record.get("status") == "filled":
                    open_positions[event_id] = record
                elif record.get("status") in {"closed", "settled"}:
                    open_positions.pop(event_id, None)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise TransientFailure("consumer journal is corrupt or unavailable") from exc
        return terminal, open_positions

    def records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        records: list[dict[str, object]] = []
        try:
            with self.path.open() as stream:
                for line in stream:
                    record = json.loads(
                        line,
                        object_pairs_hook=self._pairs,
                        parse_constant=self._constant,
                    )
                    self._validate(record)
                    assert isinstance(record, dict)
                    records.append(record)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise TransientFailure("consumer journal is corrupt or unavailable") from exc
        return records

    def pending_outcomes(self) -> list[dict[str, object]]:
        records = self.records()
        acknowledged = {
            record["event_id"]
            for record in records
            if record["record_type"] == "consumer_outcome_ack"
        }
        pending: dict[str, dict[str, object]] = {}
        for record in records:
            if record["record_type"] != "consumer_ledger":
                continue
            event = _consumer_outcome(record)
            if event is not None and event["event_id"] not in acknowledged:
                pending[str(event["event_id"])] = event
        return list(pending.values())

    @staticmethod
    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    @staticmethod
    def _constant(_value: str) -> object:
        raise ValueError

    @staticmethod
    def _validate(value: object) -> None:
        if not isinstance(value, dict):
            raise ValueError
        if value.get("record_type") == "consumer_outcome_ack":
            if (
                set(value) != {"schema_version", "record_type", "event_id", "recorded_at"}
                or value.get("schema_version") != 1
                or not isinstance(value.get("event_id"), str)
                or re.fullmatch(r"consumer-outcome-[0-9a-f]{24}", value["event_id"]) is None
            ):
                raise ValueError
            _timestamp(value.get("recorded_at"))
            return
        status = value.get("status")
        common = {"schema_version", "record_type", "event_id", "status", "recorded_at"}
        fields = {
            "rejected": common | {"reason"},
            "filled": common
            | {
                "market_id",
                "token_id",
                "market_end",
                "plan_snapshot_id",
                "quote_snapshot_id",
                "price",
                "stake",
                "fee",
                "total_cost",
                "shares",
                "exit_plan",
            },
            "closed": common
            | {"market_id", "quote_snapshot_id", "proceeds", "pnl", "price", "fee"},
            "settled": common
            | {"market_id", "quote_snapshot_id", "proceeds", "pnl", "resolution"},
        }
        if (
            value.get("schema_version") != 1
            or value.get("record_type") != "consumer_ledger"
            or status not in fields
            or frozenset(value) not in {
                frozenset(fields[status]),
                frozenset(fields[status] | {"market_id"}),
            }
            or not isinstance(value.get("event_id"), str)
            or not value["event_id"]
        ):
            raise ValueError
        _timestamp(value.get("recorded_at"))
        string_fields = fields[status] - common - {
            "price",
            "stake",
            "fee",
            "total_cost",
            "shares",
            "proceeds",
            "pnl",
            "exit_plan",
        }
        if not all(isinstance(value.get(field), str) and value[field] for field in string_fields):
            raise ValueError
        if "market_id" in value and not _safe_id(value["market_id"]):
            raise ValueError
        if status == "rejected" and (
            len(value["reason"]) > 500
            or any(ord(character) < 32 or ord(character) == 127 for character in value["reason"])
        ):
            raise ValueError
        number_fields = fields[status] & {
            "price",
            "stake",
            "fee",
            "total_cost",
            "shares",
            "proceeds",
            "pnl",
        }
        if not all(
            isinstance(value.get(field), (int, float))
            and not isinstance(value[field], bool)
            and math.isfinite(value[field])
            for field in number_fields
        ):
            raise ValueError
        if status == "filled":
            _timestamp(value["market_end"])
            plan = value["exit_plan"]
            if not isinstance(plan, dict) or set(plan) != {
                "take_profit_roi",
                "stop_loss_roi",
                "exit_by",
                "hold_to_resolution",
            }:
                raise ValueError
            take_profit = plan["take_profit_roi"]
            stop_loss = plan["stop_loss_roi"]
            exit_by = plan["exit_by"]
            if (
                not isinstance(take_profit, (int, float))
                or isinstance(take_profit, bool)
                or not math.isfinite(take_profit)
                or take_profit <= 0
                or not (
                    stop_loss is None
                    or (
                        isinstance(stop_loss, (int, float))
                        and not isinstance(stop_loss, bool)
                        and math.isfinite(stop_loss)
                        and -1 <= stop_loss < 0
                    )
                )
                or not isinstance(plan["hold_to_resolution"], bool)
                or not (exit_by is None or isinstance(exit_by, str))
            ):
                raise ValueError
            if exit_by is not None:
                _timestamp(exit_by)
        if status == "settled" and value["resolution"] not in {"YES", "NO"}:
            raise ValueError

    def append(self, record: dict[str, object]) -> None:
        record = {"schema_version": 1, "record_type": "consumer_ledger", **record}
        self._validate(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            with self.path.open("a") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise TransientFailure("consumer journal write failed") from exc

    def acknowledge_outcome(self, event_id: str, now: datetime) -> None:
        record = {
            "schema_version": 1,
            "record_type": "consumer_outcome_ack",
            "event_id": event_id,
            "recorded_at": now.astimezone(timezone.utc).isoformat(),
        }
        self._validate(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            with self.path.open("a") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise TransientFailure("consumer outcome acknowledgement failed") from exc


class Consumer:
    def __init__(
        self,
        config: Config,
        market: Market,
        validator: Validator,
        publisher: OutcomePublisher | None = None,
    ) -> None:
        self.config = config
        self.market = market
        self.validator = validator
        self.publisher = publisher
        self.journal = Journal(config.journal)
        self.lock = Lock()

    def flush_outbox(self, now: datetime) -> None:
        if self.publisher is None:
            return
        for event in self.journal.pending_outcomes()[:MAX_OUTCOME_EVENTS_PER_FLUSH]:
            try:
                self.publisher.publish(event)
                self.journal.acknowledge_outcome(str(event["event_id"]), now)
            except Exception as exc:
                raise TransientFailure("consumer outcome delivery failed") from exc

    def consume(self, event: object, now: datetime) -> None:
        with self.lock:
            self.flush_outbox(now)
            terminal, positions = self.journal.replay()
            event_id = event.get("event_id") if isinstance(event, dict) else None
            if isinstance(event_id, str) and event_id in terminal:
                return
            try:
                self._validate_event(event, now)
            except InvalidEvent as exc:
                market_id = event.get("market_id") if isinstance(event, dict) else None
                self._reject(event_id, str(exc), now, market_id)
                self.flush_outbox(now)
                return
            assert isinstance(event, dict) and isinstance(event_id, str)
            realized_pnl = sum(
                Decimal(str(record["pnl"]))
                for record in terminal.values()
                if record["status"] in {"closed", "settled"}
            )
            if realized_pnl <= -Decimal(str(self.config.maximum_loss)):
                self._reject(event_id, "maximum cumulative loss reached", now, event["market_id"])
                self.flush_outbox(now)
                return
            if any(position["market_id"] == event["market_id"] for position in positions.values()):
                self._reject(event_id, "market already has an open position", now, event["market_id"])
                self.flush_outbox(now)
                return
            try:
                quote = self.market.load(str(event["market_id"]), str(event["instrument_id"]), now)
            except InvalidEvent as exc:
                self._reject(event_id, str(exc), now, event["market_id"])
                self.flush_outbox(now)
                return
            except Exception as exc:
                raise TransientFailure("public quote unavailable") from exc
            try:
                fill = self._entry(event, quote, positions, now)
            except InvalidEvent as exc:
                self._reject(event_id, str(exc), now, event["market_id"])
                self.flush_outbox(now)
                return
            self.journal.append(fill)
            self.flush_outbox(now)

    def _validate_event(self, event: object, now: datetime) -> None:
        errors = list(self.validator.iter_errors(event))
        if errors or not isinstance(event, dict):
            raise InvalidEvent("invalid trade plan event")
        identity = json.dumps(
            [event["snapshot_id"], event["market_id"]], separators=(",", ":")
        )
        if event["event_id"] != "turn-" + sha256(identity.encode()).hexdigest()[:24]:
            raise InvalidEvent("trade plan event ID does not match")
        created = _timestamp(event["created_at"])
        expires = _timestamp(event["expires_at"])
        market_end = _timestamp(event["market_end"])
        if now >= expires or now >= market_end:
            raise InvalidEvent("trade plan is expired")
        if not created < expires or expires != market_end:
            raise InvalidEvent("trade plan terms are unsupported")
        citations = event["reviewer_citations"]
        evidence = event["evidence_references"]
        if (
            not isinstance(citations, list)
            or not isinstance(evidence, list)
            or not set(citations) <= set(evidence)
        ):
            raise InvalidEvent("trade plan evidence is unsupported")
        plan = event["exit_plan"]
        assert isinstance(plan, dict)
        exit_by = plan["exit_by"]
        if exit_by is not None and not now < _timestamp(exit_by) < market_end:
            raise InvalidEvent("trade plan exit timing is invalid")
        if plan["stop_loss_roi"] is None and plan["hold_to_resolution"] is not True:
            raise InvalidEvent("trade plan exit policy is invalid")
        if exit_by is None and plan["hold_to_resolution"] is not True:
            raise InvalidEvent("trade plan exit policy is invalid")

    def _reject(
        self, event_id: object, reason: str, now: datetime, market_id: object = None
    ) -> None:
        if not isinstance(event_id, str) or not event_id:
            event_id = "invalid-" + now.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        self.journal.append(
            {
                "event_id": event_id,
                "recorded_at": now.astimezone(timezone.utc).isoformat(),
                "status": "rejected",
                "reason": reason,
                **({"market_id": market_id} if _safe_id(market_id) else {}),
            }
        )

    def _entry(
        self,
        event: dict[str, object],
        quote: Quote,
        positions: dict[str, dict[str, object]],
        now: datetime,
    ) -> dict[str, object]:
        if (
            now - _timestamp(quote.captured_at) > timedelta(minutes=5)
            or _timestamp(quote.captured_at) > now + timedelta(seconds=5)
        ):
            raise InvalidEvent("fresh quote is stale or future-dated")
        if (quote.market_id, quote.token_id, _timestamp(quote.market_end)) != (
            event["market_id"],
            event["instrument_id"],
            _timestamp(event["market_end"]),
        ):
            raise InvalidEvent("fresh quote identity does not match the plan")
        if quote.outcome != event["outcome"]:
            raise InvalidEvent("fresh quote outcome does not match the plan")
        asks = self._book(quote.asks, required=True)
        bids = self._book(quote.bids, required=False, reverse=True)
        if bids and bids[0][0] >= asks[0][0]:
            raise InvalidEvent("fresh quote book is crossed")
        stake = Decimal(str(event["stake"]))
        fee = stake * Decimal(str(self.config.fee_rate))
        total_cost = stake + fee
        exposure = sum(Decimal(str(position["total_cost"])) for position in positions.values())
        market_exposure = sum(
            Decimal(str(position["total_cost"]))
            for position in positions.values()
            if position["market_id"] == event["market_id"]
        )
        if stake > Decimal(str(self.config.maximum_stake)):
            raise InvalidEvent("maximum stake exceeded")
        if market_exposure + total_cost > Decimal(
            str(self.config.bankroll * self.config.maximum_market_exposure)
        ):
            raise InvalidEvent("per-market exposure limit exceeded")
        if exposure + total_cost > Decimal(
            str(self.config.bankroll * self.config.maximum_total_exposure)
        ):
            raise InvalidEvent("total exposure limit exceeded")
        shares, price = self._buy(stake, asks, Decimal(str(event["max_entry_price"])))
        if Decimal(str(event["probability"])) - price < Decimal(str(self.config.minimum_edge)):
            raise InvalidEvent("minimum edge not met")
        return {
            "event_id": event["event_id"],
            "status": "filled",
            "recorded_at": now.astimezone(timezone.utc).isoformat(),
            "market_id": event["market_id"],
            "token_id": event["instrument_id"],
            "market_end": event["market_end"],
            "plan_snapshot_id": event["snapshot_id"],
            "quote_snapshot_id": quote.snapshot_id,
            "price": float(price),
            "stake": float(stake),
            "fee": float(fee),
            "total_cost": float(total_cost),
            "shares": float(shares),
            "exit_plan": event["exit_plan"],
        }

    @staticmethod
    def _book(
        levels: object, *, required: bool, reverse: bool = False
    ) -> tuple[tuple[Decimal, Decimal], ...]:
        if not isinstance(levels, tuple) or (required and not levels) or len(levels) > 50:
            raise InvalidEvent("quote book is malformed")
        parsed: list[tuple[Decimal, Decimal]] = []
        try:
            for level in levels:
                if not isinstance(level, tuple) or len(level) != 2:
                    raise ValueError
                price, size = Decimal(str(level[0])), Decimal(str(level[1]))
                if (
                    not Decimal(0) < price < Decimal(1)
                    or size <= 0
                    or not price.is_finite()
                    or not size.is_finite()
                ):
                    raise ValueError
                parsed.append((price, size))
        except (ValueError, TypeError, ArithmeticError):
            raise InvalidEvent("quote book is malformed") from None
        expected = sorted(parsed, key=lambda level: level[0], reverse=reverse)
        if parsed != expected:
            raise InvalidEvent("quote book is malformed")
        return tuple(parsed)

    @staticmethod
    def _buy(
        stake: Decimal, asks: tuple[tuple[Decimal, Decimal], ...], limit: Decimal
    ) -> tuple[Decimal, Decimal]:
        remaining, shares = stake, Decimal(0)
        for price, size in asks:
            if price > limit:
                break
            spent = min(remaining, price * size)
            shares += spent / price
            remaining -= spent
            if remaining == 0:
                return shares, stake / shares
        raise InvalidEvent("insufficient executable ask depth or maximum entry exceeded")

    def sweep(self, now: datetime) -> None:
        with self.lock:
            self.flush_outbox(now)
            _terminal, positions = self.journal.replay()
            for event_id, position in tuple(positions.items()):
                try:
                    self._sweep_position(event_id, position, now)
                except QuoteFailure as exc:
                    # One position's unreadable venue data must not fail the
                    # whole sweep or block the positions behind it.
                    print(
                        json.dumps(
                            {
                                "severity": "ERROR",
                                "message": f"sweep deferred {event_id}: {exc}: {exc.__cause__}",
                            }
                        ),
                        flush=True,
                    )
            self.flush_outbox(now)

    def _sweep_position(
        self, event_id: str, position: dict[str, object], now: datetime
    ) -> None:
        try:
            quote = self.market.load(
                str(position["market_id"]), str(position["token_id"]), now
            )
        except Exception as exc:
            raise QuoteFailure("public quote unavailable") from exc
        try:
            if (quote.market_id, quote.token_id) != (
                position["market_id"],
                position["token_id"],
            ):
                raise InvalidEvent("exit quote identity does not match")
            if (
                now - _timestamp(quote.captured_at) > timedelta(minutes=5)
                or _timestamp(quote.captured_at) > now
            ):
                raise InvalidEvent("exit quote is stale or future-dated")
            if quote.resolution in {"YES", "NO"}:
                proceeds = (
                    Decimal(str(position["shares"]))
                    if quote.resolution == "YES"
                    else Decimal(0)
                )
                self.journal.append(
                    self._outcome(event_id, position, quote, now, "settled", proceeds)
                )
                return
            if _timestamp(quote.market_end) != _timestamp(position["market_end"]):
                # Polymarket can reschedule a match; the announced end
                # date is event metadata, not the instrument identity.
                # Hold for resolution instead of failing the sweep.
                return
            bids = self._book(quote.bids, required=False, reverse=True)
            asks = self._book(quote.asks, required=True)
            if bids and bids[0][0] >= asks[0][0]:
                raise InvalidEvent("exit quote book is crossed")
        except InvalidEvent as exc:
            raise QuoteFailure("public exit quote is invalid") from exc
        result = self._sell(Decimal(str(position["shares"])), bids)
        if result is None:
            return
        gross, price = result
        net = gross * (Decimal(1) - Decimal(str(self.config.fee_rate)))
        roi = net / Decimal(str(position["total_cost"])) - Decimal(1)
        plan = position["exit_plan"]
        assert isinstance(plan, dict)
        stop = plan["stop_loss_roi"]
        due = plan["exit_by"] is not None and now >= _timestamp(plan["exit_by"])
        if (
            roi >= Decimal(str(plan["take_profit_roi"]))
            or (stop is not None and roi <= Decimal(str(stop)))
            or due
        ):
            record = self._outcome(event_id, position, quote, now, "closed", net)
            record["price"] = float(price)
            record["fee"] = float(gross - net)
            self.journal.append(record)

    @staticmethod
    def _sell(
        shares: Decimal, bids: tuple[tuple[Decimal, Decimal], ...]
    ) -> tuple[Decimal, Decimal] | None:
        remaining, gross = shares, Decimal(0)
        for price, size in bids:
            filled = min(remaining, size)
            gross += filled * price
            remaining -= filled
            if remaining == 0:
                return gross, gross / shares
        return None

    @staticmethod
    def _outcome(
        event_id: str,
        position: dict[str, object],
        quote: Quote,
        now: datetime,
        status: str,
        proceeds: Decimal,
    ) -> dict[str, object]:
        return {
            "event_id": event_id,
            "status": status,
            "recorded_at": now.astimezone(timezone.utc).isoformat(),
            "market_id": position["market_id"],
            "quote_snapshot_id": quote.snapshot_id,
            "proceeds": float(proceeds),
            "pnl": float(proceeds - Decimal(str(position["total_cost"]))),
            **({"resolution": quote.resolution} if quote.resolution else {}),
        }
