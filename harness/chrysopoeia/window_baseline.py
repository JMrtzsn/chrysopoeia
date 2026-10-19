"""Deterministic baseline for short BTC Up/Down windows.

This is a measurement, not a trade instruction: it gives the trader the window's
opening price, the current price, remaining time, recent minute volatility, and a
normal-approximation P(Up). The harness still owns all policy and execution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from itertools import pairwise
from math import erf, log, sqrt

from chrysopoeia.financial_analysis import crypto_history
from chrysopoeia.paper_cycle import EvidenceRecord, external_evidence
from chrysopoeia.trading import MarketSnapshot

WINDOW_SECONDS = 300
MINUTE_SECONDS = 60
MAX_RETURNS = 15
MIN_CANDLES = 14
MIN_PROBABILITY = 0.01
MAX_PROBABILITY = 0.99
VOL_FLOOR = 1e-6

History = Callable[..., dict[str, object]]
Ticker = Callable[..., float]


def _clamp(value: float) -> float:
    return min(max(value, MIN_PROBABILITY), MAX_PROBABILITY)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def estimate_up_probability(
    open_price: float, last_price: float, seconds_remaining: float, minute_vol: float
) -> float:
    """Normal-approximation P(price ends above the window open)."""
    for value in (open_price, last_price, minute_vol):
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("baseline inputs must be positive")
    if open_price == last_price:
        return 0.5
    horizon = max(float(seconds_remaining), 0.0) / MINUTE_SECONDS
    sigma = max(float(minute_vol), VOL_FLOOR) * sqrt(horizon if horizon > 0 else 1e-9)
    return _clamp(_normal_cdf(log(last_price / open_price) / sigma))


def last_price(exchange_id: str = "bitstamp", symbol: str = "BTC/USD") -> float:
    """Read one public last price; read-only, with no order methods."""
    import ccxt

    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": 10_000})
    try:
        price = exchange.fetch_ticker(symbol).get("last")
    finally:
        exchange.close()
    if not isinstance(price, (int, float)) or price <= 0:
        raise ValueError("last price is unavailable")
    return float(price)


def window_metrics(
    candles: Sequence[object],
    window_start: datetime,
    captured_at: datetime,
    window_end: datetime,
    *,
    latest: float | None = None,
) -> dict[str, object]:
    """Measure the open, latest price, remaining time, and recent minute volatility."""
    start = window_start.timestamp()
    captured = captured_at.timestamp()
    usable = [
        candle
        for candle in candles
        if getattr(candle, "timestamp", 0) <= captured
        and getattr(candle, "close", None) is not None
    ]
    if len(usable) < MIN_CANDLES:
        raise ValueError("baseline history is insufficient")
    at_open = [candle for candle in usable if candle.timestamp <= start]
    opening = (
        at_open[-1].open
        if at_open and getattr(at_open[-1], "open", None) is not None
        else (at_open[-1] if at_open else usable[0]).close
    )
    last = usable[-1].close if latest is None else latest
    returns = [
        log(right.close / left.close)
        for left, right in pairwise(usable)
        if left.close > 0 and right.close > 0
    ][-MAX_RETURNS:]
    if len(returns) < 2:
        raise ValueError("baseline history is insufficient")
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    minute_vol = sqrt(variance)
    remaining = window_end.timestamp() - captured_at.timestamp()
    return {
        "window_start": window_start.astimezone(timezone.utc).isoformat(),
        "window_end": window_end.astimezone(timezone.utc).isoformat(),
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "open": float(opening),
        "last": float(last),
        "delta_bps": (float(last) / float(opening) - 1.0) * 10_000,
        "seconds_remaining": max(remaining, 0.0),
        "minute_vol": float(minute_vol),
        "model_p_up": estimate_up_probability(
            float(opening), float(last), remaining, float(minute_vol)
        ),
    }


def baseline_evidence(
    snapshot: MarketSnapshot,
    *,
    now: datetime,
    history: History = crypto_history,
    ticker: Ticker = last_price,
) -> EvidenceRecord | None:
    """Build one citable baseline record for a BTC 5m snapshot, or None."""
    try:
        captured_at = datetime.fromisoformat(snapshot.captured_at.replace("Z", "+00:00"))
        window_end = datetime.fromisoformat(snapshot.end_time.replace("Z", "+00:00"))
        if captured_at.tzinfo is None or window_end.tzinfo is None:
            return None
        window_start = window_end.replace(
            second=0, microsecond=0
        ).timestamp() - WINDOW_SECONDS
        fetched = history("bitstamp", "BTC/USD", interval="1m", limit=30, now=now)
        candles = fetched.get("candles")
        source_url = fetched.get("source_url")
        if not isinstance(candles, list) or not isinstance(source_url, str):
            return None
        metrics = window_metrics(
            candles,
            datetime.fromtimestamp(window_start, timezone.utc),
            captured_at,
            window_end,
            latest=ticker(),
        )
    except (ValueError, TypeError, KeyError, OSError):
        return None
    excerpt = (
        f"window_open={metrics['open']:.2f} last={metrics['last']:.2f} "
        f"delta_bps={metrics['delta_bps']:+.1f} "
        f"seconds_remaining={metrics['seconds_remaining']:.0f} "
        f"minute_vol={metrics['minute_vol']:.6f} "
        f"baseline_p_up={metrics['model_p_up']:.3f}"
    )
    try:
        return external_evidence(
            snapshot,
            source_url,
            "BTC 5m deterministic window baseline",
            snapshot.captured_at,
            excerpt=excerpt,
        )
    except (ValueError, TypeError):
        return None
