"""Read-only public Polymarket market-data adapter."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from chrysopoeia.trading import (
    BookLevel,
    MarketSnapshot,
    market_snapshot_identity,
    validate_polymarket_event_url,
)


API_HOST = "gamma-api.polymarket.com"
CLOB_HOST = "clob.polymarket.com"
WEB_HOSTS = {"polymarket.com", "www.polymarket.com"}
MAX_BOOK_AGE = timedelta(minutes=5)
MAX_METADATA_FUTURE_SKEW = timedelta(seconds=5)
MAX_BOOK_LEVELS = 50
DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024
Fetch = Callable[[str, float, int], bytes]


class PolymarketError(ValueError):
    """A safe failure while loading public Polymarket market data."""


@dataclass(frozen=True)
class MarketCandidate:
    market_id: str
    question: str
    end_time: str
    source_url: str
    capture: str

    def as_dict(self) -> dict[str, str]:
        return {
            "market_id": self.market_id,
            "question": self.question,
            "end_time": self.end_time,
            "source_url": self.source_url,
            "capture": self.capture,
        }


@dataclass(frozen=True)
class MarketResolution:
    market_id: str
    resolution: str
    resolved_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "market_id": self.market_id,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
        }


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


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolymarketError(f"Polymarket adapter {name} is missing or invalid")
    return value.strip()


def _json_body(body: object, max_bytes: int) -> dict[str, object]:
    if not isinstance(body, bytes):
        raise PolymarketError("Polymarket adapter fetch returned invalid data")
    if len(body) > max_bytes:
        raise PolymarketError("Polymarket adapter response is too large")
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise PolymarketError("Polymarket adapter response is not valid JSON") from None
    if not isinstance(data, dict):
        raise PolymarketError("Polymarket adapter response has invalid schema")
    return data


def _fetch_json(url: str, timeout: float, max_bytes: int, fetch: Fetch) -> dict[str, object]:
    host = urlparse(url).hostname
    if host not in {API_HOST, CLOB_HOST}:
        raise PolymarketError("Polymarket adapter endpoint is not allowlisted")
    try:
        body = fetch(url, timeout, max_bytes)
    except PolymarketError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError):
        raise PolymarketError("Polymarket adapter could not fetch public market data") from None
    return _json_body(body, max_bytes)


def _fetch_json_list(
    url: str, timeout: float, max_bytes: int, fetch: Fetch
) -> list[object]:
    if urlparse(url).hostname != API_HOST:
        raise PolymarketError("Polymarket adapter endpoint is not allowlisted")
    try:
        body = fetch(url, timeout, max_bytes)
    except PolymarketError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError):
        raise PolymarketError(
            "Polymarket adapter could not fetch public market data"
        ) from None
    if not isinstance(body, bytes):
        raise PolymarketError("Polymarket adapter fetch returned invalid data")
    if len(body) > max_bytes:
        raise PolymarketError("Polymarket adapter response is too large")
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise PolymarketError("Polymarket adapter response is not valid JSON") from None
    if not isinstance(data, list):
        raise PolymarketError("Polymarket adapter response has invalid schema")
    return data


def _candidate(data: object, current: datetime) -> tuple[MarketCandidate, datetime] | None:
    try:
        if not isinstance(data, dict):
            return None
        identifier = data.get("id")
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
            return None
        market_id = str(identifier)
        if (
            len(market_id) > 100
            or not market_id.isascii()
            or not market_id.isdigit()
            or market_id.startswith("0")
        ):
            return None
        if (
            data.get("active") is not True
            or data.get("closed") is not False
            or data.get("acceptingOrders") is not True
        ):
            return None
        for name in ("outcomes", "clobTokenIds"):
            value = data.get(name)
            if isinstance(value, str) and len(value) > 10_000:
                return None
        if _list_field(data.get("outcomes"), "outcomes") != ["Yes", "No"]:
            return None
        tokens = _list_field(data.get("clobTokenIds"), "token")
        if (
            len(tokens) != 2
            or len(set(tokens)) != 2
            or any(
                not isinstance(token, str)
                or not token.strip()
                or len(token) > 500
                for token in tokens
            )
        ):
            return None
        question = data.get("question")
        if (
            not isinstance(question, str)
            or not question.strip()
            or len(question) > 500
            or any(ord(character) < 32 or ord(character) == 127 for character in question)
        ):
            return None
        end = None
        for value in (data.get("endDate"), data.get("endDateIso")):
            try:
                end = _timestamp(value)
                break
            except PolymarketError:
                pass
        if end is None:
            return None
        if end <= current:
            return None
        source_url = None
        for slug in (data.get("eventSlug"), data.get("slug")):
            if not isinstance(slug, str) or len(slug) > 500:
                continue
            candidate_url = f"https://polymarket.com/event/{slug}"
            try:
                source_url = validate_polymarket_event_url(candidate_url)
                break
            except ValueError:
                pass
        if source_url is None:
            return None
        candidate = MarketCandidate(
            market_id,
            question.strip(),
            end.isoformat(),
            source_url,
            market_id,
        )
        return candidate, end
    except (PolymarketError, TypeError, ValueError):
        return None


def discover_markets(
    *,
    limit: int = 10,
    now: datetime | None = None,
    fetch: Fetch = _fetch,
) -> tuple[MarketCandidate, ...]:
    """Discover at most 20 eligible markets from a bounded public Gamma scan."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise PolymarketError("Polymarket discovery limit must be between 1 and 20")
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PolymarketError("Polymarket adapter current time must include a UTC offset")
    current = current.astimezone(timezone.utc)
    found: dict[str, tuple[MarketCandidate, datetime]] = {}
    for offset in (0, 25, 50):
        endpoint = (
            f"https://{API_HOST}/markets?active=true&closed=false"
            f"&limit=25&offset={offset}"
        )
        page = _fetch_json_list(
            endpoint, DEFAULT_TIMEOUT, DEFAULT_MAX_RESPONSE_BYTES, fetch
        )
        for item in page[:25]:
            parsed = _candidate(item, current)
            if parsed is None:
                continue
            candidate, end = parsed
            previous = found.get(candidate.market_id)
            if previous is not None and previous[0] != candidate:
                raise PolymarketError(
                    "Polymarket discovery contains a conflicting duplicate market"
                )
            found[candidate.market_id] = (candidate, end)
        if len(page) < 25:
            break
    ranked = sorted(found.values(), key=lambda item: (item[1], int(item[0].market_id)))
    return tuple(candidate for candidate, _ in ranked[:limit])


