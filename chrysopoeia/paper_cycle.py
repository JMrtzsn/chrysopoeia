import re
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from inspect import signature
from math import isfinite
from typing import Annotated, Literal, Protocol, TypeGuard, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chrysopoeia.trading import (
    MarketSnapshot,
    OperatingConfig,
    Proposal,
    Review,
    run_decision_cycle,
    validate_polymarket_event_url,
)

PROPOSAL_KEY = "paper_cycle_proposal"
REVIEW_KEY = "paper_cycle_review"
EVIDENCE_KEY = "paper_cycle_evidence"
PAPER_CYCLE_DECISION_KEY = "paper_cycle_decision"
PAPER_CYCLE_FILL_KEY = "paper_cycle_fill"
PAPER_CYCLE_REPORT_KEY = "paper_cycle_report"


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRecord(StrictOutput):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    retrieved_at: str = Field(min_length=1)
    source_kind: Literal["market_snapshot"]
    snapshot_id: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            return validate_polymarket_event_url(value)
        except ValueError:
            raise ValueError("url must be a canonical Polymarket HTTPS event URL")  # noqa: B904

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: str) -> str:
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
            value,
        ):
            raise ValueError("retrieved_at must be an RFC3339 timestamp")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("retrieved_at must be an RFC3339 timestamp") from None
        if timestamp.tzinfo is None:
            raise ValueError("retrieved_at must include a UTC offset")
        return value


def _validate_unique_citations(citations: list[str]) -> list[str]:
    if len(citations) != len(set(citations)):
        raise ValueError("citations must be unique")
    return citations


CitationId = Annotated[str, Field(min_length=1, max_length=128)]


class ProposalOutput(StrictOutput):
    snapshot_id: str = Field(min_length=1, max_length=200)
    market_id: str = Field(min_length=1, max_length=200)
    action: Literal["trade", "abstain"]
    probability: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)
    amount: float = Field(strict=True)
    citations: list[CitationId] = Field(max_length=10)

    _unique_citations = field_validator("citations")(_validate_unique_citations)

    @model_validator(mode="after")
    def validate_action_amount(self) -> "ProposalOutput":
        if not isfinite(self.amount):
            raise ValueError("amount must be finite")
        if self.action == "trade" and self.amount <= 0:
            raise ValueError("trade amount must be positive")
        if self.action == "trade" and not self.citations:
            raise ValueError("trade requires a citation")
        if self.action == "abstain" and self.amount != 0:
            raise ValueError("abstain amount must be zero")
        return self


class ReviewOutput(StrictOutput):
    snapshot_id: str = Field(min_length=1, max_length=200)
    market_id: str = Field(min_length=1, max_length=200)
    approved: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=500)
    citations: list[CitationId] = Field(max_length=10)

    _unique_citations = field_validator("citations")(_validate_unique_citations)

    @model_validator(mode="after")
    def validate_approval_citations(self) -> "ReviewOutput":
        if self.approved and not self.citations:
            raise ValueError("approval requires a citation")
        return self


class PaperCycleRequest(StrictOutput):
    pass


class ReviewerInput(StrictOutput):
    market_snapshot: dict[str, object]
    proposal: ProposalOutput
    evidence: list[EvidenceRecord] = Field(max_length=20)


class PaperCycleReportOutput(StrictOutput):
    status: str
    reason: str
    summary: str


class StateShape(Protocol):
    def get(self, key: str, default: object = None) -> object: ...

    def __setitem__(self, key: str, value: object) -> None: ...


StateMap = MutableMapping[str, object] | StateShape
Record = TypeVar("Record")


def _is_state_map(state: object) -> TypeGuard[StateMap]:
    if isinstance(state, MutableMapping):
        return True
    try:
        signature(state.get).bind("key", None)
        signature(state.__setitem__).bind("key", None)
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _record(value: object, record_type: type[Record], error: str) -> Record:
    if not isinstance(value, Mapping):
        raise ValueError(error)
    try:
        return record_type(**dict(value))
    except (TypeError, ValueError):
        raise ValueError(error) from None


