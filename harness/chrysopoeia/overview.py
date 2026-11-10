"""Offline multi-journal overview for the CLI.

Reads local journals only: sessions, turn statuses, forecasts, booked costs,
open positions, and outbox delivery. No network, model, or config calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast

from chrysopoeia.accounting import replay


def _probability(outcome: Mapping[str, object]) -> float | None:
    raw = (outcome.get("proposal") or {}).get("probability")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and 0 <= raw <= 1:
        return float(raw)
    return None


def _reserved_total(outcomes: Sequence[Mapping[str, object]]) -> str | None:
    total = Decimal(0)
    seen = False
    for outcome in outcomes:
        raw = outcome.get("reserved_model_cost_usd")
        if raw is None:
            continue
        value = Decimal(str(raw))
        if value.is_finite() and value >= 0:
            total += value
            seen = True
    return str(total) if seen else None


def summarize_journal(directory: Path, *, now: datetime) -> dict[str, object]:
    """Summarize one journal directory: session, turns, costs, and outbox."""
    book = replay(directory)
    outcomes = list(book.turn_outcomes.values())
    status_counts: dict[str, int] = {}
    for outcome in outcomes:
        status = str(outcome.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

    window_end = book.window_end
    expired = False
    if window_end is not None:
        try:
            expired = datetime.fromisoformat(window_end) < now
        except ValueError:
            expired = False

    forecasts = [
        {
            "turn_id": turn_id,
            "market_id": outcome.get("market_id"),
            "snapshot_id": outcome.get("snapshot_id"),
            "status": outcome.get("status"),
            "probability": _probability(outcome),
            "reason": outcome.get("reason"),
            "research_query_count": (outcome.get("research") or {}).get("query_count"),
            "created_at": outcome.get("created_at"),
            "model_cost_usd": str(outcome.get("model_cost_usd", "0")),
        }
        for turn_id, outcome in sorted(
            book.turn_outcomes.items(),
            key=lambda item: str(item[1].get("created_at", "")),
        )
    ]

    return {
        "schema_version": 1,
        "journal": str(directory),
        "session_status": book.status,
        "window_end": window_end,
        "expired": expired,
        "bankroll": book.bankroll,
        "maximum_loss": book.maximum_loss,
        "target_win_rate": book.target_win_rate,
        "turns": {
            "admitted": len(book.admitted_turns),
            "open": len(book.open_turns),
            "failed": sum(
                1 for outcome in book.finished_turns.values() if outcome == "failed"
            ),
            "outcomes": status_counts,
        },
        "forecasts": forecasts,
        "scored_forecasts": sum(
            1 for outcome in outcomes if _probability(outcome) is not None
        ),
        "cost": {
            "booked_model_cost_usd": str(book.model_cost_usd),
            "reserved_model_cost_usd": _reserved_total(outcomes),
        },
        "positions": {
            "open": len(book.positions),
            "open_exposure": book.open_exposure,
            "settled_trades": book.settled_trades,
            "closed_trades": book.closed_trades,
            "winning_trades": book.winning_trades,
        },
        "pnl": {
            "realized": book.realized_pnl,
            "unrealized": book.unrealized_pnl,
        },
        "outbox": {
            "pending": sum(
                1
                for event in book.outbox.values()
                if (event.get("event_id") or "") not in book.acknowledged_events
            ),
            "acknowledged": len(book.acknowledged_events),
        },
    }


def summarize_journals(
    directories: Sequence[Path], *, now: datetime | None = None
) -> dict[str, object]:
    """Build the aggregated offline overview for one or more journal dirs."""
    current = now or datetime.now(timezone.utc)
    per_journal = [
        summarize_journal(directory, now=current) for directory in directories
    ]
    booked = Decimal(0)
    for entry in per_journal:
        booked += Decimal(str(entry["cost"]["booked_model_cost_usd"]))
    return {
        "schema_version": 1,
        "generated_at": current.isoformat(),
        "journals": per_journal,
        "totals": {
            "journals": len(per_journal),
            "forecast_samples": sum(
                int(entry["scored_forecasts"]) for entry in per_journal
            ),
            "failed_turns": sum(int(entry["turns"]["failed"]) for entry in per_journal),
            "open_turns": sum(int(entry["turns"]["open"]) for entry in per_journal),
            "open_positions": sum(
                int(entry["positions"]["open"]) for entry in per_journal
            ),
            "booked_model_cost_usd": str(booked),
        },
    }


def render_human(report: Mapping[str, object]) -> str:
    """Render the report as compact text for an operator terminal."""
    lines: list[str] = []
    totals = cast(Mapping[str, object], report["totals"])
    journals = cast(Sequence[Mapping[str, object]], report["journals"])
    lines.append(f"chrysopoeia overview · {str(report['generated_at'])[:16]}")
    lines.append(
        f"journals {totals['journals']} · forecast samples {totals['forecast_samples']}"
        f" · failed turns {totals['failed_turns']} · open turns {totals['open_turns']}"
        f" · booked cost ${totals['booked_model_cost_usd']}"
    )
    for entry in journals:
        turns = entry["turns"]
        outcomes = turns["outcomes"]
        cost = entry["cost"]
        positions = entry["positions"]
        outbox = entry["outbox"]
        name = Path(str(entry["journal"])).name
        state = "expired" if entry["expired"] else str(entry["session_status"])
        window = f"{str(entry['window_end'])[:16]}" if entry["window_end"] else "-"
        lines.append("")
        lines.append(
            f"{name} · {state} · window end {window} · bankroll {entry['bankroll']}"
        )
        breakdown = " · ".join(
            f"{status} {count}" for status, count in sorted(outcomes.items())
        )
        lines.append(
            f"  turns admitted {turns['admitted']} · open {turns['open']} · failed {turns['failed']}"
            + (f" · {breakdown}" if breakdown else "")
        )
        lines.append(
            f"  forecasts scored {entry['scored_forecasts']} · booked cost ${cost['booked_model_cost_usd']}"
            f" · reserved ${cost['reserved_model_cost_usd'] or '0'}"
        )
        lines.append(
            f"  positions open {positions['open']} (exposure ${positions['open_exposure']})"
            f" · wins {positions['winning_trades']}/{positions['settled_trades']} settled"
            f" · pnl {entry['pnl']['realized']} realized / {entry['pnl']['unrealized']} unrealized"
        )
        lines.append(
            f"  outbox pending {outbox['pending']} · acknowledged {outbox['acknowledged']}"
        )
        for forecast in cast(Sequence[Mapping[str, object]], entry["forecasts"]):
            probability = forecast["probability"]
            probability_text = (
                f"p={probability:.2f}" if probability is not None else "p=-"
            )
            lines.append(
                f"    - {str(forecast['created_at'])[:16]} · market {forecast['market_id']}"
                f" · {forecast['status']} · {probability_text} · {forecast['reason']}"
                f" · ${forecast['model_cost_usd']}"
            )
    return "\n".join(lines)
