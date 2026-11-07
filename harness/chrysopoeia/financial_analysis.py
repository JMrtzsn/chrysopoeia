from __future__ import annotations

import json
import math
import re
import statistics
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import pairwise
from typing import Protocol

MAX_CANDLES = 200
MAX_RESPONSE_BYTES = 1_000_000
HTTP_TIMEOUT_SECONDS = 10.0
CCXT_TIMEOUT_SECONDS = 20.0
USER_AGENT = "Chrysopoeia/0.1 read-only market analysis"
CRYPTO_TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3_600,
    "4h": 14_400,
    "6h": 21_600,
    "1d": 86_400,
    "1w": 604_800,
}


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class Fetch(Protocol):
    def __call__(self, url: str, timeout: float, max_bytes: int) -> bytes: ...


class CryptoExchange(Protocol):
    has: Mapping[str, object]
    timeframes: Mapping[str, object]
    urls: Mapping[str, object]

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int, limit: int
    ) -> object: ...

    def close(self) -> object: ...


ExchangeFactory = Callable[[str, dict[str, object]], CryptoExchange]


def _http_get(url: str, timeout: float, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("market history response is too large")
    return body


def _valid_limit(limit: int) -> int:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 14 <= limit <= MAX_CANDLES
    ):
        raise ValueError(f"limit must be between 14 and {MAX_CANDLES}")
    return limit


def _candle(
    timestamp: object,
    open_: object,
    high: object,
    low: object,
    close: object,
    volume: object,
) -> Candle:
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError("invalid candle timestamp")
    if not math.isfinite(float(timestamp)) or not 0 < timestamp < 4_102_444_800:
        raise ValueError("invalid candle timestamp")
    values = (open_, high, low, close, volume)
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        raise ValueError("invalid candle values")
    converted = tuple(float(value) for value in values)
    if any(not math.isfinite(value) for value in converted):
        raise ValueError("non-finite candle value")
    open_value, high_value, low_value, close_value, volume_value = converted
    if (
        min(open_value, high_value, low_value, close_value) <= 0
        or volume_value < 0
        or high_value < max(open_value, close_value, low_value)
        or low_value > min(open_value, close_value)
    ):
        raise ValueError("inconsistent candle values")
    return Candle(
        int(timestamp), open_value, high_value, low_value, close_value, volume_value
    )


