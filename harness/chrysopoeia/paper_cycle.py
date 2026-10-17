import ipaddress
import json
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from inspect import signature
from math import isfinite
from typing import Annotated, Literal, Protocol, TypeGuard, TypeVar
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chrysopoeia.trading import (
    ExitPlan,
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
TRADE_PLAN_READY_KEY = "trade_plan_ready"
TURN_OUTCOME_KEY = "turn_outcome"
PAPER_CYCLE_REPORT_KEY = "paper_cycle_report"
LAST_SUCCESSFUL_PLAN_KEY = "last_successful_trade_plan"
LAST_SUCCESSFUL_SNAPSHOT_KEY = "last_successful_trade_plan_snapshot"
PLAN_CHECKS_KEY = "plan_checks"
MAX_PLAN_CHECKS = 5
MAX_EVIDENCE_ID_LENGTH = 200
MAX_SNAPSHOT_ID_LENGTH = 128
MAX_RETRIEVED_AT_LENGTH = 64
MAX_EVIDENCE_EXCERPT_LENGTH = 500


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
    excerpt: str | None = Field(default=None, min_length=1, max_length=MAX_EVIDENCE_EXCERPT_LENGTH)

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

    @field_validator("excerpt")
    @classmethod
    def validate_excerpt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("excerpt must be non-blank and contain no controls")
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
                self.snapshot_id, normalized, self.title, self.retrieved_at, self.excerpt
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
    snapshot_id: str,
    normalized_url: str,
    normalized_title: str,
    retrieved_at: str,
    excerpt: str | None = None,
) -> str:
    value = f"{snapshot_id}\n{normalized_url}\n{normalized_title}\n{retrieved_at}"
    if excerpt is not None:
        value += f"\n{excerpt}"
    digest = sha256(value.encode()).hexdigest()[:56]
    return f"external:{snapshot_id}:{digest}"