def _book_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.isdigit():
        raise PolymarketError("Polymarket adapter book timestamp is missing or invalid")
    try:
        return datetime.fromtimestamp(int(value) / 1_000, timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise PolymarketError("Polymarket adapter book timestamp is missing or invalid") from None


def _levels(value: object, name: str, *, required: bool) -> tuple[BookLevel, ...]:
    if not isinstance(value, list):
        raise PolymarketError(f"Polymarket adapter {name} list is malformed")
    if required and not value:
        raise PolymarketError("Polymarket adapter book has empty asks")
    levels = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"price", "size"}
            or not isinstance(item["price"], str)
            or not isinstance(item["size"], str)
        ):
            raise PolymarketError("Polymarket adapter book level is malformed")
        try:
            level = BookLevel(float(item["price"]), float(item["size"]))
        except (TypeError, ValueError):
            raise PolymarketError("Polymarket adapter book level is malformed") from None
        levels.append(level)
    return tuple(levels)


def load_market_resolution(
    market: str,
    *,
    now: datetime | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    fetch: Fetch = _fetch,
) -> MarketResolution:
    """Load one venue-derived canonical resolution from public Gamma data."""
    endpoint, _expected, _uses_slug = _endpoint(market)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 10:
        raise PolymarketError("Polymarket adapter timeout must be between 0 and 10 seconds")
    if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or not 0 < max_response_bytes <= 1_000_000:
        raise PolymarketError("Polymarket adapter response limit must be between 1 and 1,000,000 bytes")
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PolymarketError("Polymarket adapter current time must include a UTC offset")
    data = _fetch_json(endpoint, float(timeout), max_response_bytes, fetch)
    identifier = data.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).isdigit():
        raise PolymarketError("Polymarket adapter response has invalid market ID schema")
    market_id = str(identifier)
    if data.get("closed") is not True:
        raise PolymarketError("Polymarket adapter market has not resolved yet")
    prices = data.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except ValueError:
            raise PolymarketError("Polymarket adapter outcome prices are malformed") from None
    if not isinstance(prices, list) or len(prices) != 2 or not all(
        isinstance(price, (str, int, float)) for price in prices
    ):
        raise PolymarketError("Polymarket adapter outcome prices are malformed")
    try:
        fractions = [float(price) for price in prices]
    except (TypeError, ValueError):
        raise PolymarketError("Polymarket adapter outcome prices are malformed") from None
    if any(not 0 <= fraction <= 1 for fraction in fractions):
        raise PolymarketError("Polymarket adapter outcome prices are out of range")
    resolved = sum(1 for fraction in fractions if fraction >= 0.999)
    if resolved != 1:
        raise PolymarketError("Polymarket adapter market has no dominant resolution")
    resolution = "resolved_yes" if fractions[0] >= 0.999 else "resolved_no"
    return MarketResolution(
        market_id,
        resolution,
        current.astimezone(timezone.utc).isoformat(),
    )


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
    paper_fee_rate: float,
    paper_fee_source: str,
) -> MarketSnapshot:
    """Load metadata and YES depth into one canonical market-data snapshot."""
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
    if not isinstance(paper_fee_source, str) or len(paper_fee_source) > 200:
        raise PolymarketError("Polymarket adapter paper fee is invalid")
    try:
        MarketSnapshot(
            "validation", "validation", 0.5, bankroll, market_exposure,
            total_exposure, fee_rate=paper_fee_rate, fee_source=paper_fee_source,
        )
    except (TypeError, ValueError):
        raise PolymarketError("Polymarket adapter paper fee is invalid") from None

    data = _fetch_json(endpoint, float(timeout), max_response_bytes, fetch)

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

    current_utc = current.astimezone(timezone.utc)
    updated = _timestamp(data.get("updatedAt"))
    if updated - current_utc > MAX_METADATA_FUTURE_SKEW:
        raise PolymarketError("Polymarket adapter market timestamp is in the future")
    question = _text(data.get("question"), "question")
    rules = _text(data.get("description"), "resolution rules")
    end = _timestamp(data["endDate"] if "endDate" in data else data.get("endDateIso"))
    if end <= current_utc:
        raise PolymarketError("Polymarket adapter end time must be in the future")
    event_slug = data.get("eventSlug") or data.get("slug")
    source_slug = _text(event_slug, "event slug")
    if not source_slug.replace("-", "").isalnum():
        raise PolymarketError("Polymarket adapter event slug is invalid")
    source_url = f"https://polymarket.com/event/{source_slug}"
    yes_token = tokens[0]
    book_endpoint = f"https://{CLOB_HOST}/book?token_id={quote(yes_token, safe='')}"
    book = _fetch_json(book_endpoint, float(timeout), max_response_bytes, fetch)
    if book.get("asset_id") != yes_token:
        raise PolymarketError("Polymarket adapter book token does not match the YES token")
    book_time = _book_timestamp(book.get("timestamp"))
    book_age = current_utc - book_time
    if book_age < timedelta(0) or book_age > MAX_BOOK_AGE:
        raise PolymarketError("Polymarket adapter book is stale")
    asks = tuple(sorted(
        _levels(book.get("asks"), "asks", required=True),
        key=lambda level: level.price,
    )[:MAX_BOOK_LEVELS])
    bids = _levels(book.get("bids", []), "bids", required=False)
    if bids and max(level.price for level in bids) >= asks[0].price:
        raise PolymarketError("Polymarket adapter book is crossed")
    price = asks[0].price

    try:
        snapshot = MarketSnapshot(
            snapshot_id or "validation",
            market_id, price, bankroll, market_exposure, total_exposure,
            question, rules, end.isoformat(), current_utc.isoformat(), source_url,
            yes_token, asks, paper_fee_rate, paper_fee_source, book_time.isoformat(),
        )
        if snapshot_id is None:
            snapshot = MarketSnapshot(
                market_snapshot_identity(snapshot), market_id, price, bankroll,
                market_exposure, total_exposure, question, rules, end.isoformat(),
                current_utc.isoformat(), source_url, yes_token, asks, paper_fee_rate,
                paper_fee_source, book_time.isoformat(),
            )
        return snapshot
    except ValueError as exc:
        raise PolymarketError(f"Polymarket adapter cannot create snapshot: {exc}") from exc
