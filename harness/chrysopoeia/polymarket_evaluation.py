from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from chrysopoeia import accounting
from chrysopoeia.polymarket import (
    HistoricalPrice,
    PolymarketError,
    PolymarketSeriesHistory,
    load_price_history,
    load_series_history,
)

MAX_WINDOWS = 20
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


def evaluate_journal(
    journal: Path,
    event_url: str,
    *,
    limit: int = 10,
    load_series: Callable[..., PolymarketSeriesHistory] | None = None,
    load_prices: Callable[..., tuple[HistoricalPrice, ...]] | None = None,
) -> dict[str, object]:
    """Score local trade forecasts against resolved Polymarket series outcomes."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_WINDOWS:
        raise ValueError(f"limit must be between 1 and {MAX_WINDOWS}")
    book = accounting.replay(journal)
    history = (load_series or load_series_history)(event_url, limit=limit)
    outcomes = {item.market_id: item for item in history.outcomes}
    anchor_slug = urlsplit(event_url).path.rsplit("/", 1)[-1]
    series_prefix = anchor_slug.rsplit("-", 1)[0]
    decisions = [
        value
        for value in book.turn_outcomes.values()
        if isinstance(value, Mapping)
        and isinstance(value.get("proposal"), Mapping)
    ]
    decisions.sort(key=lambda value: str(value.get("created_at", "")))

    predictions: dict[str, tuple[datetime, float, str]] = {}
    abstentions = outside_window = unmatched = duplicate_forecasts = 0
    for outcome in decisions:
        market_id = outcome.get("market_id")
        proposal = outcome.get("proposal")
        evidence = outcome.get("evidence")
        source_url = (
            evidence[0].get("url")
            if isinstance(evidence, list) and evidence and isinstance(evidence[0], Mapping)
            else None
        )
        source_slug = (
            urlsplit(source_url).path.rsplit("/", 1)[-1]
            if isinstance(source_url, str)
            else ""
        )
        if (
            not isinstance(market_id, str)
            or not isinstance(proposal, Mapping)
            or not source_slug.startswith(f"{series_prefix}-")
        ):
            continue
        market = outcomes.get(market_id)
        if market is None:
            unmatched += 1
            continue
        try:
            created_at = _parse_time(outcome.get("created_at"))
            raw_probability = proposal.get("probability")
            if isinstance(raw_probability, bool):
                continue
            probability = float(raw_probability)
        except (TypeError, ValueError):
            continue
        if not 0 <= probability <= 1:
            continue
        if not market.start_time <= created_at < market.end_time:
            outside_window += 1
            continue
        if market_id in predictions:
            duplicate_forecasts += 1
            continue
        # The first in-window estimate counts, whether the agent traded or abstained.
        action = str(proposal.get("action"))
        if action != "trade":
            abstentions += 1
        predictions[market_id] = (created_at, probability, action)

    scored: list[dict[str, object]] = []
    agent_probabilities: list[float] = []
    labels: list[bool] = []
    market_probabilities: list[float] = []
    market_labels: list[bool] = []
    matched_agent_probabilities: list[float] = []
    matched_market_probabilities: list[float] = []
    matched_labels: list[bool] = []
    for market in history.outcomes:
        prediction = predictions.get(market.market_id)
        forecast_time = prediction[0] if prediction else market.start_time
        p_agent = prediction[1] if prediction else None
        age = forecast_time - timedelta(seconds=BASELINE_LOOKBACK_SECONDS)
        try:
            baseline = _latest_price(
                (load_prices or load_price_history)(
                    market.up_token_id, age, forecast_time
                ),
                forecast_time,
            )
        except PolymarketError:
            baseline = None
        record: dict[str, object] = {
            "market_id": market.market_id,
            "slug": market.slug,
            "start_time": market.start_time.isoformat(),
            "resolved_up": market.up_won,
            "forecast_time": forecast_time.isoformat(),
            "agent_probability_up": p_agent,
            "agent_action": prediction[2] if prediction else None,
            "market_probability_up": baseline,
            "resolution_source": market.resolution_source,
        }
        if p_agent is not None:
            agent_probabilities.append(p_agent)
            labels.append(market.up_won)
            if baseline is not None:
                matched_agent_probabilities.append(p_agent)
                matched_market_probabilities.append(baseline)
                matched_labels.append(market.up_won)
        if baseline is not None:
            market_probabilities.append(baseline)
            market_labels.append(market.up_won)
        scored.append(record)

    agent_score = brier_score(agent_probabilities, labels)
    matched_agent_score = brier_score(matched_agent_probabilities, matched_labels)
    matched_market_score = brier_score(matched_market_probabilities, matched_labels)
    market_score = brier_score(market_probabilities, market_labels)
    market_up_rate = (
        sum(market.up_won for market in history.outcomes) / len(history.outcomes)
        if history.outcomes
        else None
    )
    same_sample_improvement = (
        matched_market_score - matched_agent_score
        if matched_market_score is not None and matched_agent_score is not None
        else None
    )
    return {
        "schema_version": 1,
        "record_type": "polymarket_forecast_evaluation",
        "series_id": history.series_id,
        "series_slug": history.series_slug,
        "metric": "brier_score",
        "lower_is_better": True,
        "windows_loaded": len(history.outcomes),
        "resolved_up_rate": market_up_rate,
        "agent": {
            "samples": len(agent_probabilities),
            "trades": len(agent_probabilities) - abstentions,
            "trade_coverage": (
                (len(agent_probabilities) - abstentions) / len(agent_probabilities)
                if agent_probabilities
                else None
            ),
            "abstentions_in_loaded_windows": abstentions,
            "out_of_window_forecasts": outside_window,
            "unmatched_forecasts": unmatched,
            "duplicate_forecasts_skipped": duplicate_forecasts,
            "brier_score": agent_score,
        },
        "market_baseline": {
            "samples": len(market_probabilities),
            "brier_score": market_score,
            "samples_matching_agent": len(matched_market_probabilities),
            "brier_on_agent_sample": matched_market_score,
            "agent_brier_on_same_sample": matched_agent_score,
            "agent_improvement": same_sample_improvement,
        },
        "windows": scored,
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
