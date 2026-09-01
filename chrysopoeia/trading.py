from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite
from urllib.parse import urlparse


MINIMUM_NET_EDGE = 0.05
MAXIMUM_MARKET_EXPOSURE = 0.01
MAXIMUM_TOTAL_EXPOSURE = 0.10


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
            parsed = urlparse(self.source_url)
            try:
                port = parsed.port
            except ValueError:
                port = -1
            if parsed.scheme != "https" or parsed.hostname not in {"polymarket.com", "www.polymarket.com"} or port is not None or parsed.username is not None or parsed.password is not None or not parsed.path.startswith("/event/") or parsed.query or parsed.fragment:
                raise ValueError("source_url must be a canonical public Polymarket HTTPS event URL")


@dataclass(frozen=True)
class Proposal:
    snapshot_id: str
    market_id: str
    probability: float
    amount: float

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        _identifier(self.market_id, "market_id")
        _finite(self.probability, "probability")
        _finite(self.amount, "amount")
        if not 0 <= self.probability <= 1:
            raise ValueError("probability must be between 0 and 1")
        if self.amount <= 0:
            raise ValueError("proposal amount must be positive")


@dataclass(frozen=True)
class Review:
    snapshot_id: str
    market_id: str
    approved: bool
    reason: str

    def __post_init__(self) -> None:
        _identifier(self.snapshot_id, "snapshot_id")
        _identifier(self.market_id, "market_id")
        if not isinstance(self.approved, bool):
            raise ValueError("review approval must be boolean")
        _identifier(self.reason, "review reason")


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
class CycleReport:
    decision: RiskDecision
    fill: SimulatedFill | None
    summary: str


def _quote(snapshot: MarketSnapshot, proposal: Proposal) -> SimulatedFill:
    remaining = Decimal(str(proposal.amount))
    shares = Decimal(0)
    levels_consumed = 0
    # ponytail: six-field local snapshots keep their historical unlimited-price fill.
    levels = snapshot.asks or (BookLevel(snapshot.price, float("1e308")),)
    for level in levels:
        price = Decimal(str(level.price))
        spend = min(remaining, price * Decimal(str(level.size)))
        if spend:
            shares += spend / price
            remaining -= spend
            levels_consumed += 1
        if remaining == 0:
            break
    if remaining:
        raise ValueError("insufficient executable YES depth")
    gross = Decimal(str(proposal.amount))
    fee = gross * Decimal(str(snapshot.fee_rate))
    return SimulatedFill(
        snapshot.snapshot_id, snapshot.market_id, float(gross / shares), float(gross),
        float(shares), float(fee), float(gross + fee), levels_consumed,
    )


def check_risk(
    snapshot: MarketSnapshot,
    proposal: Proposal,
    review: Review,
    quote: SimulatedFill | None = None,
    quote_error: str | None = None,
) -> RiskDecision:
    identities = {(snapshot.snapshot_id, snapshot.market_id), (proposal.snapshot_id, proposal.market_id), (review.snapshot_id, review.market_id)}
    if len(identities) != 1:
        raise ValueError("snapshot and market identity must be consistent")
    if not review.approved:
        return RiskDecision(False, f"review rejected: {review.reason}")
    if proposal.probability - snapshot.price < MINIMUM_NET_EDGE - 1e-12:
        return RiskDecision(False, "minimum net edge of 0.05 not met")
    if quote_error is not None:
        return RiskDecision(False, quote_error)
    try:
        quoted = quote or _quote(snapshot, proposal)
    except ValueError as exc:
        return RiskDecision(False, str(exc))
    if snapshot.market_exposure + quoted.total_cost > snapshot.bankroll * MAXIMUM_MARKET_EXPOSURE:
        return RiskDecision(False, "per-market exposure limit exceeded")
    if snapshot.total_exposure + quoted.total_cost > snapshot.bankroll * MAXIMUM_TOTAL_EXPOSURE:
        return RiskDecision(False, "total exposure limit exceeded")
    return RiskDecision(True, "approved by review and deterministic risk policy")


def paper_execute(snapshot: MarketSnapshot, proposal: Proposal) -> SimulatedFill:
    """Quote a complete depth-aware YES fill; this is not an agent tool."""
    return _quote(snapshot, proposal)


def run_decision_cycle(snapshot: MarketSnapshot, proposal: Proposal, review: Review) -> CycleReport:
    """Run proposal, review, risk, paper execution, and reporting in order."""
    quote = None
    quote_error = None
    if review.approved and proposal.probability - snapshot.price >= MINIMUM_NET_EDGE - 1e-12:
        try:
            quote = _quote(snapshot, proposal)
        except ValueError as exc:
            quote_error = str(exc)
    decision = check_risk(snapshot, proposal, review, quote, quote_error)
    fill = quote if decision.allowed else None
    outcome = (
        f"filled VWAP {fill.price:g}, gross {fill.amount:g}, fee {fill.fee:g}, "
        f"total {fill.total_cost:g}, shares {fill.shares:g}"
        if fill else f"no fill: {decision.reason}"
    )
    return CycleReport(decision, fill, f"{snapshot.snapshot_id}/{snapshot.market_id}: {outcome}")
