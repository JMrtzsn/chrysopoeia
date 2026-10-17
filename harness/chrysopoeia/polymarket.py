"""Read-only public Polymarket market-data adapter."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
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
DISCOVERY_HORIZON = timedelta(days=30)
DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024
Fetch = Callable[[str, float, int], bytes]
# First outcome is the "YES side" the harness buys; Up/Down markets map Up to it.
BINARY_OUTCOMES = (["Yes", "No"], ["Up", "Down"])


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


@dataclass(frozen=True)
class SeriesOutcome:
    market_id: str
    slug: str
    question: str
    start_time: datetime
    end_time: datetime
    resolved_at: datetime
    up_won: bool
    up_token_id: str
    down_token_id: str
    resolution_source: str


@dataclass(frozen=True)
class PolymarketSeriesHistory:
    series_id: str
    series_slug: str
    source_url: str
    outcomes: tuple[SeriesOutcome, ...]


@dataclass(frozen=True)
class HistoricalPrice:
    timestamp: int
    price: float


@dataclass(frozen=True)
class ResolvedMarket:
    market_id: str
    slug: str
    end_time: datetime
    yes_won: bool | None
    yes_token_id: str


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
        if _list_field(data.get("outcomes"), "outcomes") not in BINARY_OUTCOMES:
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
        query = urlencode(
            {
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
                "end_date_min": current.isoformat(),
                "end_date_max": (current + DISCOVERY_HORIZON).isoformat(),
                "limit": 25,
                "offset": offset,
            }
        )
        endpoint = f"https://{API_HOST}/markets?{query}"
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
    return tuple(candidate for candidate, _ in found.values())[:limit]


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


def load_resolved_market(
    market_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    fetch: Fetch = _fetch,
) -> ResolvedMarket:
    """Load any binary market's first-outcome ("YES side") token and resolution.

    `yes_won` is None while the market is open or not dominantly resolved.
    """
    if not isinstance(market_id, str) or not market_id.isdigit() or len(market_id) > 100:
        raise PolymarketError("Polymarket market ID is invalid")
    data = _fetch_json(
        f"https://{API_HOST}/markets/{quote(market_id)}",
        float(timeout),
        max_response_bytes,
        fetch,
    )
    if str(data.get("id")) != market_id:
        raise PolymarketError("Polymarket adapter response does not match the requested market")
    if _list_field(data.get("outcomes"), "outcomes") not in BINARY_OUTCOMES:
        raise PolymarketError("Polymarket market is not a supported binary market")
    tokens = _list_field(data.get("clobTokenIds"), "token")
    if len(tokens) != 2 or not all(isinstance(t, str) and t.isdigit() for t in tokens):
        raise PolymarketError("Polymarket market has unsupported token structure")
    yes_won: bool | None = None
    if data.get("closed") is True:
        try:
            prices = [float(p) for p in _list_field(data.get("outcomePrices"), "outcome prices")]
        except (TypeError, ValueError):
            prices = []
        if len(prices) == 2 and prices[0] >= 0.999 and prices[1] <= 0.001:
            yes_won = True
        elif len(prices) == 2 and prices[0] <= 0.001 and prices[1] >= 0.999:
            yes_won = False
    return ResolvedMarket(
        market_id,
        _text(data.get("slug"), "market slug"),
        _timestamp(data.get("endDate")),
        yes_won,
        tokens[0],
    )


def load_series_history(
    event_url: str,
    *,
    limit: int = 10,
    now: datetime | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    fetch: Fetch = _fetch,
) -> PolymarketSeriesHistory:
    """Load a bounded list of resolved sibling outcomes for a recurring event."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise PolymarketError("Polymarket series history limit must be between 1 and 20")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 10:
        raise PolymarketError("Polymarket adapter timeout must be between 0 and 10 seconds")
    if not isinstance(max_response_bytes, int) or isinstance(max_response_bytes, bool) or not 0 < max_response_bytes <= 1_000_000:
        raise PolymarketError("Polymarket adapter response limit must be between 1 and 1,000,000 bytes")
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PolymarketError("Polymarket adapter current time must include a UTC offset")
    current = current.astimezone(timezone.utc)
    _, event_slug, uses_slug = _endpoint(event_url)
    if not uses_slug:
        raise PolymarketError("Polymarket series history requires an event URL")

    event_url_api = f"https://{API_HOST}/events?{urlencode({'slug': event_slug})}"
    event_matches = _fetch_json_list(
        event_url_api, float(timeout), max_response_bytes, fetch
    )
    event = next(
        (
            value
            for value in event_matches
            if isinstance(value, dict) and value.get("slug") == event_slug
        ),
        None,
    )
    if not isinstance(event, dict):
        raise PolymarketError("Polymarket event series is unavailable")
    series_values = event.get("series")
    if not isinstance(series_values, list):
        raise PolymarketError("Polymarket event series is unavailable")
    series = next(
        (
            value
            for value in series_values
            if isinstance(value, dict)
            and isinstance(value.get("id"), (str, int))
            and not isinstance(value.get("id"), bool)
            and str(value["id"]).isdigit()
            and isinstance(value.get("slug"), str)
        ),
        None,
    )
    if not isinstance(series, dict):
        raise PolymarketError("Polymarket event series is unavailable")
    series_id = str(series["id"])
    series_slug = _text(series["slug"], "series slug")
    query = urlencode(
        {
            "series_id": series_id,
            "closed": "true",
            "limit": limit,
            "order": "endDate",
            "ascending": "false",
        }
    )
    series_url = f"https://{API_HOST}/events?{query}"
    siblings = _fetch_json_list(series_url, float(timeout), max_response_bytes, fetch)
    outcomes: list[SeriesOutcome] = []
    seen: set[str] = set()
    for sibling in siblings:
        if (
            not isinstance(sibling, dict)
            or sibling.get("closed") is not True
            or sibling.get("seriesSlug") != series_slug
        ):
            continue
        try:
            markets = _list_field(sibling.get("markets"), "series markets")
        except PolymarketError:
            continue
        for market in markets:
            if not isinstance(market, dict) or market.get("closed") is not True:
                continue
            try:
                market_id_value = market.get("id")
                if (
                    isinstance(market_id_value, bool)
                    or not isinstance(market_id_value, (str, int))
                    or not str(market_id_value).isdigit()
                ):
                    continue
                market_id = str(market_id_value)
                slug = _text(market.get("slug"), "series market slug")
                question = _text(market.get("question"), "series market question")
                raw_start = sibling.get("eventStartTime") or sibling.get("startTime")
                if isinstance(raw_start, str):
                    start_time = _timestamp(raw_start)
                else:
                    start_epoch = slug.rsplit("-", 1)[-1]
                    if not start_epoch.isdigit():
                        continue
                    start_time = datetime.fromtimestamp(int(start_epoch), timezone.utc)
                end_time = _timestamp(market.get("endDate") or sibling.get("endDate"))
                resolved_at = _timestamp(market.get("closedTime") or market.get("endDate"))
                labels = _list_field(market.get("outcomes"), "series outcomes")
                prices = _list_field(market.get("outcomePrices"), "series outcome prices")
                tokens = _list_field(market.get("clobTokenIds"), "series token IDs")
                if (
                    end_time >= current
                    or resolved_at > current
                    or start_time >= end_time
                    or len(labels) != 2
                    or len(prices) != 2
                    or len(tokens) != 2
                    or labels.count("Up") != 1
                    or labels.count("Down") != 1
                    or not all(isinstance(token, str) and token.isdigit() for token in tokens)
                ):
                    continue
                up_index, down_index = labels.index("Up"), labels.index("Down")
                up_price, down_price = float(prices[up_index]), float(prices[down_index])
                if up_price >= 0.999 and down_price <= 0.001:
                    up_won = True
                elif up_price <= 0.001 and down_price >= 0.999:
                    up_won = False
                else:
                    continue
                resolution_source = _text(
                    market.get("resolutionSource") or sibling.get("resolutionSource"),
                    "resolution source",
                )
            except (PolymarketError, TypeError, ValueError):
                continue
            if market_id in seen:
                continue
            outcomes.append(
                SeriesOutcome(
                    market_id,
                    slug,
                    question,
                    start_time,
                    end_time,
                    resolved_at,
                    up_won,
                    tokens[up_index],
                    tokens[down_index],
                    resolution_source,
                )
            )
            seen.add(market_id)
    outcomes.sort(key=lambda value: value.start_time, reverse=True)
    return PolymarketSeriesHistory(series_id, series_slug, series_url, tuple(outcomes[:limit]))


