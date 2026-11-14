import math
import os
from collections.abc import Iterable
from datetime import datetime, time, timedelta, timezone

from google.cloud import bigquery

from observer.insights import (
    _TABLE_ID,
    LOOKBACK_DAYS,
    MAXIMUM_BYTES_BILLED,
    QUERY_TIMEOUT_SECONDS,
    BigQueryClient,
    _amount,
    _count,
    _default_client,
    _row_value,
    _table_reference,
)

# Scheduled executions run at minute 40 of hours 13-22 UTC; outcomes follow
# each execution within minutes. Silence before 13:40 and after 23:00 is by
# design, so the last-outcome age check applies only inside that window.
WINDOW_START = time(13, 40)
WINDOW_END = time(23, 0)
# Hourly executions: four hours without a decision means about three
# consecutive executions produced no outcome.
STALE_OUTCOME_AGE = timedelta(hours=4)
# A filled position may legally wait through a venue reschedule before its
# settlement sweep closes it; a day without any terminal outcome is not.
SETTLEMENT_GRACE_HOURS = 24
POSITIONS_TABLE = "open_positions"

# Lifecycle state comes from the platform-maintained open-positions projection
# (a derived, rebuildable read model over the archive) instead of a 90-day scan.
_POSITIONS_QUERY = """
SELECT
  COUNTIF(status = 'open' AND market_end < TIMESTAMP_SUB(@as_of, INTERVAL @grace_hours HOUR)) AS stuck_settlements,
  MAX(IF(settled_at IS NOT NULL, TIMESTAMP_DIFF(settled_at, market_end, SECOND), NULL)) AS settlement_lag_seconds,
  MAX(settled_at) AS last_completed_at
FROM {table}
"""

# 24-hour metrics anchor on the turn decision time. The scan starts no earlier
# than the last completed trade so context revisions since that outcome are
# fully covered; with no completed trade the revisions count stays zero.
_SCAN_QUERY = """
WITH parsed AS (
  SELECT SAFE.PARSE_JSON(data) AS payload, publish_time
  FROM {table}
  WHERE publish_time >= TIMESTAMP_SUB(@as_of, INTERVAL @lookback_days DAY)
    AND publish_time < @as_of
    AND data IS NOT NULL
), events AS (
  SELECT payload
  FROM parsed
  WHERE payload IS NOT NULL
    AND JSON_VALUE(payload, '$.event_id') IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_VALUE(payload, '$.record_type'), JSON_VALUE(payload, '$.event_id')
    ORDER BY publish_time DESC
  ) = 1
), turns AS (
  SELECT
    JSON_VALUE(payload, '$.context.profile_id') AS profile_id,
    SAFE_CAST(JSON_VALUE(payload, '$.context.profile_version') AS INT64) AS profile_version,
    JSON_VALUE(payload, '$.status') AS status,
    JSON_VALUE(payload, '$.trade_plan_event_id') AS trade_plan_event_id,
    SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) AS created_at,
    SAFE_CAST(JSON_VALUE(payload, '$.model_cost_usd') AS FLOAT64) AS model_cost_usd
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'turn_outcome'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) IN (3, 4)
    AND SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) < @as_of
), consumer_events AS (
  SELECT
    JSON_VALUE(payload, '$.trade_plan_event_id') AS trade_plan_event_id,
    JSON_VALUE(payload, '$.status') AS status,
    SAFE_CAST(JSON_VALUE(payload, '$.pnl') AS FLOAT64) AS pnl,
    SAFE_CAST(JSON_VALUE(payload, '$.recorded_at') AS TIMESTAMP) AS recorded_at
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'consumer_outcome'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) = 1
    AND SAFE_CAST(JSON_VALUE(payload, '$.recorded_at') AS TIMESTAMP) < @as_of
), lifecycle AS (
  SELECT
    trade_plan_event_id,
    LOGICAL_OR(status = 'filled') AS was_filled,
    ARRAY_AGG(
      IF(status IN ('closed', 'settled'), STRUCT(recorded_at, pnl), NULL)
      IGNORE NULLS ORDER BY recorded_at DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS final_outcome
  FROM consumer_events
  GROUP BY trade_plan_event_id
)
SELECT
  MAX(t.created_at) AS last_decision_at,
  COUNTIF(t.created_at >= TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR)) AS decisions_24h,
  COUNTIF(t.created_at >= TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR) AND t.status = 'abstained') AS abstained_24h,
  COUNTIF(t.created_at >= TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR) AND l.was_filled) AS fills_24h,
  COUNTIF(t.created_at >= TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR) AND l.final_outcome.pnl > 0) AS winning_24h,
  COALESCE(SUM(IF(t.created_at >= TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR), l.final_outcome.pnl, 0)), 0) AS realized_pnl_24h,
  COALESCE(SUM(IF(t.created_at >= TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR), t.model_cost_usd, 0)), 0) AS model_cost_24h,
  COUNT(DISTINCT IF(@last_completed IS NOT NULL AND t.created_at > @last_completed,
    CONCAT(t.profile_id, ':', t.profile_version), NULL)) AS revisions_since_last_outcome
FROM turns t
LEFT JOIN lifecycle l USING (trade_plan_event_id)
WHERE t.created_at >= IF(@last_completed IS NULL,
  TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR),
  LEAST(@last_completed, TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR)))
"""


