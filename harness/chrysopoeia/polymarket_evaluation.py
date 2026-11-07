from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from chrysopoeia import accounting
from chrysopoeia.polymarket import (
    HistoricalPrice,
    PolymarketError,
    ResolvedMarket,
    load_price_history,
    load_resolved_market,
)

MAX_MARKETS = 200
BASELINE_LOOKBACK_SECONDS = 300
BASELINE_LOOKBACK_SECONDS = 300


def brier_score(probabilities: list[float], outcomes: list[bool]) -> float | None:
    if len(probabilities) != len(outcomes):
        raise ValueError("probability and outcome counts differ")
    if not probabilities:
        return None
    if any(
        isinstance(probability, bool)
        or not isinstance(probability, (int, float))
        or not 0 <= probability <= 1
        for probability in probabilities
    ):
        raise ValueError("probability is outside [0, 1]")
    return sum(
        (probability - (1.0 if outcome else 0.0)) ** 2
        for probability, outcome in zip(probabilities, outcomes, strict=True)
    ) / len(probabilities)


def _slug(evidence: object) -> str:
    if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping):
        url = evidence[0].get("url")
        if isinstance(url, str):
            return urlsplit(url).path.rsplit("/", 1)[-1]
    return ""


def evaluate_journal(
    journal: Path,
    *,
    series_url: str | None = None,
    load_market: Callable[..., ResolvedMarket] | None = None,
    load_prices: Callable[..., tuple[HistoricalPrice, ...]] | None = None,
) -> dict[str, object]:
    """Score each market's first pre-close P(YES side) against its resolution.

    Works for any binary Yes/No or Up/Down Polymarket market. Abstentions are
    scored too; trade coverage is reported separately. `series_url` optionally
    restricts scoring to one recurring series (e.g. a BTC 5m window URL).
    """
    prefix = None
    if series_url is not None:
        anchor = urlsplit(series_url).path.rsplit("/", 1)[-1]
        prefix = f"{anchor.rsplit('-', 1)[0]}-"
    first: dict[str, tuple[datetime, float, str]] = {}
    repeated = missing = 0
    outcomes = [
        value
        for value in accounting.replay(journal).turn_outcomes.values()
        if isinstance(value, Mapping) and isinstance(value.get("proposal"), Mapping)
    ]
    outcomes.sort(key=lambda value: str(value.get("created_at", "")))
    for outcome in outcomes:
        market_id, proposal = outcome.get("market_id"), outcome["proposal"]
        if not isinstance(market_id, str):
            continue
        if prefix is not None and not _slug(outcome.get("evidence")).startswith(prefix):
            continue
        raw = proposal.get("probability")
        try:
            created_at = _parse_time(outcome.get("created_at"))
            if (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not 0 <= raw <= 1
            ):
                continue
        except ValueError:
            continue
        action = str(proposal.get("action"))
        if action != "trade" and raw in (0, 1):
            # Abstentions at exactly 0/1 are placeholders, not genuine estimates.
            missing += 1
            continue
        if market_id in first:
            repeated += 1
            continue
        first[market_id] = (created_at, float(raw), action)
    if len(first) > MAX_MARKETS:
        raise ValueError(f"more than {MAX_MARKETS} markets to evaluate")

    windows: list[dict[str, object]] = []
    agent_p: list[float] = []
    agent_y: list[bool] = []
    pair_agent: list[float] = []
    pair_market: list[float] = []
    pair_y: list[bool] = []
    pending = late = unavailable = trades = 0
    for market_id, (forecast_time, probability, action) in first.items():
        try:
            market = (load_market or load_resolved_market)(market_id)
        except PolymarketError:
            unavailable += 1
            continue
        if market.yes_won is None:
            pending += 1
            continue
        if forecast_time >= market.end_time:
            late += 1
            continue
        try:
            baseline = _latest_price(
                (load_prices or load_price_history)(
                    market.yes_token_id,
                    forecast_time - timedelta(seconds=BASELINE_LOOKBACK_SECONDS),
                    forecast_time,
                ),
                forecast_time,
            )
        except PolymarketError:
            baseline = None
        agent_p.append(probability)
        agent_y.append(market.yes_won)
        trades += action == "trade"
        if baseline is not None:
            pair_agent.append(probability)
            pair_market.append(baseline)
            pair_y.append(market.yes_won)
        windows.append(
            {
                "market_id": market_id,
                "slug": market.slug,
                "forecast_time": forecast_time.isoformat(),
                "agent_action": action,
                "agent_probability_yes": probability,
                "market_probability_yes": baseline,
                "resolved_yes": market.yes_won,
            }
        )

    agent_on_pairs = brier_score(pair_agent, pair_y)
    market_on_pairs = brier_score(pair_market, pair_y)
    return {
        "schema_version": 2,
        "record_type": "polymarket_forecast_evaluation",
        "metric": "brier_score",
        "lower_is_better": True,
        "series_filter": prefix,
        "scored_markets": len(agent_p),
        "pending_markets": pending,
        "late_forecasts_skipped": late,
        "unavailable_markets": unavailable,
        "repeated_forecasts_ignored": repeated,
        "abstentions_without_estimate": missing,
        "agent": {
            "brier_score": brier_score(agent_p, agent_y),
            "trades": trades,
            "trade_coverage": trades / len(agent_p) if agent_p else None,
        },
        "market_baseline": {
            "paired_samples": len(pair_market),
            "market_brier": market_on_pairs,
            "agent_brier": agent_on_pairs,
            "agent_improvement": (
                market_on_pairs - agent_on_pairs
                if market_on_pairs is not None and agent_on_pairs is not None
                else None
            ),
        },
        "markets": windows,
    }


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("forecast timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("forecast timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("forecast timestamp must have a UTC offset")
    return parsed.astimezone(timezone.utc)


def _latest_price(
    points: tuple[HistoricalPrice, ...], forecast_time: datetime
) -> float | None:
    cutoff = int(forecast_time.timestamp())
    prior = [point for point in points if point.timestamp <= cutoff]
    if not prior:
        return None
    latest = max(prior, key=lambda point: point.timestamp)
    if cutoff - latest.timestamp > BASELINE_LOOKBACK_SECONDS:
        return None
    return latest.price