def _canonical_evidence(snapshot: MarketSnapshot) -> list[EvidenceRecord]:
    if not all((snapshot.question, snapshot.captured_at, snapshot.source_url)):
        return []
    evidence_id = f"market_snapshot:{snapshot.snapshot_id}"
    if len(evidence_id) > 128:
        evidence_id = (
            "market_snapshot:" + sha256(snapshot.snapshot_id.encode()).hexdigest()
        )
    return [
        EvidenceRecord(
            evidence_id=evidence_id,
            url=snapshot.source_url,
            title=snapshot.question,
            retrieved_at=snapshot.captured_at,
            source_kind="market_snapshot",
            snapshot_id=snapshot.snapshot_id,
        )
    ]


def _evidence(state: StateMap, snapshot: MarketSnapshot) -> list[EvidenceRecord]:
    expected = _canonical_evidence(snapshot)
    value = state.get(EVIDENCE_KEY)
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("paper cycle evidence is missing or invalid")
    try:
        actual = [EvidenceRecord.model_validate(record) for record in value]
    except (TypeError, ValueError):
        raise ValueError("paper cycle evidence is missing or invalid") from None
    if actual != expected:
        raise ValueError("paper cycle evidence does not match the canonical snapshot")
    return actual


def _validate_citations(citations: list[str], evidence: list[EvidenceRecord]) -> None:
    available = {record.evidence_id for record in evidence}
    if any(citation not in available for citation in citations):
        raise ValueError("citation does not resolve to canonical snapshot evidence")


def finalize_paper_cycle(
    state: StateMap, review_output: ReviewOutput
) -> dict[str, object]:
    """Validate cycle state, run deterministic policy and paper fill, and store the report."""
    if not _is_state_map(state):
        raise ValueError("session state is invalid")
    operating = _record(
        state.get("operating_config"),
        OperatingConfig,
        "operating configuration is missing or invalid",
    )
    snapshot = _record(
        state.get("market_snapshot"),
        MarketSnapshot,
        "market snapshot is missing or invalid",
    )
    proposal_output = _record(
        state.get(PROPOSAL_KEY), ProposalOutput, "paper proposal is missing or invalid"
    )
    if not isinstance(review_output, ReviewOutput):
        raise ValueError("paper review is missing or invalid")
    evidence = _evidence(state, snapshot)
    _validate_citations(proposal_output.citations, evidence)
    _validate_citations(review_output.citations, evidence)
    if proposal_output.action != "trade":
        raise ValueError("paper proposal is not a trade")
    if (snapshot.snapshot_id, snapshot.market_id) != (
        proposal_output.snapshot_id,
        proposal_output.market_id,
    ) or (proposal_output.snapshot_id, proposal_output.market_id) != (
        review_output.snapshot_id,
        review_output.market_id,
    ):
        raise ValueError("paper cycle snapshot identity is inconsistent")
    state[REVIEW_KEY] = review_output.model_dump()
    proposal = Proposal(**proposal_output.model_dump(exclude={"action", "citations"}))
    review = Review(**review_output.model_dump(exclude={"citations"}))
    try:
        cycle = run_decision_cycle(snapshot, proposal, review, operating)
    except ValueError:
        raise ValueError("paper cycle snapshot identity is inconsistent") from None

    decision = asdict(cycle.decision)
    fill = asdict(cycle.fill) if cycle.fill else None
    if cycle.fill:
        status, reason = "filled", "filled"
    elif not review.approved:
        status, reason = "rejected", "review_rejected"
    else:
        status, reason = "rejected", cycle.decision.reason
    report = PaperCycleReportOutput(
        status=status, reason=reason, summary=cycle.summary
    ).model_dump()
    state[PAPER_CYCLE_DECISION_KEY] = decision
    state[PAPER_CYCLE_FILL_KEY] = fill
    state[PAPER_CYCLE_REPORT_KEY] = report
    return report