def _positions_reference(archive_ref: str) -> str:
    parts = archive_ref.split(".")
    if len(parts) != 3 or _TABLE_ID.fullmatch(archive_ref) is None:
        raise ValueError("observer archive table is not configured or invalid")
    return f"`{parts[0]}.{parts[1]}.{POSITIONS_TABLE}`"


def _daily_cost_budget() -> float | None:
    raw = os.environ.get("OBSERVER_DAILY_COST_BUDGET_USD")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("observer daily cost budget is invalid") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError("observer daily cost budget is invalid")
    return value


def _optional_timestamp(row: object, key: str) -> datetime | None:
    value = _row_value(row, key)
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("observer query result is invalid")
    return value.astimezone(timezone.utc)


def _optional_count(row: object, key: str) -> int | None:
    if _row_value(row, key) is None:
        return None
    return _count(row, key)


def _health(
    scan_row: object,
    positions_row: object,
    as_of: datetime,
    budget: float | None,
) -> dict[str, object]:
    last_decision = _optional_timestamp(scan_row, "last_decision_at")
    last_completed = _optional_timestamp(positions_row, "last_completed_at")
    decisions = _count(scan_row, "decisions_24h")
    abstained = _count(scan_row, "abstained_24h")
    fills = _count(scan_row, "fills_24h")
    winning = _count(scan_row, "winning_24h")
    if winning > fills or abstained > decisions:
        raise ValueError("observer query result is invalid")
    stuck = _count(positions_row, "stuck_settlements")
    lag = _optional_count(positions_row, "settlement_lag_seconds")
    in_window = WINDOW_START <= as_of.time() < WINDOW_END
    reasons: list[str] = []
    if in_window and (last_decision is None or as_of - last_decision > STALE_OUTCOME_AGE):
        reasons.append("stale_outcome")
    if stuck > 0:
        reasons.append("stuck_settlements")
    cost = _amount(scan_row, "model_cost_24h", non_negative=True)
    if budget is not None and cost > budget:
        reasons.append("daily_cost_budget_exceeded")
    return {
        "schema_version": 1,
        "record_type": "observer_health",
        "as_of": as_of.isoformat(),
        "status": "degraded" if reasons else "healthy",
        "reasons": reasons,
        "in_scheduled_window": in_window,
        "metrics": {
            "last_decision_at": last_decision.isoformat() if last_decision else None,
            "last_completed_at": last_completed.isoformat() if last_completed else None,
            "decisions_24h": decisions,
            "abstained_24h": abstained,
            "abstention_rate_24h": abstained / decisions if decisions else None,
            "fills_24h": fills,
            "winning_24h": winning,
            "realized_pnl_24h": _amount(scan_row, "realized_pnl_24h"),
            "model_cost_24h_usd": cost,
            "daily_cost_budget_usd": budget,
            "stuck_settlements": stuck,
            "settlement_lag_hours_max": lag / 3600 if lag is not None else None,
            "revisions_since_last_outcome": _optional_count(
                scan_row, "revisions_since_last_outcome"
            ),
        },
    }


def query_health(
    as_of: datetime,
    *,
    table: str | None = None,
    client: BigQueryClient | None = None,
) -> dict[str, object]:
    """Answer "is the trading loop producing outcomes?" with two bounded reads."""
    archive_ref = table or os.environ.get("OBSERVER_ARCHIVE_TABLE")
    table_ref = _table_reference(archive_ref)
    positions_ref = _positions_reference(archive_ref or "")
    if as_of.tzinfo is None:
        raise ValueError("observer cutoff must include a UTC offset")
    cutoff = as_of.astimezone(timezone.utc)
    selected_client = client or _default_client()
    positions_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        query_parameters=[
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", cutoff),
            bigquery.ScalarQueryParameter(
                "grace_hours", "INT64", SETTLEMENT_GRACE_HOURS
            ),
        ],
    )
    positions_job: Iterable[object] = selected_client.query(
        _POSITIONS_QUERY.format(table=positions_ref),
        job_config=positions_config,
        timeout=QUERY_TIMEOUT_SECONDS,
    ).result(timeout=QUERY_TIMEOUT_SECONDS)
    positions_row = next(iter(positions_job), None)
    last_completed = (
        _optional_timestamp(positions_row, "last_completed_at") if positions_row else None
    )
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        query_parameters=[
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", cutoff),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", LOOKBACK_DAYS),
            bigquery.ScalarQueryParameter("last_completed", "TIMESTAMP", last_completed),
        ],
    )
    rows: Iterable[object] = selected_client.query(
        _SCAN_QUERY.format(table=table_ref),
        job_config=job_config,
        timeout=QUERY_TIMEOUT_SECONDS,
    ).result(timeout=QUERY_TIMEOUT_SECONDS)
    scan_row = next(iter(rows), None)
    if scan_row is None:
        scan_row = {
            "last_decision_at": None,
            "decisions_24h": 0,
            "abstained_24h": 0,
            "fills_24h": 0,
            "winning_24h": 0,
            "realized_pnl_24h": 0.0,
            "model_cost_24h": 0.0,
            "revisions_since_last_outcome": 0,
        }
    if positions_row is None:
        positions_row = {
            "stuck_settlements": 0,
            "settlement_lag_seconds": None,
            "last_completed_at": None,
        }
    return _health(scan_row, positions_row, cutoff, _daily_cost_budget())
