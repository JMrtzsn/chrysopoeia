import math
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol

from google.cloud import bigquery

LOOKBACK_DAYS = 90
CONTEXT_LIMIT = 100
COMPLETED_TRADE_GATE = 20
MAXIMUM_BYTES_BILLED = 100 * 1024 * 1024
QUERY_TIMEOUT_SECONDS = 20
_TABLE_ID = re.compile(r"[A-Za-z0-9-]+\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*")

_QUERY = """
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
    JSON_VALUE(payload, '$.context.scope_key') AS scope_key,
    JSON_VALUE(payload, '$.context.profile_id') AS profile_id,
    SAFE_CAST(JSON_VALUE(payload, '$.context.profile_version') AS INT64) AS profile_version,
    JSON_VALUE(payload, '$.context.manifest_hash') AS manifest_hash,
    JSON_VALUE(payload, '$.trade_plan_event_id') AS trade_plan_event_id,
    JSON_VALUE(payload, '$.status') AS status,
    SAFE_CAST(JSON_VALUE(payload, '$.model_cost_usd') AS FLOAT64) AS model_cost_usd,
    SAFE_CAST(JSON_VALUE(payload, '$.reserved_model_cost_usd') AS FLOAT64) AS reserved_model_cost_usd
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'turn_outcome'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) IN (3, 4)
    AND SAFE_CAST(JSON_VALUE(payload, '$.created_at') AS TIMESTAMP) < @as_of
    AND JSON_VALUE(payload, '$.context.scope_key') IS NOT NULL
    AND JSON_VALUE(payload, '$.context.profile_id') IS NOT NULL
    AND SAFE_CAST(JSON_VALUE(payload, '$.context.profile_version') AS INT64) > 0
    AND JSON_VALUE(payload, '$.context.manifest_hash') IS NOT NULL
), consumer_events AS (
  SELECT
    JSON_VALUE(payload, '$.event_id') AS event_id,
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
    LOGICAL_OR(status = 'rejected') AS was_rejected,
    ARRAY_AGG(
      IF(status IN ('closed', 'settled'), STRUCT(status, pnl, recorded_at), NULL)
      IGNORE NULLS ORDER BY recorded_at DESC, event_id DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS final_outcome
  FROM consumer_events
  GROUP BY trade_plan_event_id
)
SELECT
  turns.scope_key,
  turns.profile_id,
  turns.profile_version,
  turns.manifest_hash,
  COUNT(*) AS decision_count,
  COUNTIF(turns.status = 'plan_ready') AS plan_ready_count,
  COUNTIF(turns.status = 'abstained') AS abstained_count,
  COUNTIF(turns.status IN ('plan_check_rejected', 'reviewer_rejected', 'policy_rejected')) AS rejected_count,
  COUNTIF(lifecycle.was_rejected) AS consumer_rejected_count,
  COUNTIF(lifecycle.was_filled) AS filled_count,
  COUNTIF(lifecycle.final_outcome IS NOT NULL) AS completed_trade_count,
  COUNTIF(lifecycle.final_outcome.pnl > 0) AS winning_trade_count,
  COALESCE(SUM(lifecycle.final_outcome.pnl), 0) AS realized_pnl_usd,
  COALESCE(SUM(turns.model_cost_usd), 0) AS actual_model_cost_usd,
  IF(
    COUNTIF(turns.reserved_model_cost_usd IS NULL) = 0,
    SUM(turns.reserved_model_cost_usd),
    NULL
  ) AS reserved_model_cost_usd,
  MAX(lifecycle.final_outcome.recorded_at) AS outcome_watermark
FROM turns
LEFT JOIN lifecycle USING (trade_plan_event_id)
GROUP BY scope_key, profile_id, profile_version, manifest_hash
ORDER BY scope_key, profile_id, profile_version, manifest_hash
LIMIT 101
"""


class QueryJob(Protocol):
    def result(self, *, timeout: int) -> Iterable[object]: ...