def external_evidence(
    snapshot: MarketSnapshot,
    url: str,
    title: str,
    retrieved_at: str,
    excerpt: str | None = None,
) -> EvidenceRecord:
    """Construct one normalized, snapshot-bound external evidence record."""
    normalized_url = _normalize_web_url(url)
    normalized_title = title.strip() if isinstance(title, str) else title
    normalized_excerpt = excerpt.strip() if isinstance(excerpt, str) else excerpt
    return EvidenceRecord(
        evidence_id=_external_evidence_id(
            snapshot.snapshot_id,
            normalized_url,
            normalized_title,
            retrieved_at,
            normalized_excerpt,
        ),
        url=normalized_url,
        title=normalized_title,
        retrieved_at=retrieved_at,
        source_kind="external",
        snapshot_id=snapshot.snapshot_id,
        excerpt=normalized_excerpt,
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
    outcome: Literal["YES", "NO"] = Field(default="YES", exclude_if=lambda value: value == "YES")
    amount: float = Field(strict=True)
    citations: list[CitationId] = Field(max_length=10)
    rationale: str = Field(min_length=1, max_length=500)
    max_entry_price: float | None = Field(default=None, ge=0, le=1, strict=True)
    exit_plan: "ExitPlanOutput | None" = None

    _unique_citations = field_validator("citations")(_validate_unique_citations)

    @model_validator(mode="after")
    def validate_action_amount(self) -> "ProposalOutput":
        if not isfinite(self.amount):
            raise ValueError("amount must be finite")
        if self.action == "trade" and self.amount <= 0:
            raise ValueError("trade amount must be positive")
        if self.action == "trade" and not self.citations:
            raise ValueError("trade requires a citation")
        if self.action == "trade":
            if self.max_entry_price is None or self.exit_plan is None:
                raise ValueError("trade requires a maximum entry price and exit plan")
            if not 0 < self.max_entry_price < 1:
                raise ValueError("max_entry_price must be between 0 and 1")
        if self.action == "abstain" and self.amount != 0:
            raise ValueError("abstain amount must be zero")
        if self.action == "abstain" and (
            self.max_entry_price is not None or self.exit_plan is not None
        ):
            raise ValueError("abstention cannot include trade terms")
        return self


class ExitPlanOutput(StrictOutput):
    take_profit_roi: float = Field(ge=0, strict=True)
    stop_loss_roi: float | None = Field(default=None, ge=-1, le=0, strict=True)
    exit_by: str | None = Field(
        default=None, max_length=MAX_RETRIEVED_AT_LENGTH, strict=True
    )
    hold_to_resolution: bool = Field(default=False, strict=True)

    @field_validator("exit_by")
    @classmethod
    def validate_exit_by(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                raise ValueError("exit_by must be an RFC3339 timestamp") from None
            if parsed.tzinfo is None or len(value) > MAX_RETRIEVED_AT_LENGTH:
                raise ValueError("exit_by must be an RFC3339 timestamp")
        return value

    @model_validator(mode="after")
    def validate_exit_choice(self) -> "ExitPlanOutput":
        try:
            ExitPlan(**self.model_dump())
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        return self


ProposalOutput.model_rebuild()


class PlanCheck(StrictOutput):
    passed: bool = Field(strict=True)
    reasons: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        max_length=MAX_PLAN_CHECKS
    )
    plan: ProposalOutput | None


class OutcomeEvidence(StrictOutput):
    evidence_id: str = Field(min_length=1, max_length=MAX_EVIDENCE_ID_LENGTH)
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    source_kind: Literal["market_snapshot", "external"]
    excerpt: str | None = Field(default=None, min_length=1, max_length=MAX_EVIDENCE_EXCERPT_LENGTH)


class ResearchStatus(StrictOutput):
    status: Literal["ok", "unavailable"]
    reason: str | None = Field(default=None, min_length=1, max_length=200)
    query_count: int = Field(ge=0, strict=True)


def build_turn_outcome(
    *,
    proposal: Mapping[str, object],
    review: Mapping[str, object] | None,
    policy: Mapping[str, object] | None,
    status: Literal[
        "abstained",
        "plan_check_rejected",
        "reviewer_rejected",
        "policy_rejected",
        "plan_ready",
    ],
    reason: str,
    created_at: str,
    trade_plan_event_id: str | None,
    model_cost_usd: str,
    plan_checks: object = (),
    evidence: object = (),
    research: object | None = None,
) -> dict[str, object]:
    """Build one deterministic, strict outcome payload from decided cycle state."""
    output = ProposalOutput.model_validate(proposal)
    checked_review = ReviewOutput.model_validate(review) if review is not None else None
    if not isinstance(plan_checks, (list, tuple)) or len(plan_checks) > MAX_PLAN_CHECKS:
        raise ValueError("outcome plan checks are invalid")
    try:
        checked_plan_checks = [PlanCheck.model_validate(check) for check in plan_checks]
    except (TypeError, ValueError):
        raise ValueError("outcome plan checks are invalid") from None
    if not isinstance(evidence, (list, tuple)) or len(evidence) > 20:
        raise ValueError("outcome evidence is invalid")
    try:
        checked_evidence = [OutcomeEvidence.model_validate(record) for record in evidence]
        checked_research = ResearchStatus.model_validate(
            research or {"status": "unavailable", "reason": "legacy outcome", "query_count": 0}
        )
    except (TypeError, ValueError):
        raise ValueError("outcome research is invalid") from None
    if not isinstance(reason, str) or not 1 <= len(reason) <= 500:
        raise ValueError("outcome reason is invalid")
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError("outcome creation time is invalid") from None
    if created.tzinfo is None or len(created_at) > 64:
        raise ValueError("outcome creation time is invalid")
    checked_policy = dict(policy) if policy is not None else None
    if checked_policy is not None and (
        set(checked_policy) != {"allowed", "reason"}
        or not isinstance(checked_policy.get("allowed"), bool)
        or not isinstance(checked_policy.get("reason"), str)
        or not 1 <= len(str(checked_policy["reason"])) <= 500
    ):
        raise ValueError("outcome policy is invalid")
    if status == "plan_ready" and trade_plan_event_id is None:
        raise ValueError("plan-ready outcome requires a trade plan event")
    if status != "plan_ready" and trade_plan_event_id is not None:
        raise ValueError("rejected outcome cannot reference a trade plan event")
    turn_id = "turn-" + sha256(
        json.dumps([output.snapshot_id, output.market_id], separators=(",", ":")).encode()
    ).hexdigest()[:24]
    if status in {"abstained", "plan_check_rejected"} and (
        checked_review is not None or checked_policy is not None
    ):
        raise ValueError("outcome contains an unexpected review or policy")
    if status == "reviewer_rejected" and (
        checked_review is None
        or checked_review.approved
        or checked_policy is None
        or checked_policy["allowed"] is not False
    ):
        raise ValueError("reviewer rejection outcome is inconsistent")
    if status == "policy_rejected" and (
        checked_review is None
        or not checked_review.approved
        or checked_policy is None
        or checked_policy["allowed"] is not False
    ):
        raise ValueError("policy rejection outcome is inconsistent")
    if status == "plan_ready" and (
        checked_review is None
        or not checked_review.approved
        or checked_policy is None
        or checked_policy["allowed"] is not True
        or trade_plan_event_id != turn_id
    ):
        raise ValueError("plan-ready outcome is inconsistent")
    try:
        cost = Decimal(model_cost_usd)
    except InvalidOperation:
        raise ValueError("model cost must be non-negative") from None
    if not cost.is_finite() or cost < 0:
        raise ValueError("model cost must be non-negative")
    return {
        "schema_version": 2 if output.outcome == "NO" or any(check.plan and check.plan.outcome == "NO" for check in checked_plan_checks) else 1,
        "record_type": "turn_outcome",
        "event_id": "outcome-" + turn_id.removeprefix("turn-"),
        "turn_id": turn_id,
        "snapshot_id": output.snapshot_id,
        "market_id": output.market_id,
        "created_at": created_at,
        "status": status,
        "reason": reason,
        "plan_checks": [check.model_dump() for check in checked_plan_checks],
        "evidence": [record.model_dump() for record in checked_evidence],
        "research": checked_research.model_dump(),
        "proposal": output.model_dump(exclude={"snapshot_id", "market_id"}),
        "review": (
            checked_review.model_dump(exclude={"snapshot_id", "market_id"})
            if checked_review
            else None
        ),
        "policy": checked_policy,
        "trade_plan_event_id": trade_plan_event_id,
        "model_cost_usd": float(cost),
    }


def validate_turn_outcome(value: object) -> dict[str, object]:
    """Validate a serialized outcome and return its canonical payload."""
    if not isinstance(value, Mapping):
        raise ValueError("invalid turn outcome")
    normalized = dict(value)
    normalized.setdefault("plan_checks", [])
    normalized.setdefault("evidence", [])
    normalized.setdefault(
        "research",
        {"status": "unavailable", "reason": "legacy outcome", "query_count": 0},
    )
    if set(normalized) != {
        "schema_version", "record_type", "event_id", "turn_id", "snapshot_id",
        "market_id", "created_at", "status", "reason", "proposal", "review",
        "policy", "trade_plan_event_id", "model_cost_usd", "plan_checks", "evidence", "research",
    }:
        raise ValueError("invalid turn outcome")
    try:
        proposal = dict(normalized["proposal"])
        proposal.update(snapshot_id=normalized["snapshot_id"], market_id=normalized["market_id"])
        review = normalized["review"]
        if review is not None:
            review = dict(review)
            review.update(snapshot_id=normalized["snapshot_id"], market_id=normalized["market_id"])
        expected = build_turn_outcome(
            proposal=proposal,
            review=review,
            policy=normalized["policy"],
            status=normalized["status"],
            reason=normalized["reason"],
            created_at=normalized["created_at"],
            trade_plan_event_id=normalized["trade_plan_event_id"],
            model_cost_usd=str(normalized["model_cost_usd"]),
            plan_checks=normalized["plan_checks"],
            evidence=normalized["evidence"],
            research=normalized["research"],
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid turn outcome") from None
    if normalized.get("schema_version") not in {1, 2} or normalized.get("record_type") != "turn_outcome" or normalized != expected:
        raise ValueError("invalid turn outcome")
    return expected


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


class DraftExitPlan(StrictOutput):
    take_profit_roi: float | None = Field(default=None, ge=0, strict=True)
    stop_loss_roi: float | None = Field(default=None, ge=-1, le=0, strict=True)
    exit_by: str | None = Field(default=None, max_length=MAX_RETRIEVED_AT_LENGTH)
    hold_to_resolution: bool | None = Field(default=None, strict=True)


class ProposalDraft(StrictOutput):
    snapshot_id: str | None = Field(default=None, min_length=1, max_length=200)
    market_id: str | None = Field(default=None, min_length=1, max_length=200)
    action: Literal["trade", "abstain"] | None = None
    probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False, strict=True)
    outcome: Literal["YES", "NO"] = Field(default="YES", exclude_if=lambda value: value == "YES")
    amount: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    citations: list[CitationId] | None = Field(default=None, max_length=10)
    max_entry_price: float | None = Field(default=None, ge=0, le=1, strict=True)
    exit_plan: DraftExitPlan | None = None


class PaperCycleRequest(StrictOutput):
    context: str | None = Field(default=None, max_length=2_000)
    draft: ProposalDraft | None = None

    @field_validator("draft", mode="before")
    @classmethod
    def validate_draft(cls, value: object) -> object:
        if value is not None and len(json.dumps(value, separators=(",", ":"))) > 20_000:
            raise ValueError("draft is too large")
        return value


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


def plan_check_rejection_reason(state: StateMap) -> str:
    checks = state.get(PLAN_CHECKS_KEY, [])
    if not isinstance(checks, list) or not checks:
        return "no plan check was run"
    if not any(
        isinstance(check, Mapping) and check.get("passed") is True
        for check in checks
    ):
        return "no plan check passed"
    return "proposal differs from the last passed plan"


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
    proposal = Proposal(
        snapshot_id=proposal_output.snapshot_id,
        market_id=proposal_output.market_id,
        probability=proposal_output.probability,
        outcome=proposal_output.outcome,
        amount=proposal_output.amount,
        max_entry_price=proposal_output.max_entry_price,
        exit_plan=(
            ExitPlan(**proposal_output.exit_plan.model_dump())
            if proposal_output.exit_plan is not None
            else None
        ),
        citations=tuple(proposal_output.citations),
    )
    review = Review(
        **review_output.model_dump(exclude={"citations"}),
        citations=tuple(review_output.citations),
    )
    try:
        cycle = run_decision_cycle(snapshot, proposal, review, operating)
    except ValueError:
        raise ValueError("paper cycle snapshot identity is inconsistent") from None

    decision = asdict(cycle.decision)
    fill = asdict(cycle.fill) if cycle.fill else None
    checked = (
        state.get(LAST_SUCCESSFUL_PLAN_KEY) == proposal_output.model_dump()
        and state.get(LAST_SUCCESSFUL_SNAPSHOT_KEY) == asdict(snapshot)
    )
    event = (
        json.loads(json.dumps(asdict(cycle.event), sort_keys=True))
        if cycle.event and checked
        else None
    )
    if fill is not None and proposal_output.exit_plan is not None:
        fill["exit_plan"] = proposal_output.exit_plan.model_dump()
    if cycle.event and checked:
        status, reason = "approved", cycle.decision.reason
    elif cycle.event:
        status, reason = "rejected", plan_check_rejection_reason(state)
    elif not review.approved:
        status, reason = "rejected", "review_rejected"
    else:
        status, reason = "rejected", cycle.decision.reason
    report = PaperCycleReportOutput(
        status=status, reason=reason, summary=cycle.summary
    ).model_dump()
    state[PAPER_CYCLE_DECISION_KEY] = decision
    state[PAPER_CYCLE_FILL_KEY] = fill
    state[TRADE_PLAN_READY_KEY] = event
    state[PAPER_CYCLE_REPORT_KEY] = report
    return report
