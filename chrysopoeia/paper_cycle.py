import ipaddress
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from inspect import signature
from math import isfinite
from typing import Annotated, Literal, Protocol, TypeGuard, TypeVar
from urllib.parse import urlsplit, urlunsplit

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
VALIDATED_EXTERNAL_EVIDENCE_KEY = "validated_external_evidence"
PAPER_CYCLE_DECISION_KEY = "paper_cycle_decision"
PAPER_CYCLE_FILL_KEY = "paper_cycle_fill"
PAPER_CYCLE_REPORT_KEY = "paper_cycle_report"
MAX_EVIDENCE_ID_LENGTH = 200
MAX_SNAPSHOT_ID_LENGTH = 128
MAX_RETRIEVED_AT_LENGTH = 64


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRecord(StrictOutput):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str = Field(min_length=1, max_length=MAX_EVIDENCE_ID_LENGTH)
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    retrieved_at: str = Field(min_length=1, max_length=MAX_RETRIEVED_AT_LENGTH)
    source_kind: Literal["market_snapshot", "external"]
    snapshot_id: str = Field(min_length=1, max_length=MAX_SNAPSHOT_ID_LENGTH)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("title must not be blank")
        return value

    @field_validator("snapshot_id")
    @classmethod
    def validate_snapshot_id(cls, value: str) -> str:
        if not value.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("snapshot_id must be non-blank and contain no controls")
        return value

    @model_validator(mode="after")
    def validate_source(self) -> "EvidenceRecord":
        if self.source_kind == "external":
            normalized = _normalize_web_url(self.url)
            expected = _external_evidence_id(
                self.snapshot_id, normalized, self.title, self.retrieved_at
            )
            if self.evidence_id != expected:
                raise ValueError("evidence_id does not match external evidence")
            object.__setattr__(self, "url", normalized)
            return self
        try:
            canonical = validate_polymarket_event_url(self.url)
        except ValueError:
            raise ValueError("url must be a canonical Polymarket HTTPS event URL")  # noqa: B904
        if canonical != self.url:
            raise ValueError("url must be a canonical Polymarket HTTPS event URL")
        expected = f"market_snapshot:{self.snapshot_id}"
        if len(expected) > 128:
            expected = (
                "market_snapshot:" + sha256(self.snapshot_id.encode()).hexdigest()
            )
        if self.evidence_id != expected:
            raise ValueError("evidence_id does not match the canonical snapshot")
        return self

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: str) -> str:
        if (
            len(value) > MAX_RETRIEVED_AT_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                value,
            )
        ):
            raise ValueError("retrieved_at must be an RFC3339 timestamp")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("retrieved_at must be an RFC3339 timestamp") from None
        if timestamp.tzinfo is None:
            raise ValueError("retrieved_at must include a UTC offset")
        return value


def _normalize_web_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("web URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("web URL is invalid") from None
    host = parsed.hostname
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in {None, 443}
        or "\\" in value
        or re.search(r"%(?![0-9A-Fa-f]{2})", value)
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("web URL is invalid")
    normalized_host = host.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None
    if (
        address is not None
        or "." not in normalized_host
        or normalized_host == "localhost"
        or normalized_host.endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError("web URL host must be public")
    try:
        normalized_host = normalized_host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("web URL is invalid") from None
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or re.fullmatch(r"[a-z0-9-]+", label) is None
        for label in normalized_host.split(".")
    ):
        raise ValueError("web URL is invalid")
    netloc = normalized_host if port in {None, 443} else f"{normalized_host}:{port}"
    normalized = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
    if len(normalized) > 2048:
        raise ValueError("web URL is invalid")
    return normalized


def _external_evidence_id(
    snapshot_id: str, normalized_url: str, normalized_title: str, retrieved_at: str
) -> str:
    digest = sha256(
        f"{snapshot_id}\n{normalized_url}\n{normalized_title}\n{retrieved_at}".encode()
    ).hexdigest()[:56]
    return f"external:{snapshot_id}:{digest}"


def external_evidence(
    snapshot: MarketSnapshot,
    url: str,
    title: str,
    retrieved_at: str,
) -> EvidenceRecord:
    """Construct one normalized, snapshot-bound external evidence record."""
    normalized_url = _normalize_web_url(url)
    normalized_title = title.strip() if isinstance(title, str) else title
    return EvidenceRecord(
        evidence_id=_external_evidence_id(
            snapshot.snapshot_id, normalized_url, normalized_title, retrieved_at
        ),
        url=normalized_url,
        title=normalized_title,
        retrieved_at=retrieved_at,
        source_kind="external",
        snapshot_id=snapshot.snapshot_id,
    )


def _validate_unique_citations(citations: list[str]) -> list[str]:
    if len(citations) != len(set(citations)):
        raise ValueError("citations must be unique")
    return citations


CitationId = Annotated[str, Field(min_length=1, max_length=MAX_EVIDENCE_ID_LENGTH)]


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
    if not expected and not actual:
        return actual
    try:
        validated = validate_evidence_bundle(snapshot, actual)
    except ValueError:
        raise ValueError(
            "paper cycle evidence does not match the canonical snapshot"
        ) from None
    return validated


def validate_evidence_bundle(
    snapshot: MarketSnapshot, evidence: list[EvidenceRecord]
) -> list[EvidenceRecord]:
    canonical = _canonical_evidence(snapshot)
    if not canonical or not 1 <= len(evidence) <= 20 or evidence[:1] != canonical:
        raise ValueError("evidence does not match the canonical snapshot")
    external = evidence[1:]
    if any(
        record.source_kind != "external" or record.snapshot_id != snapshot.snapshot_id
        for record in external
    ):
        raise ValueError("evidence does not match the canonical snapshot")
    ids = [record.evidence_id for record in evidence]
    urls = [canonical[0].url, *(_normalize_web_url(record.url) for record in external)]
    if len(ids) != len(set(ids)) or len(urls) != len(set(urls)):
        raise ValueError("evidence contains duplicates")
    return evidence


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
