import re
from dataclasses import asdict, dataclass
from hashlib import sha256
from urllib.parse import urlsplit

from chrysopoeia.trading import validate_polymarket_event_url


@dataclass(frozen=True)
class ContextInterface:
    interface_id: str
    description: str
    use_when: str


@dataclass(frozen=True)
class ContextIdentity:
    scope_key: str
    profile_id: str
    profile_version: int
    manifest_hash: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_BTC_5M_CONTEXT = ContextIdentity(
    "polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown", 1
)


def context_identity_for_source_url(source_url: str) -> ContextIdentity | None:
    try:
        canonical = validate_polymarket_event_url(source_url)
    except ValueError:
        return None
    slug = urlsplit(canonical).path.removeprefix("/event/").lower()
    if (
        slug.startswith("btc-updown-5m-")
        and slug.removeprefix("btc-updown-5m-").isdigit()
    ):
        return _BTC_5M_CONTEXT
    recurring_crypto = re.fullmatch(
        r"([a-z0-9]{2,12})-updown-(\d{1,4}[mhd])-(\d+)", slug
    )
    if recurring_crypto is not None:
        asset, interval, _window = recurring_crypto.groups()
        return ContextIdentity(
            f"polymarket:series:{asset}-updown-{interval}",
            f"crypto.{asset}.usd.{interval}.updown",
            1,
        )
    scope = slug if len(slug) <= 170 else sha256(slug.encode()).hexdigest()
    return ContextIdentity(f"polymarket:event:{scope}", "polymarket.event", 1)


CONTEXT_INTERFACES = (
    ContextInterface(
        "public_web",
        "Current public information with source links.",
        "A market claim depends on recent events or evidence outside the supplied snapshot.",
    ),
)


def discover_context(task: str) -> list[dict[str, str]]:
    """List context interfaces available for a bounded description of the research task."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if len(task) > 1_000:
        raise ValueError("task must not exceed 1,000 characters")
    return [asdict(interface) for interface in CONTEXT_INTERFACES]
