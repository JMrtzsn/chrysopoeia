import json
import math
import os
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chrysopoeia.context import ContextIdentity
from chrysopoeia.trading import validate_polymarket_event_url

REGISTERED_CONTEXT_TOOLS = frozenset(
    {
        "analyze_stock_history",
        "analyze_crypto_history",
        "analyze_polymarket_history",
    }
)
REGISTERED_EVIDENCE_SOURCES = frozenset(
    {"market_snapshot", "public_web", "financial_analysis", "series_history", "outcome_history"}
)
_TOOL_EVIDENCE_SOURCES = {
    "analyze_stock_history": "financial_analysis",
    "analyze_crypto_history": "financial_analysis",
    "analyze_polymarket_history": "series_history",
}
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9:._-]{0,199}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
MIN_FINALIZED_OUTCOMES_FOR_REVISION = 20
MAX_CATALOG_BYTES = 5 * 1024 * 1024


class ProfileError(ValueError):
    """Raised when a local context profile is invalid or its catalog is corrupt."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ContextProfileDraft(StrictModel):
    learning_summary: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=1_500)
    tool_ids: list[str] = Field(max_length=6)
    evidence_sources: list[str] = Field(max_length=5)
    rationale: str = Field(min_length=1, max_length=500)

    @field_validator("learning_summary", "instructions", "rationale")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("profile text is invalid")
        return value.strip()

    @field_validator("tool_ids")
    @classmethod
    def validate_tool_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or not set(values) <= REGISTERED_CONTEXT_TOOLS:
            raise ValueError("profile contains an unregistered tool")
        return values

    @field_validator("evidence_sources")
    @classmethod
    def validate_evidence_sources(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or not set(values) <= REGISTERED_EVIDENCE_SOURCES:
            raise ValueError("profile contains an unregistered evidence source")
        return values

    @model_validator(mode="after")
    def tools_have_evidence_sources(self) -> "ContextProfileDraft":
        if any(
            _TOOL_EVIDENCE_SOURCES[tool_id] not in self.evidence_sources
            for tool_id in self.tool_ids
        ):
            raise ValueError("profile tool is missing its evidence-source declaration")
        return self


class ContextProfileReview(StrictModel):
    approved: bool
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("profile review reason is invalid")
        return value.strip()


class ContextLearningSummary(StrictModel):
    scope_key: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    profile_version: int = Field(ge=1)
    as_of: str = Field(min_length=1, max_length=64)
    lookback_days: int = Field(ge=1, le=365)
    profile_version_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    plan_ready_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    consumer_rejected_count: int = Field(ge=0)
    filled_count: int = Field(ge=0)
    completed_trade_count: int = Field(ge=0)
    winning_trade_count: int = Field(ge=0)
    realized_pnl_usd: float
    outcome_watermark: str | None = Field(default=None, max_length=64)

    @field_validator("scope_key", "profile_id")
    @classmethod
    def validate_context_identifiers(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("context summary identity is invalid")
        return value

    @field_validator("as_of", "outcome_watermark")
    @classmethod
    def validate_summary_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("context summary timestamp is invalid") from None
        if timestamp.tzinfo is None:
            raise ValueError("context summary timestamp needs an offset")
        return value

    @field_validator("realized_pnl_usd")
    @classmethod
    def validate_realized_pnl(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("context summary P&L is invalid")
        return float(value)

    @model_validator(mode="after")
    def validate_counts(self) -> "ContextLearningSummary":
        if (
            self.plan_ready_count + self.abstained_count + self.rejected_count
            != self.decision_count
            or self.filled_count > self.plan_ready_count
            or self.completed_trade_count > self.filled_count
            or self.winning_trade_count > self.completed_trade_count
        ):
            raise ValueError("context summary counts are inconsistent")
        return self


class ContextProfile(StrictModel):
    scope_key: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    profile_version: int = Field(ge=1)
    learning_summary: str = Field(min_length=1, max_length=500)
    instructions: str = Field(min_length=1, max_length=1_500)
    tool_ids: list[str] = Field(max_length=6)
    evidence_sources: list[str] = Field(max_length=5)
    created_at: str = Field(min_length=1, max_length=64)
    sample_count: int = Field(ge=0)
    source_market_id: str | None = Field(default=None, max_length=200)
    source_snapshot_id: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2048)
    source_watermark: str | None = Field(default=None, max_length=64)
    source_summary_hash: str | None = None
    source_summary: ContextLearningSummary | None = None
    proposal_rationale: str = Field(min_length=1, max_length=500)
    approved_by: str = Field(min_length=1, max_length=100)
    approval_reason: str = Field(min_length=1, max_length=500)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("scope_key", "profile_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("profile identity is invalid")
        return value

    @field_validator("learning_summary", "instructions", "proposal_rationale", "approval_reason")
    @classmethod
    def validate_profile_text(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("profile text is invalid")
        return value.strip()

    @field_validator("tool_ids")
    @classmethod
    def validate_profile_tools(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or not set(values) <= REGISTERED_CONTEXT_TOOLS:
            raise ValueError("profile contains an unregistered tool")
        return values

    @field_validator("evidence_sources")
    @classmethod
    def validate_profile_sources(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or not set(values) <= REGISTERED_EVIDENCE_SOURCES:
            raise ValueError("profile contains an unregistered evidence source")
        return values

    @field_validator("created_at", "source_watermark")
    @classmethod
    def validate_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("profile timestamp is invalid") from None
        if parsed.tzinfo is None:
            raise ValueError("profile timestamp requires an offset")
        return value

    @field_validator("source_market_id", "source_snapshot_id")
    @classmethod
    def validate_source_ids(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip()
            or len(value) > 200
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("profile source identity is invalid")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                validate_polymarket_event_url(value)
            except ValueError:
                raise ValueError("profile source URL is invalid") from None
        return value

    @field_validator("source_summary_hash")
    @classmethod
    def validate_summary_hash(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST.fullmatch(value) is None:
            raise ValueError("profile summary hash is invalid")
        return value

    @model_validator(mode="after")
    def validate_manifest_hash(self) -> "ContextProfile":
        if any(
            _TOOL_EVIDENCE_SOURCES[tool_id] not in self.evidence_sources
            for tool_id in self.tool_ids
        ):
            raise ValueError("profile tool is missing its evidence-source declaration")
        if self.manifest_hash != profile_manifest_hash(
            self.scope_key,
            self.profile_id,
            self.profile_version,
            self.learning_summary,
            self.instructions,
            self.tool_ids,
            self.evidence_sources,
        ):
            raise ValueError("profile manifest hash does not match")
        if (self.source_summary is None) != (self.source_summary_hash is None):
            raise ValueError("profile summary and its hash must be stored together")
        source_fields = (self.source_market_id, self.source_snapshot_id, self.source_url)
        if any(value is not None for value in source_fields) and any(
            value is None for value in source_fields
        ):
            raise ValueError("profile source identities must be recorded together")
        if self.source_summary is not None and (
            self.source_summary.scope_key != self.scope_key
            or self.source_summary.profile_id != self.profile_id
            or self.source_summary.profile_version != self.profile_version - 1
            or self.source_summary.completed_trade_count != self.sample_count
            or self.source_summary.outcome_watermark != self.source_watermark
            or self.source_summary_hash is None
            or self.source_summary_hash != context_learning_summary_hash(self.source_summary)
        ):
            raise ValueError("profile outcome summary provenance is inconsistent")
        return self

    @property
    def identity(self) -> ContextIdentity:
        return ContextIdentity(
            self.scope_key, self.profile_id, self.profile_version, self.manifest_hash
        )


def profile_manifest_hash(
    scope_key: str,
    profile_id: str,
    profile_version: int,
    learning_summary: str,
    instructions: str,
    tool_ids: list[str] | tuple[str, ...],
    evidence_sources: list[str] | tuple[str, ...],
) -> str:
    manifest = {
        "scope_key": scope_key,
        "profile_id": profile_id,
        "profile_version": profile_version,
        "learning_summary": learning_summary,
        "instructions": instructions,
        "tool_ids": list(tool_ids),
        "evidence_sources": list(evidence_sources),
    }
    content = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return sha256(content.encode()).hexdigest()


def context_learning_summary_hash(summary: ContextLearningSummary) -> str:
    content = json.dumps(summary.model_dump(), sort_keys=True, separators=(",", ":"))
    return sha256(content.encode()).hexdigest()


def build_context_profile(
    identity: ContextIdentity,
    draft: ContextProfileDraft,
    *,
    created_at: str,
    sample_count: int = 0,
    source_watermark: str | None = None,
    source_summary_hash: str | None = None,
    source_summary: ContextLearningSummary | None = None,
    source_market_id: str | None = None,
    source_snapshot_id: str | None = None,
    source_url: str | None = None,
    approved_by: str,
    approval_reason: str,
) -> ContextProfile:
    values = {
        "scope_key": identity.scope_key,
        "profile_id": identity.profile_id,
        "profile_version": identity.profile_version,
        "learning_summary": draft.learning_summary,
        "instructions": draft.instructions,
        "tool_ids": draft.tool_ids,
        "evidence_sources": draft.evidence_sources,
        "created_at": created_at,
        "sample_count": sample_count,
        "source_market_id": source_market_id,
        "source_snapshot_id": source_snapshot_id,
        "source_url": source_url,
        "source_watermark": source_watermark,
        "source_summary_hash": source_summary_hash,
        "source_summary": source_summary.model_dump() if source_summary is not None else None,
        "proposal_rationale": draft.rationale,
        "approved_by": approved_by,
        "approval_reason": approval_reason,
    }
    return ContextProfile(
        **values,
        manifest_hash=profile_manifest_hash(
            identity.scope_key,
            identity.profile_id,
            identity.profile_version,
            draft.learning_summary,
            draft.instructions,
            draft.tool_ids,
            draft.evidence_sources,
        ),
    )


def bundled_profiles() -> tuple[ContextProfile, ...]:
    btc_draft = ContextProfileDraft(
        learning_summary="No finalized Consumer outcomes are attached to this bundled profile.",
        instructions=(
            "For BTC/USD 5-minute Up/Down markets, ground estimates in the current "
            "window and recent 1-minute BTC/USD price behavior. Use resolved sibling "
            "windows as descriptive base-rate evidence, not as a guaranteed forecast."
        ),
        tool_ids=["analyze_crypto_history", "analyze_polymarket_history"],
        evidence_sources=["market_snapshot", "public_web", "financial_analysis", "series_history", "outcome_history"],
        rationale="Bundled BTC five-minute market context.",
    )
    event_draft = ContextProfileDraft(
        learning_summary="No finalized pair-specific outcomes have been recorded yet.",
        instructions=(
            "Analyze this exact Polymarket event and its resolution rules. Use the "
            "canonical snapshot and bounded public evidence; do not assume facts "
            "not supported by citations."
        ),
        tool_ids=[],
        evidence_sources=["market_snapshot", "public_web", "outcome_history"],
        rationale="Bundled generic event context template.",
    )
    return (
        build_context_profile(
            ContextIdentity(
                "polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown", 1
            ),
            btc_draft,
            created_at="2026-10-21T00:00:00+00:00",
            approved_by="bundled",
            approval_reason="Curated Harness profile.",
        ),
        build_context_profile(
            ContextIdentity(
                "polymarket:profile-template:generic-event", "polymarket.event", 1
            ),
            event_draft,
            created_at="2026-10-21T00:00:00+00:00",
            approved_by="bundled",
            approval_reason="Curated generic Polymarket event template.",
        ),
    )


BUNDLED_CONTEXT_PROFILES = bundled_profiles()


def bundled_profile_for_identity(identity: ContextIdentity) -> ContextProfile | None:
    if identity.profile_id == "polymarket.event" and identity.scope_key.startswith(
        "polymarket:event:"
    ):
        template = next(
            profile
            for profile in BUNDLED_CONTEXT_PROFILES
            if profile.scope_key == "polymarket:profile-template:generic-event"
        )
        return build_context_profile(
            ContextIdentity(identity.scope_key, identity.profile_id, 1),
            ContextProfileDraft(
                learning_summary=template.learning_summary,
                instructions=template.instructions,
                tool_ids=template.tool_ids,
                evidence_sources=template.evidence_sources,
                rationale=template.proposal_rationale,
            ),
            created_at=template.created_at,
            approved_by="bundled",
            approval_reason=template.approval_reason,
        )
    return next(
        (
            profile
            for profile in BUNDLED_CONTEXT_PROFILES
            if (profile.scope_key, profile.profile_id)
            == (identity.scope_key, identity.profile_id)
        ),
        None,
    )
class ContextCatalog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        if self.path.stat().st_size > MAX_CATALOG_BYTES:
            raise ProfileError("local context catalog exceeds its size limit")
        records: list[dict[str, object]] = []
        latest_versions: dict[tuple[str, str], tuple[int, str]] = {}
        try:
            text = self.path.read_text(encoding="utf-8")
            if text and not text.endswith("\n"):
                raise ValueError("context catalog has an incomplete final record")
            for line in text.splitlines():
                if not line.strip():
                    continue
                record = json.loads(
                    line,
                    object_pairs_hook=self._pairs,
                    parse_constant=self._constant,
                )
                if not isinstance(record, dict):
                    raise ValueError
                if record.get("record_type") == "context_profile":
                    if set(record) != {"schema_version", "record_type", "profile"} or record.get("schema_version") != 1:
                        raise ValueError
                    profile = ContextProfile.model_validate(record["profile"])
                    key = (profile.scope_key, profile.profile_id)
                    previous = latest_versions.get(key)
                    if previous is not None and (
                        profile.profile_version != previous[0] + 1
                        or profile.manifest_hash == previous[1]
                    ):
                        raise ValueError("context profile versions are not monotonic")
                    latest_versions[key] = (profile.profile_version, profile.manifest_hash)
                elif record.get("record_type") == "profile_iteration":
                    self._validate_iteration(record)
                else:
                    raise ValueError
                records.append(record)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ProfileError("local context catalog is corrupt or unavailable") from None
        return records

    @staticmethod
    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate catalog key")
            result[key] = value
        return result

    @staticmethod
    def _constant(_value: str) -> object:
        raise ValueError("JSON constants are prohibited")

    @staticmethod
    def _validate_iteration(record: dict[str, object]) -> None:
        if set(record) != {
            "schema_version", "record_type", "scope_key", "profile_id",
            "profile_version", "summary_hash", "outcome_watermark", "decision",
            "recorded_at",
        }:
            raise ValueError("invalid profile iteration record")
        if record.get("schema_version") != 1 or record.get("decision") not in {
            "rejected", "unchanged", "approved"
        }:
            raise ValueError("invalid profile iteration record")
        scope_key = record.get("scope_key")
        profile_id = record.get("profile_id")
        profile_version = record.get("profile_version")
        summary_hash = record.get("summary_hash")
        if not isinstance(scope_key, str) or _IDENTIFIER.fullmatch(scope_key) is None:
            raise ValueError("invalid profile iteration record")
        if not isinstance(profile_id, str) or _IDENTIFIER.fullmatch(profile_id) is None:
            raise ValueError("invalid profile iteration record")
        if (
            not isinstance(profile_version, int)
            or isinstance(profile_version, bool)
            or profile_version < 1
        ):
            raise ValueError("invalid profile iteration record")
        if not isinstance(summary_hash, str) or _DIGEST.fullmatch(summary_hash) is None:
            raise ValueError("invalid profile iteration record")
        for key in ("outcome_watermark", "recorded_at"):
            value = record.get(key)
            if not isinstance(value, str):
                raise ValueError("invalid profile iteration timestamp")
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("invalid profile iteration timestamp")

    def latest(self, scope_key: str, profile_id: str) -> ContextProfile | None:
        profiles = [
            profile
            for profile in self.profiles()
            if profile.scope_key == scope_key and profile.profile_id == profile_id
        ]
        return max(profiles, key=lambda profile: profile.profile_version, default=None)

    def profiles(self) -> list[ContextProfile]:
        return [
            ContextProfile.model_validate(record["profile"])
            for record in self._records()
            if record.get("record_type") == "context_profile"
        ]

    def iterations(self) -> list[dict[str, object]]:
        return [
            record
            for record in self._records()
            if record.get("record_type") == "profile_iteration"
        ]

    def was_evaluated(
        self,
        scope_key: str,
        profile_id: str,
        profile_version: int,
        summary_hash: str,
        outcome_watermark: str | None = None,
    ) -> bool:
        records = self._records()
        return any(
            record.get("scope_key") == scope_key
            and record.get("profile_id") == profile_id
            and record.get("profile_version") == profile_version
            and (
                record.get("summary_hash") == summary_hash
                or (
                    outcome_watermark is not None
                    and record.get("outcome_watermark") == outcome_watermark
                )
            )
            for record in records
            if record.get("record_type") == "profile_iteration"
        ) or any(
            profile.scope_key == scope_key
            and profile.profile_id == profile_id
            and profile.profile_version == profile_version
            and (
                profile.source_summary_hash == summary_hash
                or (
                    outcome_watermark is not None
                    and profile.source_watermark == outcome_watermark
                )
            )
            for profile in (
                ContextProfile.model_validate(record["profile"])
                for record in records
                if record.get("record_type") == "context_profile"
            )
        )

    def record_iteration(
        self,
        *,
        scope_key: str,
        profile_id: str,
        profile_version: int,
        summary_hash: str,
        outcome_watermark: str,
        decision: Literal["rejected", "unchanged", "approved"],
        recorded_at: str,
    ) -> None:
        record: dict[str, object] = {
            "schema_version": 1,
            "record_type": "profile_iteration",
            "scope_key": scope_key,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "summary_hash": summary_hash,
            "outcome_watermark": outcome_watermark,
            "decision": decision,
            "recorded_at": recorded_at,
        }
        self._validate_iteration(record)
        if self.was_evaluated(
            scope_key, profile_id, profile_version, summary_hash, outcome_watermark
        ):
            return
        self._append(record)

    def record_profile(self, profile: ContextProfile, *, previous_version: int) -> None:
        if profile.profile_version != previous_version + 1:
            raise ProfileError("context profile version is not the next version")
        existing = next(
            (
                item
                for item in self.profiles()
                if (item.scope_key, item.profile_id, item.profile_version)
                == (profile.scope_key, profile.profile_id, profile.profile_version)
            ),
            None,
        )
        if existing is not None:
            if existing.manifest_hash == profile.manifest_hash:
                return
            raise ProfileError("context profile version already has different content")
        latest = self.latest(profile.scope_key, profile.profile_id)
        if latest is not None and latest.profile_version != previous_version:
            raise ProfileError("context profile changed while a revision was being approved")
        self._append(
            {
                "schema_version": 1,
                "record_type": "context_profile",
                "profile": profile.model_dump(),
            }
        )

    def _append(self, record: dict[str, object]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size + len(data) > MAX_CATALOG_BYTES:
            raise ProfileError("local context catalog would exceed its size limit")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if os.write(descriptor, data) != len(data):
                raise ProfileError("context profile catalog append was incomplete")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def local_catalog_path() -> Path:
    configured = os.environ.get("CHRYSOPOEIA_CONTEXT_CATALOG")
    if configured:
        return Path(configured).expanduser()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    root = Path(xdg_state).expanduser() if xdg_state else Path.home() / ".local" / "share"
    return root / "chrysopoeia" / "context_profiles.jsonl"
