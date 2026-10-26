import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from paper_consumer.core import InvalidEvent, Quote

MAX_BYTES = 256 * 1024
TIMEOUT = 5.0
MAX_LEVELS = 50


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError


def _json(value: bytes | str) -> object:
    return json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)


def _get(url: str) -> dict[str, object]:
    try:
        with urlopen(
            Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "chrysopoeia-consumer/0.1"},
            ),
            timeout=TIMEOUT,
        ) as response:
            body = response.read(MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("public market request failed") from exc
    if len(body) > MAX_BYTES:
        raise RuntimeError("public market response is too large")
    try:
        value = _json(body)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise InvalidEvent("public market response is malformed") from exc
    if not isinstance(value, dict):
        raise InvalidEvent("public market response is malformed")
    return value


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise InvalidEvent("public market timestamp is malformed")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidEvent("public market timestamp is malformed") from None
    if result.tzinfo is None:
        raise InvalidEvent("public market timestamp is malformed")
    return result.astimezone(timezone.utc)


def _list(value: object) -> list[object]:
    if isinstance(value, str):
        try:
            value = _json(value)
        except (json.JSONDecodeError, ValueError, RecursionError):
            raise InvalidEvent("public market metadata is malformed") from None
    if not isinstance(value, list):
        raise InvalidEvent("public market metadata is malformed")
    return value


def _levels(value: object, *, reverse: bool) -> tuple[tuple[float, float], ...]:
    # Live books exceed 50 levels; the response is byte-bounded, so keep the best 50 like Harness.
    if not isinstance(value, list):
        raise InvalidEvent("public market book is malformed")
    result = []
    try:
        for level in value:
            if not isinstance(level, dict) or set(level) != {"price", "size"}:
                raise ValueError
            result.append((float(level["price"]), float(level["size"])))
    except (TypeError, ValueError):
        raise InvalidEvent("public market book is malformed") from None
    return tuple(sorted(result, key=lambda level: level[0], reverse=reverse)[:MAX_LEVELS])


class Polymarket:
    """Bounded, public, read-only market data. It has no signing or order code."""

    def load(self, market_id: str, token_id: str, now: datetime) -> Quote:
        metadata = _get(f"https://gamma-api.polymarket.com/markets/{quote(market_id, safe='')}")
        if str(metadata.get("id")) != market_id:
            raise InvalidEvent("public market ID does not match")
        tokens = _list(metadata.get("clobTokenIds"))
        outcomes = _list(metadata.get("outcomes"))
        if (
            len(outcomes) != 2
            or outcomes[0] == outcomes[1]
            or any(
                not isinstance(outcome, str)
                or not outcome
                or outcome != outcome.strip()
                or len(outcome) > 120
                for outcome in outcomes
            )
            or len(tokens) != 2
            or not all(isinstance(token, str) and token for token in tokens)
            or tokens[0] == tokens[1]
            or token_id not in tokens
        ):
            raise InvalidEvent("public market outcome token does not match")
        token_index = tokens.index(token_id)
        selected_outcome = "YES" if token_index == 0 else "NO"
        end = _time(metadata.get("endDate", metadata.get("endDateIso")))
        updated = _time(metadata.get("updatedAt"))
        if updated - now.astimezone(timezone.utc) > timedelta(seconds=5):
            raise InvalidEvent("public market metadata is future-dated")
        if metadata.get("closed") is True:
            prices = _list(metadata.get("outcomePrices"))
            if not all(
                isinstance(value, (str, int, float)) and not isinstance(value, bool)
                for value in prices
            ):
                raise InvalidEvent("public resolution is ambiguous")
            try:
                fractions = [float(value) for value in cast(list[str | int | float], prices)]
            except (TypeError, ValueError):
                raise InvalidEvent("public resolution is ambiguous") from None
            if len(fractions) != 2 or any(not 0 <= value <= 1 for value in fractions) or sum(value >= 0.999 for value in fractions) != 1:
                raise InvalidEvent("public resolution is ambiguous")
            resolution = "YES" if fractions[token_index] >= 0.999 else "NO"
            return Quote(
                "resolution-"
                + sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()[:24],
                market_id,
                token_id,
                end.isoformat(),
                now.isoformat(),
                (),
                (),
                resolution,
                selected_outcome,
            )
        if metadata.get("active") is not True or metadata.get("acceptingOrders") is not True:
            raise InvalidEvent("public market is not tradeable")
        book = _get(f"https://clob.polymarket.com/book?token_id={quote(token_id, safe='')}")
        if book.get("asset_id") != token_id:
            raise InvalidEvent("public book token does not match")
        timestamp = book.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.isdigit():
            raise InvalidEvent("public book timestamp is malformed")
        captured = datetime.fromtimestamp(int(timestamp) / 1_000, timezone.utc)
        book_age = now.astimezone(timezone.utc) - captured
        if book_age > timedelta(minutes=5) or book_age < -timedelta(seconds=5):
            raise InvalidEvent("public market book is stale or future-dated")
        asks = _levels(book.get("asks"), reverse=False)
        bids = _levels(book.get("bids", []), reverse=True)
        if not asks:
            raise InvalidEvent("public book has no asks")
        identity = sha256(json.dumps(book, sort_keys=True).encode()).hexdigest()[:24]
        return Quote(
            "polymarket-" + identity,
            market_id,
            token_id,
            end.isoformat(),
            captured.isoformat(),
            asks,
            bids,
            outcome=selected_outcome,
        )