class BigQueryClient(Protocol):
    def query(self, query: str, *, job_config: object, timeout: int) -> QueryJob: ...


@lru_cache(maxsize=1)
def _default_client() -> bigquery.Client:
    location = os.environ.get("OBSERVER_BIGQUERY_LOCATION")
    return bigquery.Client(location=location) if location else bigquery.Client()


def _table_reference(value: str | None) -> str:
    if not isinstance(value, str) or _TABLE_ID.fullmatch(value) is None:
        raise ValueError("observer archive table is not configured or invalid")
    return f"`{value}`"


def _row_value(row: object, key: str) -> object:
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(row, key, None)


def _count(row: object, key: str) -> int:
    value = _row_value(row, key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("observer query result is invalid")
    return value


def _amount(row: object, key: str, *, non_negative: bool = False) -> float:
    value = _row_value(row, key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (non_negative and value < 0)
    ):
        raise ValueError("observer query result is invalid")
    return float(value)


def _optional_non_negative_amount(row: object, key: str) -> float | None:
    if _row_value(row, key) is None:
        return None
    return _amount(row, key, non_negative=True)


def _context(row: object) -> dict[str, object]:
    identity: dict[str, object] = {}
    for key in ("scope_key", "profile_id", "manifest_hash"):
        value = _row_value(row, key)
        if not isinstance(value, str) or not value:
            raise ValueError("observer query result is invalid")
        identity[key] = value
    identity["profile_version"] = _count(row, "profile_version")
    if identity["profile_version"] < 1:
        raise ValueError("observer query result is invalid")

    counts = {
        key: _count(row, key)
        for key in (
            "decision_count",
            "plan_ready_count",
            "abstained_count",
            "rejected_count",
            "consumer_rejected_count",
            "filled_count",
            "completed_trade_count",
            "winning_trade_count",
        )
    }
    completed = counts["completed_trade_count"]
    winning = counts["winning_trade_count"]
    if winning > completed:
        raise ValueError("observer query result is invalid")
    watermark = _row_value(row, "outcome_watermark")
    return {
        **identity,
        **counts,
        "win_rate": winning / completed if completed else None,
        "realized_pnl_usd": _amount(row, "realized_pnl_usd"),
        "actual_model_cost_usd": _amount(row, "actual_model_cost_usd", non_negative=True),
        "reserved_model_cost_usd": _optional_non_negative_amount(
            row, "reserved_model_cost_usd"
        ),
        "campaign": {
            "required_completed_trades": COMPLETED_TRADE_GATE,
            "remaining_completed_trades": max(0, COMPLETED_TRADE_GATE - completed),
            "trade_gate_met": completed >= COMPLETED_TRADE_GATE,
        },
        "outcome_watermark": watermark.isoformat() if isinstance(watermark, datetime) else None,
    }


def query_insights(
    as_of: datetime,
    *,
    table: str | None = None,
    client: BigQueryClient | None = None,
) -> dict[str, object]:
    """Return bounded, profile-scoped aggregates without retaining a projection."""
    table_ref = _table_reference(table or os.environ.get("OBSERVER_ARCHIVE_TABLE"))
    if as_of.tzinfo is None:
        raise ValueError("observer cutoff must include a UTC offset")
    cutoff = as_of.astimezone(timezone.utc)
    selected_client = client or _default_client()
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        query_parameters=[
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", cutoff),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", LOOKBACK_DAYS),
        ],
    )
    rows = selected_client.query(
        _QUERY.format(table=table_ref),
        job_config=job_config,
        timeout=QUERY_TIMEOUT_SECONDS,
    ).result(timeout=QUERY_TIMEOUT_SECONDS)
    contexts = [_context(row) for row in rows]
    return {
        "schema_version": 1,
        "record_type": "observer_insight",
        "as_of": cutoff.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "context_limit": CONTEXT_LIMIT,
        "truncated": len(contexts) > CONTEXT_LIMIT,
        "contexts": contexts[:CONTEXT_LIMIT],
    }
