from dataclasses import dataclass
from math import isfinite


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
class MarketSnapshot:
    snapshot_id: str
    market_id: str
    price: float
    bankroll: float
    market_exposure: float
    total_exposure: float

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


@dataclass(frozen=True)
class CycleReport:
    decision: RiskDecision
    fill: SimulatedFill | None
    summary: str


def check_risk(snapshot: MarketSnapshot, proposal: Proposal, review: Review) -> RiskDecision:
    identities = {(snapshot.snapshot_id, snapshot.market_id), (proposal.snapshot_id, proposal.market_id), (review.snapshot_id, review.market_id)}
    if len(identities) != 1:
        raise ValueError("snapshot and market identity must be consistent")
    if not review.approved:
        return RiskDecision(False, f"review rejected: {review.reason}")
    if proposal.probability - snapshot.price < MINIMUM_NET_EDGE - 1e-12:
        return RiskDecision(False, "minimum net edge of 0.05 not met")
    if snapshot.market_exposure + proposal.amount > snapshot.bankroll * MAXIMUM_MARKET_EXPOSURE:
        return RiskDecision(False, "per-market exposure limit exceeded")
    if snapshot.total_exposure + proposal.amount > snapshot.bankroll * MAXIMUM_TOTAL_EXPOSURE:
        return RiskDecision(False, "total exposure limit exceeded")
    return RiskDecision(True, "approved by review and deterministic risk policy")


def paper_execute(snapshot: MarketSnapshot, proposal: Proposal) -> SimulatedFill:
    """Simulate a fill at the canonical snapshot price; this is not an agent tool."""
    return SimulatedFill(snapshot.snapshot_id, snapshot.market_id, snapshot.price, proposal.amount)


def run_decision_cycle(snapshot: MarketSnapshot, proposal: Proposal, review: Review) -> CycleReport:
    """Run proposal, review, risk, paper execution, and reporting in order."""
    decision = check_risk(snapshot, proposal, review)
    fill = paper_execute(snapshot, proposal) if decision.allowed else None
    outcome = f"filled {fill.amount:g} at {fill.price:g}" if fill else f"no fill: {decision.reason}"
    return CycleReport(decision, fill, f"{snapshot.snapshot_id}/{snapshot.market_id}: {outcome}")
