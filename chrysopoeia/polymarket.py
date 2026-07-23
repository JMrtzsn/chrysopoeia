"""Read-only public Polymarket market-data adapter."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from chrysopoeia.trading import MarketSnapshot


API_HOST = "gamma-api.polymarket.com"
WEB_HOSTS = {"polymarket.com", "www.polymarket.com"}
MAX_AGE = timedelta(minutes=5)
DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 256_000
Fetch = Callable[[str, float, int], bytes]


class PolymarketError(ValueError):
    """A safe failure while loading public Polymarket market data."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
        return None


def _fetch(url: str, timeout: float, max_bytes: int) -> bytes:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "chrysopoeia/0.1"})
    try:
        with build_opener(_NoRedirects()).open(request, timeout=timeout) as response:
            return response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise PolymarketError("Polymarket adapter could not fetch public market data") from None


def _endpoint(value: str) -> tuple[str, str, bool]:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PolymarketError("Polymarket adapter requires a non-blank market URL or identifier")
    if "://" not in value:
        if not value.isdigit():
            raise PolymarketError("Polymarket adapter market identifier must contain only digits")
        return f"https://{API_HOST}/markets/{quote(value)}", value, False

    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise PolymarketError("Polymarket adapter URL has an invalid port") from exc
    if parsed.scheme != "https" or parsed.hostname not in WEB_HOSTS or port is not None or parsed.username is not None or parsed.password is not None:
        raise PolymarketError("Polymarket adapter accepts only public polymarket.com HTTPS URLs")
    if parsed.query or parsed.fragment:
        raise PolymarketError("Polymarket adapter market URL must not contain a query or fragment")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "event" or not all(part.replace("-", "").isalnum() for part in parts):
        raise PolymarketError("Polymarket adapter URL must identify a Polymarket event market")
    slug = parts[-1]
    return f"https://{API_HOST}/markets/slug/{quote(slug)}", slug, True


def _list_field(value: object, name: str) -> list[object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise PolymarketError(f"Polymarket adapter has malformed {name} schema") from None
    if not isinstance(value, list):
        raise PolymarketError(f"Polymarket adapter has malformed {name} schema")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PolymarketError("Polymarket adapter market timestamp is missing or invalid")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PolymarketError("Polymarket adapter market timestamp is missing or invalid") from None
    if timestamp.tzinfo is None:
        raise PolymarketError("Polymarket adapter market timestamp must include a UTC offset")
    return timestamp.astimezone(timezone.utc)


def load_market_snapshot(
    market: str,
    bankroll: float,
    market_exposure: float,
    total_exposure: float,
    *,
    snapshot_id: str | None = None,
    now: datetime | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    fetch: Fetch = _fetch,
) -> MarketSnapshot:
    """Load one active binary market's executable YES ask into a validated snapshot."""
    endpoint, expected, uses_slug = _endpoint(market)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 10:
        raise PolymarketError("Polymarket adapter timeout must be between 0 and 10 seconds")
    if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or not 0 < max_response_bytes <= 1_000_000:
        raise PolymarketError("Polymarket adapter response limit must be between 1 and 1,000,000 bytes")
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PolymarketError("Polymarket adapter current time must include a UTC offset")
    if snapshot_id is not None and (not isinstance(snapshot_id, str) or not snapshot_id.strip()):
        raise PolymarketError("Polymarket adapter snapshot ID must be a non-blank string")

    try:
        body = fetch(endpoint, float(timeout), max_response_bytes)
    except PolymarketError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError):
        raise PolymarketError("Polymarket adapter could not fetch public market data") from None
    if not isinstance(body, bytes):
        raise PolymarketError("Polymarket adapter fetch returned invalid data")
    if len(body) > max_response_bytes:
        raise PolymarketError("Polymarket adapter response is too large")
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise PolymarketError("Polymarket adapter response is not valid JSON") from None
    if not isinstance(data, dict):
        raise PolymarketError("Polymarket adapter response has invalid schema")

    identifier = data.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).isdigit():
        raise PolymarketError("Polymarket adapter response has invalid market ID schema")
    market_id = str(identifier)
    if (uses_slug and data.get("slug") != expected) or (not uses_slug and market_id != expected):
        raise PolymarketError("Polymarket adapter response does not match the requested market")
    if data.get("closed") is not False:
        raise PolymarketError("Polymarket adapter market is closed")
    if data.get("active") is not True:
        raise PolymarketError("Polymarket adapter market is inactive")
    if data.get("acceptingOrders") is not True:
        raise PolymarketError("Polymarket adapter market is not accepting orders")

    outcomes = _list_field(data.get("outcomes"), "outcomes")
    if len(outcomes) != 2:
        raise PolymarketError("Polymarket adapter supports only binary markets")
    if outcomes != ["Yes", "No"]:
        raise PolymarketError("Polymarket adapter requires YES and NO outcomes in canonical order")
    tokens = _list_field(data.get("clobTokenIds"), "token")
    if len(tokens) != 2 or any(not isinstance(token, str) or not token for token in tokens) or tokens[0] == tokens[1]:
        raise PolymarketError("Polymarket adapter has unsupported token structure")

    updated = _timestamp(data.get("updatedAt"))
    age = current.astimezone(timezone.utc) - updated
    if age < timedelta(0) or age > MAX_AGE:
        raise PolymarketError("Polymarket adapter market data is stale")
    try:
        price = float(data.get("bestAsk"))
    except (TypeError, ValueError):
        raise PolymarketError("Polymarket adapter executable YES price is missing or invalid") from None
    if isinstance(data.get("bestAsk"), bool) or not isfinite(price) or not 0 < price < 1:
        raise PolymarketError("Polymarket adapter executable YES price is missing or invalid")

    identity = f"{market_id}|{updated.isoformat()}|{price}|{bankroll}|{market_exposure}|{total_exposure}"
    generated_id = "polymarket-" + sha256(identity.encode()).hexdigest()[:24]
    try:
        return MarketSnapshot(snapshot_id if snapshot_id is not None else generated_id, market_id, price, bankroll, market_exposure, total_exposure)
    except ValueError as exc:
        raise PolymarketError(f"Polymarket adapter cannot create snapshot: {exc}") from exc