def stock_history(
    symbol: str, *, limit: int = 100, fetch: Fetch = _http_get
) -> dict[str, object]:
    """Fetch daily US-equity candles from Yahoo Finance's public chart endpoint."""
    limit = _valid_limit(limit)
    if (
        not isinstance(symbol, str)
        or re.fullmatch(r"[A-Za-z0-9^=._-]{1,20}", symbol) is None
    ):
        raise ValueError("invalid stock symbol")
    encoded = urllib.parse.quote(symbol.upper(), safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1y&interval=1d"
    try:
        response = json.loads(fetch(url, HTTP_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("stock history response is invalid") from None
    try:
        result = response["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        opens, highs, lows, closes = (
            quote[key] for key in ("open", "high", "low", "close")
        )
        volumes = quote.get("volume") or [0] * len(timestamps)
    except (KeyError, IndexError, TypeError):
        raise ValueError("stock history is unavailable") from None
    if not all(
        isinstance(values, list)
        for values in (timestamps, opens, highs, lows, closes, volumes)
    ):
        raise ValueError("stock history response is invalid")
    if (
        len(
            {
                len(values)
                for values in (timestamps, opens, highs, lows, closes, volumes)
            }
        )
        != 1
    ):
        raise ValueError("stock history response is inconsistent")
    candles: list[Candle] = []
    for values in zip(timestamps, opens, highs, lows, closes, volumes, strict=True):
        if any(value is None for value in values):
            continue
        candles.append(_candle(*values))
    candles.sort(key=lambda candle: candle.timestamp)
    candles = candles[-limit:]
    if len(candles) < 14:
        raise ValueError("stock history has fewer than 14 usable daily candles")
    return {
        "symbol": result.get("meta", {}).get("symbol", symbol.upper()),
        "currency": result.get("meta", {}).get("currency"),
        "interval": "1d",
        "source": "Yahoo Finance public chart endpoint",
        "source_url": url,
        "price_adjustment": "raw OHLCV; corporate actions not adjusted",
        "candles": candles,
    }


def crypto_history(
    exchange_id: str,
    symbol: str,
    *,
    interval: str = "1d",
    limit: int = 100,
    exchange_factory: ExchangeFactory | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Fetch bounded public OHLCV candles through CCXT, without credentials."""
    limit = _valid_limit(limit)
    if isinstance(exchange_id, str):
        exchange_id = exchange_id.strip().lower()
    if isinstance(symbol, str):
        symbol = symbol.strip().upper().replace("-", "/")
    if (
        not isinstance(exchange_id, str)
        or re.fullmatch(r"[a-z0-9]{2,24}", exchange_id) is None
    ):
        raise ValueError("invalid CCXT exchange id")
    match = (
        re.fullmatch(r"([A-Z0-9]{2,12})/([A-Z0-9]{2,12})", symbol)
        if isinstance(symbol, str)
        else None
    )
    if match is None:
        raise ValueError("symbol must look like BTC/USD")
    if not isinstance(interval, str) or interval not in CRYPTO_TIMEFRAMES:
        raise ValueError("unsupported crypto timeframe")
    if exchange_factory is None:
        import ccxt

        if exchange_id not in ccxt.exchanges:
            raise ValueError("unsupported CCXT exchange")
        exchange_class = getattr(ccxt, exchange_id, None)
        if not callable(exchange_class):
            raise ValueError("unsupported CCXT exchange")
        exchange = exchange_class(
            {"enableRateLimit": True, "timeout": int(CCXT_TIMEOUT_SECONDS * 1000)}
        )
    else:
        exchange = exchange_factory(
            exchange_id,
            {"enableRateLimit": True, "timeout": int(CCXT_TIMEOUT_SECONDS * 1000)},
        )
    try:
        if not exchange.has.get("fetchOHLCV") or interval not in exchange.timeframes:
            raise ValueError("exchange does not support this OHLCV timeframe")
        end = now or datetime.now(timezone.utc)
        if end.tzinfo is None:
            raise ValueError("now must include a UTC offset")
        since = int(end.timestamp() * 1000) - CRYPTO_TIMEFRAMES[interval] * limit * 1000
        rows = exchange.fetch_ohlcv(symbol, interval, since, limit)
        if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != 6 for row in rows
        ):
            raise ValueError("crypto history response is invalid")
        candles = [_candle(float(row[0]) / 1000, *row[1:]) for row in rows]
        urls = exchange.urls
        source_root = urls.get("www") if isinstance(urls, Mapping) else None
        if isinstance(source_root, list):
            source_root = next(
                (value for value in source_root if isinstance(value, str)), None
            )
        if not isinstance(source_root, str) or not source_root.startswith("https://"):
            raise ValueError("exchange source URL is unavailable")
        source_url = f"{source_root.rstrip('/')}/?{urllib.parse.urlencode({'market': symbol, 'timeframe': interval, 'since': since, 'limit': limit})}"
    finally:
        exchange.close()
    candles.sort(key=lambda candle: candle.timestamp)
    candles = candles[-limit:]
    if len(candles) < 14:
        raise ValueError("crypto history has fewer than 14 usable candles")
    return {
        "symbol": symbol,
        "currency": match.group(2),
        "interval": interval,
        "exchange": exchange_id,
        "source": f"{exchange_id} via CCXT public OHLCV",
        "source_url": source_url,
        "price_adjustment": "exchange-reported OHLCV",
        "candles": candles,
    }


def analyze_history(history: dict[str, object]) -> dict[str, object]:
    candles = history.get("candles")
    if (
        not isinstance(candles, list)
        or len(candles) < 2
        or any(not isinstance(c, Candle) for c in candles)
    ):
        raise ValueError("invalid candle series")
    closes = [c.close for c in candles]
    returns = [(right / left - 1.0) * 100.0 for left, right in pairwise(closes)]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    def sma(period: int) -> float | None:
        return statistics.fmean(closes[-period:]) if len(closes) >= period else None

    ema20 = closes[0]
    alpha = 2.0 / 21.0
    for close in closes[1:]:
        ema20 = alpha * close + (1.0 - alpha) * ema20

    changes = [right - left for left, right in pairwise(closes)]
    last_changes = changes[-14:]
    gains = [max(change, 0.0) for change in last_changes]
    losses = [max(-change, 0.0) for change in last_changes]
    average_gain = statistics.fmean(gains) if len(last_changes) == 14 else None
    average_loss = statistics.fmean(losses) if len(last_changes) == 14 else None
    if average_gain is None or average_loss is None:
        rsi = None
    elif average_loss == 0:
        rsi = 100.0 if average_gain > 0 else 50.0
    else:
        rsi = 100.0 - 100.0 / (1.0 + average_gain / average_loss)

    stochastic: list[float] = []
    for index in range(13, len(candles)):
        highest = max(highs[index - 13 : index + 1])
        lowest = min(lows[index - 13 : index + 1])
        stochastic.append(
            100.0 * (closes[index] - lowest) / (highest - lowest)
            if highest > lowest
            else 50.0
        )
    stochastic_k = stochastic[-1] if stochastic else None
    stochastic_d = statistics.fmean(stochastic[-3:]) if len(stochastic) >= 3 else None

    true_ranges = []
    for index, candle in enumerate(candles):
        previous = closes[index - 1] if index else candle.close
        true_ranges.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous),
                abs(candle.low - previous),
            )
        )
    atr14 = statistics.fmean(true_ranges[-14:]) if len(true_ranges) >= 14 else None

    def rounded(value: float | None) -> float | None:
        return round(value, 6) if value is not None and math.isfinite(value) else None

    return {
        "symbol": history["symbol"],
        "currency": history.get("currency"),
        "source": history["source"],
        "source_url": history["source_url"],
        "price_adjustment": history.get("price_adjustment", "unspecified"),
        "interval": history["interval"],
        "bar_count": len(candles),
        "first_bar": datetime.fromtimestamp(
            candles[0].timestamp, timezone.utc
        ).isoformat(),
        "last_bar": datetime.fromtimestamp(
            candles[-1].timestamp, timezone.utc
        ).isoformat(),
        "close": rounded(closes[-1]),
        "mean_close": rounded(statistics.fmean(closes)),
        "close_stddev": rounded(statistics.pstdev(closes)),
        "period_return_pct": rounded((closes[-1] / closes[0] - 1.0) * 100.0),
        "mean_return_pct": rounded(statistics.fmean(returns)) if returns else None,
        "return_stddev_pct": rounded(statistics.pstdev(returns)) if returns else None,
        "sma_10": rounded(sma(10)),
        "sma_20": rounded(sma(20)),
        "sma_50": rounded(sma(50)),
        "ema_20": rounded(ema20),
        "rsi_14_simple": rounded(rsi),
        "stochastic_14_k": rounded(stochastic_k),
        "stochastic_3_d": rounded(stochastic_d),
        "atr_14": rounded(atr14),
        "mean_volume": rounded(statistics.fmean(c.volume for c in candles)),
        "recent_candles": [
            {
                "time": datetime.fromtimestamp(c.timestamp, timezone.utc).isoformat(),
                "open": rounded(c.open),
                "high": rounded(c.high),
                "low": rounded(c.low),
                "close": rounded(c.close),
                "volume": rounded(c.volume),
            }
            for c in candles[-5:]
        ],
        "interpretation": "Descriptive historical measurements only; not a forecast or trade recommendation.",
    }