def load_price_history(
    token_id: str,
    start: datetime,
    end: datetime,
    *,
    fidelity: int = 1,
    timeout: float = DEFAULT_TIMEOUT,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    fetch: Fetch = _fetch,
) -> tuple[HistoricalPrice, ...]:
    """Load sparse CLOB price points in a bounded explicit time range."""
    if not isinstance(token_id, str) or not token_id.isdigit() or len(token_id) > 100:
        raise PolymarketError("Polymarket token ID is invalid")
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or end.tzinfo is None
        or start >= end
        or (end - start).total_seconds() > 15 * 24 * 60 * 60
    ):
        raise PolymarketError("Polymarket price history time range is invalid")
    if isinstance(fidelity, bool) or not isinstance(fidelity, int) or not 1 <= fidelity <= 1_440:
        raise PolymarketError("Polymarket price history fidelity is invalid")
    query = urlencode(
        {
            "market": token_id,
            "startTs": int(start.timestamp()),
            "endTs": int(end.timestamp()),
            "fidelity": fidelity,
        }
    )
    data = _fetch_json(
        f"https://{CLOB_HOST}/prices-history?{query}",
        float(timeout),
        max_response_bytes,
        fetch,
    )
    raw = data.get("history")
    if not isinstance(raw, list) or len(raw) > 20_000:
        raise PolymarketError("Polymarket price history response is invalid")
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    points: list[HistoricalPrice] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PolymarketError("Polymarket price history point is invalid")
        timestamp, price = item.get("t"), item.get("p")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not isfinite(float(timestamp))
            or not isinstance(price, (int, float, str))
            or isinstance(price, bool)
        ):
            raise PolymarketError("Polymarket price history point is invalid")
        try:
            price_value = float(price)
        except ValueError:
            raise PolymarketError("Polymarket price history point is invalid") from None
        if not isfinite(price_value) or not 0 <= price_value <= 1:
            raise PolymarketError("Polymarket price history point is out of range")
        timestamp_value = int(timestamp)
        if start_ts <= timestamp_value <= end_ts:
            points.append(HistoricalPrice(timestamp_value, price_value))
    return tuple(sorted(points, key=lambda point: point.timestamp))
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
    include_no_book: bool = False,
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
    if outcomes not in BINARY_OUTCOMES:
        raise PolymarketError("Polymarket adapter requires YES/NO or Up/Down outcomes in canonical order")
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
    # `current` predates the fetch, so a fresh book can be stamped slightly later.
    if book_age < -MAX_METADATA_FUTURE_SKEW or book_age > MAX_BOOK_AGE:
        raise PolymarketError("Polymarket adapter book is stale")
    asks = tuple(sorted(
        _levels(book.get("asks"), "asks", required=True),
        key=lambda level: level.price,
    )[:MAX_BOOK_LEVELS])
    bids = tuple(
        sorted(
            _levels(book.get("bids", []), "bids", required=False),
            key=lambda level: level.price,
            reverse=True,
        )[:MAX_BOOK_LEVELS]
    )
    if bids and bids[0].price >= asks[0].price:
        raise PolymarketError("Polymarket adapter book is crossed")
    price = asks[0].price
    # The capture is complete only once the book has been received.
    current_utc = max(current_utc, book_time)
    no_fields: dict = {}
    if include_no_book:
        no_token = tokens[1]
        no_book = _fetch_json(
            f"https://{CLOB_HOST}/book?token_id={quote(no_token, safe='')}",
            float(timeout), max_response_bytes, fetch,
        )
        if no_book.get("asset_id") != no_token:
            raise PolymarketError("Polymarket adapter NO token does not match")
        no_time = _book_timestamp(no_book.get("timestamp"))
        if not -MAX_METADATA_FUTURE_SKEW <= current_utc - no_time <= MAX_BOOK_AGE:
            raise PolymarketError("Polymarket adapter NO book is stale")
        current_utc = max(current_utc, no_time)
        no_fields = {
            "no_token_id": no_token,
            "no_asks": tuple(sorted(_levels(no_book.get("asks"), "asks", required=True), key=lambda level: level.price)[:MAX_BOOK_LEVELS]),
            "no_bids": tuple(sorted(_levels(no_book.get("bids", []), "bids", required=False), key=lambda level: level.price, reverse=True)[:MAX_BOOK_LEVELS]),
            "no_book_captured_at": no_time.isoformat(),
        }

    try:
        snapshot = MarketSnapshot(
            snapshot_id or "validation",
            market_id, price, bankroll, market_exposure, total_exposure,
            question, rules, end.isoformat(), current_utc.isoformat(), source_url,
            yes_token, asks, paper_fee_rate, paper_fee_source, book_time.isoformat(),
            bids,
            **no_fields,
        )
        if snapshot_id is None:
            snapshot = replace(snapshot, snapshot_id=market_snapshot_identity(snapshot))
        return snapshot
    except ValueError as exc:
        raise PolymarketError(f"Polymarket adapter cannot create snapshot: {exc}") from exc
