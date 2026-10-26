import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from math import isfinite
from urllib.parse import urlparse

MINIMUM_NET_EDGE = 0.05
MAXIMUM_MARKET_EXPOSURE = 0.01
MAXIMUM_TOTAL_EXPOSURE = 0.10


def validate_polymarket_event_url(value: str) -> str:
    """Return an exact canonical public Polymarket event URL or raise ValueError."""
    if not isinstance(value, str) or not value.isascii():
        raise ValueError("source URL must be a canonical public Polymarket HTTPS event URL")
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        port = -1
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "polymarket.com"
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or len(parts) != 2
        or parts[0] != "event"
        or not re.fullmatch(r"[A-Za-z0-9-]+", parts[1])
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("source URL must be a canonical public Polymarket HTTPS event URL")
    return value


@dataclass(frozen=True)
class OperatingConfig:
    bankroll: float = 1_000
    trader_agents: int = 1
    maximum_market_exposure: float = MAXIMUM_MARKET_EXPOSURE
    maximum_total_exposure: float = MAXIMUM_TOTAL_EXPOSURE
    maximum_loss: float = 100
    daily_cloud_cost_budget: float = 5

    def __post_init__(self) -> None:
        for value, name in (
            (self.bankroll, "bankroll"),
            (self.maximum_market_exposure, "maximum_market_exposure"),
            (self.maximum_total_exposure, "maximum_total_exposure"),
            (self.maximum_loss, "maximum_loss"),
            (self.daily_cloud_cost_budget, "daily_cloud_cost_budget"),
        ):
            _finite(value, name)
        if self.bankroll <= 0:
            raise ValueError("bankroll must be positive")
        if not isinstance(self.trader_agents, int) or isinstance(self.trader_agents, bool) or self.trader_agents <= 0:
            raise ValueError("trader_agents must be a positive integer")
        if not 0 < self.maximum_market_exposure <= self.maximum_total_exposure <= 1:
            raise ValueError("exposure limits must be ordered fractions between 0 and 1")
        if not 0 < self.maximum_loss <= self.bankroll:
            raise ValueError("maximum_loss must be positive and no greater than bankroll")
        if self.daily_cloud_cost_budget < 0:
            raise ValueError("daily_cloud_cost_budget cannot be negative")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _finite(value: float, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float

    def __post_init__(self) -> None:
        _finite(self.price, "book level price")
        _finite(self.size, "book level size")
        if not 0 < self.price < 1 or self.size <= 0:
            raise ValueError("book levels require a price between 0 and 1 and positive size")


def _offset_timestamp(value: str, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be a valid timestamp") from None
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include a UTC offset")
    return timestamp


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    market_id: str
    price: float
    bankroll: float
    market_exposure: float
    total_exposure: float
    question: str = ""
    resolution_rules: str = ""
    end_time: str = ""
    captured_at: str = ""
    source_url: str = ""
    yes_token_id: str = ""
    asks: tuple[BookLevel, ...] = ()
    fee_rate: float = 0
    fee_source: str = "paper-assumption:no-fee-v1"
    book_captured_at: str = ""
    bids: tuple[BookLevel, ...] = ()
    no_token_id: str = ""
    no_asks: tuple[BookLevel, ...] = ()
    no_bids: tuple[BookLevel, ...] = ()
    no_book_captured_at: str = ""

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        _identifier(self.market_id, "market_id")
        for value, name in (
            (self.price, "price"),
            (self.bankroll, "bankroll"),
            (self.market_exposure, "market_exposure"),
            (self.total_exposure, "total_exposure"),
        ):
            _finite(value, name)
        if not 0 < self.price < 1:
            raise ValueError("price must be between 0 and 1")
        if self.bankroll <= 0:
            raise ValueError("bankroll must be positive")
        if self.market_exposure < 0 or self.total_exposure < 0:
            raise ValueError("existing exposures cannot be negative")
        if self.market_exposure > self.total_exposure or self.total_exposure > self.bankroll:
            raise ValueError("existing exposures are inconsistent")
        try:
            levels = tuple(level if isinstance(level, BookLevel) else BookLevel(**level) for level in self.asks)
        except (TypeError, ValueError):
            raise ValueError("asks must contain valid book levels") from None
        object.__setattr__(self, "asks", levels)
        if len(levels) > 50:
            raise ValueError("asks cannot exceed 50 levels")
        if any(left.price > right.price for left, right in zip(levels, levels[1:])):
            raise ValueError("asks must be sorted cheapest first")
        try:
            bids = tuple(level if isinstance(level, BookLevel) else BookLevel(**level) for level in self.bids)
        except (TypeError, ValueError):
            raise ValueError("bids must contain valid book levels") from None
        object.__setattr__(self, "bids", bids)
        if self.no_token_id:
            if self.no_token_id == self.yes_token_id:
                raise ValueError("outcome tokens must be distinct")
            try:
                no_asks = tuple(level if isinstance(level, BookLevel) else BookLevel(**level) for level in self.no_asks)
            except (TypeError, ValueError):
                raise ValueError("NO asks must contain valid book levels") from None
            if not no_asks:
                raise ValueError("NO token requires executable asks")
            no_book = MarketSnapshot(
                self.snapshot_id, self.market_id,
                no_asks[0].price,
                self.bankroll, self.market_exposure, self.total_exposure,
                self.question, self.resolution_rules, self.end_time, self.captured_at,
                self.source_url, self.no_token_id, no_asks, self.fee_rate,
                self.fee_source, self.no_book_captured_at, self.no_bids,
            )
            object.__setattr__(self, "no_asks", no_book.asks)
            object.__setattr__(self, "no_bids", no_book.bids)
        elif self.no_asks or self.no_bids or self.no_book_captured_at:
            raise ValueError("NO book requires a NO token")
        if len(bids) > 50:
            raise ValueError("bids cannot exceed 50 levels")
        if any(left.price < right.price for left, right in zip(bids, bids[1:])):
            raise ValueError("bids must be sorted highest first")
        if bids and levels and bids[0].price >= levels[0].price:
            raise ValueError("market book cannot be crossed")
        _finite(self.fee_rate, "fee_rate")
        if not 0 <= self.fee_rate < 1:
            raise ValueError("fee_rate must be a fraction between 0 and 1")
        _identifier(self.fee_source, "fee_source")
        if self.fee_rate and self.fee_source == "paper-assumption:no-fee-v1":
            raise ValueError("positive fee_rate requires explicit fee provenance")
        rich_values = (
            self.question, self.resolution_rules, self.end_time, self.captured_at,
            self.source_url, self.yes_token_id, self.book_captured_at,
        )
        if levels or any(rich_values):
            for value, name in zip(rich_values, (
                "question", "resolution_rules", "end_time", "captured_at",
                "source_url", "yes_token_id", "book_captured_at",
            )):
                _identifier(value, name)
            if not levels or self.price != levels[0].price:
                raise ValueError("rich snapshot price must equal its cheapest YES ask")
            end = _offset_timestamp(self.end_time, "end_time")
            captured = _offset_timestamp(self.captured_at, "captured_at")
            book_captured = _offset_timestamp(self.book_captured_at, "book_captured_at")
            if end <= captured:
                raise ValueError("end_time must be after captured_at")
            if book_captured > captured:
                raise ValueError("book_captured_at cannot be after captured_at")
            validate_polymarket_event_url(self.source_url)


def market_snapshot_identity(snapshot: MarketSnapshot) -> str:
    """Return the canonical market-data identity, excluding capture and account state."""
    fields = {
            "market_id": snapshot.market_id,
            "price": float(snapshot.price),
            "question": snapshot.question,
            "resolution_rules": snapshot.resolution_rules,
            "end_time": snapshot.end_time,
            "source_url": snapshot.source_url,
            "yes_token_id": snapshot.yes_token_id,
            "asks": [(float(level.price), float(level.size)) for level in snapshot.asks],
            "fee_rate": float(snapshot.fee_rate),
            "fee_source": snapshot.fee_source,
        }
    if snapshot.no_token_id:
        fields.update({
            "no_token_id": snapshot.no_token_id,
            "no_asks": [(float(level.price), float(level.size)) for level in snapshot.no_asks],
        })
    identity = json.dumps(
        fields,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "polymarket-" + sha256(identity.encode()).hexdigest()[:24]


def outcome_snapshot(snapshot: MarketSnapshot, outcome: str) -> MarketSnapshot:
    """Select the actual token book; never synthesize NO liquidity from YES prices."""
    if outcome == "YES":
        return snapshot
    if outcome != "NO" or not snapshot.no_token_id or not snapshot.no_asks:
        raise ValueError("requested outcome book is unavailable")
    return replace(
        snapshot, price=snapshot.no_asks[0].price,
        yes_token_id=snapshot.no_token_id, asks=snapshot.no_asks, bids=snapshot.no_bids,
        book_captured_at=snapshot.no_book_captured_at,
        no_token_id="", no_asks=(), no_bids=(), no_book_captured_at="",
    )


@dataclass(frozen=True)
class ExitPlan:
    take_profit_roi: float
    stop_loss_roi: float | None = None
    exit_by: str | None = None
    hold_to_resolution: bool = False

    def __post_init__(self) -> None:
        _finite(self.take_profit_roi, "take_profit_roi")
        if self.take_profit_roi <= 0:
            raise ValueError("take_profit_roi must be positive")
        if self.stop_loss_roi is not None:
            _finite(self.stop_loss_roi, "stop_loss_roi")
            if not -1 <= self.stop_loss_roi < 0:
                raise ValueError("stop_loss_roi must be between -1 and 0")
        if not isinstance(self.hold_to_resolution, bool):
            raise ValueError("hold_to_resolution must be boolean")
        if self.exit_by is not None:
            _offset_timestamp(self.exit_by, "exit_by")
        if self.stop_loss_roi is None and not self.hold_to_resolution:
            raise ValueError("a stop loss or hold-to-resolution choice is required")
        if self.exit_by is None and not self.hold_to_resolution:
            raise ValueError("exit_by or hold_to_resolution is required")


@dataclass(frozen=True)
class Proposal:
    snapshot_id: str
    market_id: str
    probability: float
    amount: float
    max_entry_price: float | None = None
    exit_plan: ExitPlan | None = None
    citations: tuple[str, ...] = ()
    outcome: str = "YES"

    def __post_init__(self) -> None:
        if self.outcome not in {"YES", "NO"}:
            raise ValueError("proposal outcome must be YES or NO")
        _identifier(self.snapshot_id, "snapshot_id")
        _identifier(self.market_id, "market_id")
        _finite(self.probability, "probability")
        _finite(self.amount, "amount")
        if not 0 <= self.probability <= 1:
            raise ValueError("probability must be between 0 and 1")
        if self.amount <= 0:
            raise ValueError("proposal amount must be positive")
        if self.max_entry_price is not None:
            _finite(self.max_entry_price, "max_entry_price")
            if not 0 < self.max_entry_price < 1:
                raise ValueError("max_entry_price must be between 0 and 1")
        if self.exit_plan is not None and not isinstance(self.exit_plan, ExitPlan):
            raise ValueError("exit_plan must be a validated ExitPlan")
        if any(not isinstance(value, str) or not value.strip() for value in self.citations):
            raise ValueError("proposal citations must be non-empty strings")


@dataclass(frozen=True)
class Review:
    snapshot_id: str
    market_id: str
    approved: bool
    reason: str
    citations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        _identifier(self.market_id, "market_id")
        if not isinstance(self.approved, bool):
            raise ValueError("review approval must be boolean")
        _identifier(self.reason, "review reason")
        if any(not isinstance(value, str) or not value.strip() for value in self.citations):
            raise ValueError("review citations must be non-empty strings")


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class SimulatedFill:
    snapshot_id: str
    market_id: str
    price: float
    amount: float
    shares: float = 0
    fee: float = 0
    total_cost: float = 0
    levels_consumed: int = 1


@dataclass(frozen=True)
class TradePlanReady:
    schema_version: int
    record_type: str
    event_id: str
    created_at: str
    market_id: str
    snapshot_id: str
    instrument_id: str
    outcome: str
    probability: float
    stake: float
    max_entry_price: float
    exit_plan: ExitPlan
    reviewer_approved: bool
    reviewer_citations: tuple[str, ...]
    policy_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    expires_at: str
    market_end: str


@dataclass(frozen=True)
class ExitQuote:
    price: float
    shares: float
    gross_proceeds: float
    fee: float
    net_proceeds: float
    levels_consumed: int


@dataclass(frozen=True)
class CycleReport:
    decision: RiskDecision
    fill: SimulatedFill | None
    summary: str
    event: TradePlanReady | None = None


def _trade_plan_ready(
    snapshot: MarketSnapshot, proposal: Proposal, review: Review
) -> TradePlanReady:
    if (
        proposal.max_entry_price is None
        or proposal.exit_plan is None
        or not snapshot.captured_at
        or not snapshot.end_time
        or not snapshot.yes_token_id
    ):
        raise ValueError("complete event terms are required")
    created = _offset_timestamp(snapshot.captured_at, "captured_at")
    event_id = "turn-" + sha256(
        json.dumps(
            [snapshot.snapshot_id, snapshot.market_id], separators=(",", ":")
        ).encode()
    ).hexdigest()[:24]
    evidence = tuple(dict.fromkeys((*proposal.citations, *review.citations)))
    return TradePlanReady(
        2 if proposal.outcome == "NO" else 1,
        "trade_plan_ready",
        event_id,
        created.astimezone(timezone.utc).isoformat(),
        snapshot.market_id,
        snapshot.snapshot_id,
        outcome_snapshot(snapshot, proposal.outcome).yes_token_id,
        proposal.outcome,
        proposal.probability if proposal.outcome == "YES" else 1 - proposal.probability,
        proposal.amount,
        proposal.max_entry_price,
        proposal.exit_plan,
        review.approved,
        review.citations,
        ("hard-policy-v1",),
        evidence,
        snapshot.end_time,
        snapshot.end_time,
    )


def consume_trade_plan(
    event: TradePlanReady, snapshot: MarketSnapshot, operating: OperatingConfig | None = None
) -> SimulatedFill:
    """Validate an accepted plan against a snapshot and independently simulate it."""
    if not isinstance(event, TradePlanReady) or event.schema_version not in {1, 2} or event.record_type != "trade_plan_ready":
        raise ValueError("unsupported trade plan event")
    expected_event_id = "turn-" + sha256(
        json.dumps(
            [snapshot.snapshot_id, snapshot.market_id], separators=(",", ":")
        ).encode()
    ).hexdigest()[:24]
    if event.event_id != expected_event_id:
        raise ValueError("trade plan event identity is inconsistent")
    if event.schema_version == 1 and event.outcome != "YES":
        raise ValueError("v1 supports only YES trade plans")
    if (event.snapshot_id, event.market_id, event.instrument_id) != (
        snapshot.snapshot_id,
        snapshot.market_id,
        outcome_snapshot(snapshot, event.outcome).yes_token_id,
    ):
        raise ValueError("trade plan snapshot identity is inconsistent")
    if event.outcome not in ({"YES"} if event.schema_version == 1 else {"YES", "NO"}):
        raise ValueError("unsupported trade plan outcome")
    if (
        event.created_at != _offset_timestamp(snapshot.captured_at, "captured_at").astimezone(timezone.utc).isoformat()
        or event.expires_at != snapshot.end_time
        or event.market_end != snapshot.end_time
        or not event.reviewer_approved
        or event.policy_references != ("hard-policy-v1",)
        or not event.reviewer_citations
        or not set(event.reviewer_citations) <= set(event.evidence_references)
    ):
        raise ValueError("trade plan terms are unsupported")
    proposal = Proposal(
        event.snapshot_id,
        event.market_id,
        event.probability if event.outcome == "YES" else 1 - event.probability,
        event.stake,
        event.max_entry_price,
        event.exit_plan,
        event.evidence_references,
        event.outcome,
    )
    quote = _quote(snapshot, proposal, event.max_entry_price)
    limits = operating or OperatingConfig(bankroll=snapshot.bankroll)
    decision = check_risk(
        snapshot,
        proposal,
        Review(event.snapshot_id, event.market_id, event.reviewer_approved, "event approval"),
        quote,
        maximum_market_exposure=limits.maximum_market_exposure,
        maximum_total_exposure=limits.maximum_total_exposure,
    )
    if not decision.allowed:
        raise ValueError(decision.reason)
    return quote


def recheck_trade_plan(
    event: TradePlanReady,
    snapshot: MarketSnapshot,
    operating: OperatingConfig,
    *,
    now: datetime,
) -> SimulatedFill:
    """Recheck an original accepted plan against a distinct fresh quote snapshot."""
    validate_trade_plan(event, now=now)
    market_end = _offset_timestamp(event.market_end, "market_end")
    fresh_end = _offset_timestamp(snapshot.end_time, "end_time")
    if snapshot.market_id != event.market_id:
        raise ValueError("fresh market identity does not match the trade plan")
    if outcome_snapshot(snapshot, event.outcome).yes_token_id != event.instrument_id:
        raise ValueError("fresh outcome instrument identity does not match the trade plan")
    if fresh_end != market_end:
        raise ValueError("fresh market terms do not match the trade plan")
    proposal = Proposal(
        snapshot.snapshot_id,
        snapshot.market_id,
        event.probability if event.outcome == "YES" else 1 - event.probability,
        event.stake,
        event.max_entry_price,
        event.exit_plan,
        event.evidence_references,
        event.outcome,
    )
    quote = _quote(snapshot, proposal, event.max_entry_price)
    decision = check_risk(
        snapshot,
        proposal,
        Review(snapshot.snapshot_id, snapshot.market_id, True, "event approval"),
        quote,
        maximum_market_exposure=operating.maximum_market_exposure,
        maximum_total_exposure=operating.maximum_total_exposure,
    )
    if not decision.allowed:
        raise ValueError(decision.reason)
    return quote


def validate_trade_plan(event: TradePlanReady, *, now: datetime) -> None:
    """Validate plan identity and immutable terms without requiring market data."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("consumer current time must include a UTC offset")
    if not isinstance(event, TradePlanReady):
        raise ValueError("unsupported trade plan event")
    expected_event_id = "turn-" + sha256(
        json.dumps([event.snapshot_id, event.market_id], separators=(",", ":")).encode()
    ).hexdigest()[:24]
    if event.event_id != expected_event_id:
        raise ValueError("trade plan event identity is inconsistent")
    if event.schema_version not in {1, 2} or event.record_type != "trade_plan_ready":
        raise ValueError("unsupported trade plan event")
    current = now.astimezone(timezone.utc)
    created = _offset_timestamp(event.created_at, "created_at")
    expires = _offset_timestamp(event.expires_at, "expires_at")
    market_end = _offset_timestamp(event.market_end, "market_end")
    if current >= expires or current >= market_end:
        raise ValueError("trade plan is expired")
    if not created < expires or expires != market_end:
        raise ValueError("trade plan terms are unsupported")
    if (
        not event.reviewer_approved
        or event.outcome not in ({"YES"} if event.schema_version == 1 else {"YES", "NO"})
        or event.policy_references != ("hard-policy-v1",)
        or not event.reviewer_citations
        or not set(event.reviewer_citations) <= set(event.evidence_references)
    ):
        raise ValueError("trade plan terms are unsupported")
    if event.exit_plan.exit_by is not None:
        exit_by = _offset_timestamp(event.exit_plan.exit_by, "exit_by")
        if not current < exit_by < market_end:
            raise ValueError("trade plan exit timing is invalid")


def parse_trade_plan(value: Mapping[str, object]) -> TradePlanReady:
    """Parse the strict serialized event envelope at a consumer boundary."""
    fields = set(TradePlanReady.__dataclass_fields__)
    if set(value) != fields or not isinstance(value.get("exit_plan"), Mapping):
        raise ValueError("invalid trade plan event")
    data = dict(value)
    try:
        data["exit_plan"] = ExitPlan(**dict(data["exit_plan"]))
        for key in ("reviewer_citations", "policy_references", "evidence_references"):
            raw = data[key]
            if not isinstance(raw, (list, tuple)):
                raise TypeError
            data[key] = tuple(raw)
        event = TradePlanReady(**data)
        for name in (
            "event_id", "created_at", "market_id", "snapshot_id", "instrument_id",
            "outcome", "expires_at", "market_end",
        ):
            _identifier(getattr(event, name), name)
        for name in ("probability", "stake", "max_entry_price"):
            _finite(getattr(event, name), name)
        if (
            not 0 <= event.probability <= 1
            or event.stake <= 0
            or not 0 < event.max_entry_price < 1
        ):
            raise ValueError
        if (
            not isinstance(event.schema_version, int)
            or isinstance(event.schema_version, bool)
            or event.schema_version not in {1, 2}
            or event.record_type != "trade_plan_ready"
            or event.outcome not in ({"YES"} if event.schema_version == 1 else {"YES", "NO"})
            or not isinstance(event.reviewer_approved, bool)
            or any(
                not isinstance(item, str) or not item.strip()
                for items in (
                    event.reviewer_citations,
                    event.policy_references,
                    event.evidence_references,
                )
                for item in items
            )
        ):
            raise ValueError
        _offset_timestamp(event.created_at, "created_at")
        _offset_timestamp(event.expires_at, "expires_at")
        _offset_timestamp(event.market_end, "market_end")
        return event
    except (TypeError, ValueError):
        raise ValueError("invalid trade plan event") from None


def _quote(
    snapshot: MarketSnapshot,
    proposal: Proposal,
    max_entry_price: float | None = None,
) -> SimulatedFill:
    snapshot = outcome_snapshot(snapshot, proposal.outcome)
    remaining = Decimal(str(proposal.amount))
    shares = Decimal(0)
    levels_consumed = 0
    # ponytail: six-field local snapshots keep their historical unlimited-price fill.
    levels = snapshot.asks or (BookLevel(snapshot.price, float("1e308")),)
    for level in levels:
        if max_entry_price is not None and level.price > max_entry_price:
            raise ValueError("maximum entry price exceeded")
        price = Decimal(str(level.price))
        spend = min(remaining, price * Decimal(str(level.size)))
        if spend:
            shares += spend / price
            remaining -= spend
            levels_consumed += 1
        if remaining == 0:
            break
    if remaining:
        raise ValueError(f"insufficient executable {proposal.outcome} depth")
    gross = Decimal(str(proposal.amount))
    fee = gross * Decimal(str(snapshot.fee_rate))
    return SimulatedFill(
        snapshot.snapshot_id, snapshot.market_id, float(gross / shares), float(gross),
        float(shares), float(fee), float(gross + fee), levels_consumed,
    )


@dataclass(frozen=True)
class StakeMetrics:
    stake: float
    shares: float
    vwap: float
    worst_entry_price: float
    slippage: float
    fees: float
    total_cash: float
    expected_net_profit: float
    expected_net_roi: float
    marginal_edge: float
    average_edge: float
    break_even_probability: float


@dataclass(frozen=True)
class CapacityPlan:
    stake: float | None
    reason: str | None
    allowance: float
    executable_stake: float
    candidates: tuple[StakeMetrics, ...]


def _stake_metrics(snapshot: MarketSnapshot, outcome: str, probability: float, stake: Decimal) -> StakeMetrics:
    fill = _quote(
        snapshot,
        Proposal(snapshot.snapshot_id, snapshot.market_id, probability, float(stake), outcome=outcome),
    )
    selected = outcome_snapshot(snapshot, outcome)
    p = Decimal(str(probability))
    fee = Decimal(str(snapshot.fee_rate))
    shares = Decimal(str(fill.shares))
    cash = Decimal(str(fill.total_cost))
    vwap = Decimal(str(fill.price))
    worst = Decimal(str(selected.asks[fill.levels_consumed - 1].price))
    profit = shares * p - cash
    return StakeMetrics(
        float(stake),
        float(shares),
        float(vwap),
        float(worst),
        float(vwap - Decimal(str(selected.price))),
        float(Decimal(str(fill.fee))),
        float(cash),
        float(profit),
        float(profit / cash),
        float(p - worst * (1 + fee)),
        float(p - vwap * (1 + fee)),
        float(cash / shares),
    )


def plan_capacity(
    snapshot: MarketSnapshot,
    outcome: str,
    probability: float,
    allowance: float,
) -> CapacityPlan:
    """Largest stake whose marginal book level still meets the net edge.

    `allowance` is the gross-spend cap from policy/exposure; executable depth
    is observed book data and is never extrapolated. Requires a real ask book.
    """
    _finite(probability, "probability")
    _finite(allowance, "allowance")
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")
    if allowance < 0:
        raise ValueError("allowance cannot be negative")
    selected = outcome_snapshot(snapshot, outcome)
    if not selected.asks:
        raise ValueError("capacity planning requires an executable ask book")
    cap = Decimal(str(allowance))
    depth = Decimal(0)
    stakes: list[Decimal] = []
    for level in selected.asks:
        depth += Decimal(str(level.price)) * Decimal(str(level.size))
        if depth <= cap:
            stakes.append(depth)
    executable = min(cap, depth)
    if not stakes or (stakes and executable > stakes[-1] and executable < depth):
        stakes.append(executable)
    if executable <= 0:
        return CapacityPlan(None, f"no executable {outcome} stake within policy allowance", float(cap), float(executable), ())
    candidates: list[StakeMetrics] = []
    chosen: StakeMetrics | None = None
    for stake in stakes:
        metrics = _stake_metrics(snapshot, outcome, probability, stake)
        candidates.append(metrics)
        if metrics.marginal_edge >= MINIMUM_NET_EDGE - 1e-12:
            chosen = metrics
    if chosen is None:
        return CapacityPlan(
            None,
            f"no executable {outcome} stake meets the minimum net edge of 0.05 within captured depth",
            float(cap),
            float(executable),
            tuple(candidates),
        )
    return CapacityPlan(chosen.stake, None, float(cap), float(executable), tuple(candidates))


def quote_exit(snapshot: MarketSnapshot, shares: float) -> ExitQuote:
    """Quote a complete YES close against executable bid depth."""
    _finite(shares, "shares")
    if shares <= 0:
        raise ValueError("shares must be positive")
    remaining = Decimal(str(shares))
    gross = Decimal(0)
    levels_consumed = 0
    for level in snapshot.bids:
        size = Decimal(str(level.size))
        filled = min(remaining, size)
        if filled:
            gross += filled * Decimal(str(level.price))
            remaining -= filled
            levels_consumed += 1
        if remaining == 0:
            break
    if remaining:
        raise ValueError("insufficient executable YES bid depth")
    fee = gross * Decimal(str(snapshot.fee_rate))
    net = gross - fee
    return ExitQuote(
        float(gross / Decimal(str(shares))),
        float(Decimal(str(shares))),
        float(gross),
        float(fee),
        float(net),
        levels_consumed,
    )


def check_risk(
    snapshot: MarketSnapshot,
    proposal: Proposal,
    review: Review,
    quote: SimulatedFill | None = None,
    quote_error: str | None = None,
    maximum_market_exposure: float = MAXIMUM_MARKET_EXPOSURE,
    maximum_total_exposure: float = MAXIMUM_TOTAL_EXPOSURE,
) -> RiskDecision:
    identities = {(snapshot.snapshot_id, snapshot.market_id), (proposal.snapshot_id, proposal.market_id), (review.snapshot_id, review.market_id)}
    if len(identities) != 1:
        raise ValueError("snapshot and market identity must be consistent")
    if not review.approved:
        return RiskDecision(False, f"review rejected: {review.reason}")
    selected = outcome_snapshot(snapshot, proposal.outcome)
    probability = proposal.probability if proposal.outcome == "YES" else 1 - proposal.probability
    if probability - selected.price < MINIMUM_NET_EDGE - 1e-12:
        return RiskDecision(False, "minimum net edge of 0.05 not met")
    if quote_error is not None:
        return RiskDecision(False, quote_error)
    try:
        quoted = quote or _quote(snapshot, proposal)
    except ValueError as exc:
        return RiskDecision(False, str(exc))
    if proposal.max_entry_price is not None and quoted.price > proposal.max_entry_price:
        return RiskDecision(False, "maximum entry price exceeded")
    if snapshot.market_exposure + quoted.total_cost > snapshot.bankroll * maximum_market_exposure:
        return RiskDecision(False, "per-market exposure limit exceeded")
    if snapshot.total_exposure + quoted.total_cost > snapshot.bankroll * maximum_total_exposure:
        return RiskDecision(False, "total exposure limit exceeded")
    # shortcut: six-field local snapshots without a real ask book keep the legacy path.
    if selected.asks:
        fee = Decimal(str(snapshot.fee_rate))
        allowance = max(
            Decimal(0),
            min(
                Decimal(str(snapshot.bankroll)) * Decimal(str(maximum_market_exposure))
                - Decimal(str(snapshot.market_exposure)),
                Decimal(str(snapshot.bankroll)) * Decimal(str(maximum_total_exposure))
                - Decimal(str(snapshot.total_exposure)),
            )
            / (Decimal(1) + fee),
        )
        capacity = plan_capacity(snapshot, proposal.outcome, probability, float(allowance))
        if capacity.stake is None:
            return RiskDecision(False, capacity.reason or "no executable stake meets the minimum net edge")
        if Decimal(str(proposal.amount)) > Decimal(str(capacity.stake)) + Decimal("1e-9"):
            try:
                deterioration = _stake_metrics(
                    snapshot, proposal.outcome, probability, Decimal(str(proposal.amount))
                )
                detail = (
                    f"; the {proposal.amount:g} quote deteriorates to marginal edge "
                    f"{deterioration.marginal_edge:.4f} at worst entry {deterioration.worst_entry_price:g} "
                    f"(expected net ROI {deterioration.expected_net_roi:.4f})"
                )
            except ValueError:
                detail = f"; {proposal.amount:g} is not executable within captured depth"
            return RiskDecision(
                False,
                f"stake {proposal.amount:g} exceeds the edge-aware capacity {capacity.stake:g} "
                f"for forecast {probability:g} (policy allowance {capacity.allowance:g}){detail}",
            )
    return RiskDecision(True, "approved by review and deterministic risk policy")


def paper_execute(snapshot: MarketSnapshot, proposal: Proposal) -> SimulatedFill:
    """Quote a complete depth-aware YES fill; this is not an agent tool."""
    return _quote(snapshot, proposal)


def run_decision_cycle(
    snapshot: MarketSnapshot,
    proposal: Proposal,
    review: Review,
    operating: OperatingConfig | None = None,
) -> CycleReport:
    """Run proposal, review, and risk policy without consuming an accepted plan."""
    quote = None
    quote_error = None
    if proposal.exit_plan is not None:
        if proposal.max_entry_price is None:
            quote_error = "maximum entry price is required with an exit plan"
        elif proposal.exit_plan.exit_by is not None:
            exit_by = _offset_timestamp(proposal.exit_plan.exit_by, "exit_by")
            captured = _offset_timestamp(snapshot.captured_at, "captured_at") if snapshot.captured_at else None
            end = _offset_timestamp(snapshot.end_time, "end_time") if snapshot.end_time else None
            if captured is None or end is None or not captured < exit_by < end:
                quote_error = "exit_by must be after capture and before market end"
    selected = outcome_snapshot(snapshot, proposal.outcome)
    probability = proposal.probability if proposal.outcome == "YES" else 1 - proposal.probability
    if review.approved and probability - selected.price >= MINIMUM_NET_EDGE - 1e-12:
        try:
            quote = _quote(snapshot, proposal, proposal.max_entry_price)
        except ValueError as exc:
            quote_error = str(exc)
    limits = operating or OperatingConfig(bankroll=snapshot.bankroll)
    decision = check_risk(
        snapshot,
        proposal,
        review,
        quote,
        quote_error,
        limits.maximum_market_exposure,
        limits.maximum_total_exposure,
    )
    event = None
    if decision.allowed and proposal.exit_plan is not None:
        event = _trade_plan_ready(snapshot, proposal, review)
    outcome = "trade plan ready" if event else f"no trade plan: {decision.reason}"
    return CycleReport(
        decision, None, f"{snapshot.snapshot_id}/{snapshot.market_id}: {outcome}", event
    )
