import math
import os
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import quote

from google.cloud import bigquery

from chrysopoeia.context import ContextIdentity

LOOKBACK_DAYS = 90
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
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY JSON_VALUE(payload, '$.record_type'), JSON_VALUE(payload, '$.event_id')
    ORDER BY publish_time DESC
  ) = 1
), turns AS (
  SELECT
    JSON_VALUE(payload, '$.trade_plan_event_id') AS trade_plan_event_id,
    JSON_VALUE(payload, '$.status') AS status,
    SAFE_CAST(JSON_VALUE(payload, '$.context.profile_version') AS INT64) AS profile_version
  FROM events
  WHERE JSON_VALUE(payload, '$.record_type') = 'turn_outcome'
    AND SAFE_CAST(JSON_VALUE(payload, '$.schema_version') AS INT64) IN (3, 4)
    AND JSON_VALUE(payload, '$.context.scope_key') = @scope_key
    AND JSON_VALUE(payload, '$.context.profile_id') = @profile_id
    AND SAFE_CAST(JSON_VALUE(payload, '$.context.profile_version') AS INT64) = @profile_version
    AND JSON_VALUE(payload, '$.context.manifest_hash') = @manifest_hash
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
    LOGICAL_OR(status = 'rejected') AS was_rejected,
    ARRAY_AGG(
      IF(status IN ('closed', 'settled'), STRUCT(status, pnl, recorded_at), NULL)
      IGNORE NULLS ORDER BY recorded_at DESC LIMIT 1
    )[SAFE_OFFSET(0)] AS final_outcome
  FROM consumer_events
  GROUP BY trade_plan_event_id
)
SELECT
  COUNT(DISTINCT turns.profile_version) AS profile_version_count,
  COUNT(*) AS decision_count,
  COUNTIF(turns.status = 'plan_ready') AS plan_ready_count,
  COUNTIF(turns.status = 'abstained') AS abstained_count,
  COUNTIF(turns.status IN ('plan_check_rejected', 'reviewer_rejected', 'policy_rejected')) AS rejected_count,
  COUNTIF(lifecycle.was_rejected) AS consumer_rejected_count,
  COUNTIF(lifecycle.was_filled) AS filled_count,
  COUNTIF(lifecycle.final_outcome IS NOT NULL) AS completed_trade_count,
  COUNTIF(lifecycle.final_outcome.pnl > 0) AS winning_trade_count,
  COALESCE(SUM(lifecycle.final_outcome.pnl), 0) AS realized_pnl_usd,
  MAX(lifecycle.final_outcome.recorded_at) AS outcome_watermark
FROM turns
LEFT JOIN lifecycle USING (trade_plan_event_id)
"""


class QueryJob(Protocol):
    def result(self, *, timeout: int) -> Iterable[object]: ...


class BigQueryClient(Protocol):
    def query(self, query: str, *, job_config: object, timeout: int) -> QueryJob: ...


def _table_reference(value: str | None) -> str:
    if not isinstance(value, str) or _TABLE_ID.fullmatch(value) is None:
        raise ValueError("BigQuery history table is not configured or invalid")
    return f"`{value}`"


def bigquery_console_url(table: str) -> str:
    _table_reference(table)
    project, dataset, name = table.split(".")
    return (
        "https://console.cloud.google.com/bigquery?project="
        + quote(project, safe="-_")
        + "&ws=!1m4!1m3!3m2!1s"
        + quote(project, safe="-_")
        + "!2s"
        + quote(dataset, safe="-_")
        + "!3s"
        + quote(name, safe="-_")
    )


def _row_value(row: object, key: str) -> object:
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, None)


def _count(row: object, key: str) -> int:
    value = _row_value(row, key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("BigQuery history result is invalid")
    return value


def _amount(row: object, key: str) -> float:
    value = _row_value(row, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("BigQuery history result is invalid")
    return float(value)


def query_context_history(
    context: ContextIdentity,
    as_of: datetime,
    *,
    table: str | None = None,
    client: BigQueryClient | None = None,
) -> dict[str, object]:
    """Return bounded aggregate outcomes for one stable context, never raw event text."""
    table_ref = _table_reference(table or os.environ.get("CHRYSOPOEIA_HISTORY_TABLE"))
    if re.fullmatch(r"[0-9a-f]{64}", context.manifest_hash) is None:
        raise ValueError("context profile hash is invalid")
    if as_of.tzinfo is None:
        raise ValueError("history cutoff must include a UTC offset")
    cutoff = as_of.astimezone(timezone.utc)
    location = os.environ.get("CHRYSOPOEIA_HISTORY_LOCATION")
    selected_client = client or (
        bigquery.Client(location=location) if location else bigquery.Client()
    )
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        query_parameters=[
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", cutoff),
            bigquery.ScalarQueryParameter("lookback_days", "INT64", LOOKBACK_DAYS),
            bigquery.ScalarQueryParameter("scope_key", "STRING", context.scope_key),
            bigquery.ScalarQueryParameter("profile_id", "STRING", context.profile_id),
            bigquery.ScalarQueryParameter("profile_version", "INT64", context.profile_version),
            bigquery.ScalarQueryParameter("manifest_hash", "STRING", context.manifest_hash),
        ],
    )
    query = _QUERY.format(table=table_ref)
    rows = selected_client.query(
        query, job_config=job_config, timeout=QUERY_TIMEOUT_SECONDS
    ).result(timeout=QUERY_TIMEOUT_SECONDS)
    row = next(iter(rows), None)
    if row is None:
        counts = {
            "profile_version_count": 0,
            "decision_count": 0,
            "plan_ready_count": 0,
            "abstained_count": 0,
            "rejected_count": 0,
            "consumer_rejected_count": 0,
            "filled_count": 0,
            "completed_trade_count": 0,
            "winning_trade_count": 0,
            "realized_pnl_usd": 0.0,
            "outcome_watermark": None,
        }
    else:
        counts = {
            key: _count(row, key)
            for key in (
                "profile_version_count",
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
        counts["realized_pnl_usd"] = _amount(row, "realized_pnl_usd")
        watermark = _row_value(row, "outcome_watermark")
        counts["outcome_watermark"] = (
            watermark.isoformat() if isinstance(watermark, datetime) else None
        )
    return {
        "scope_key": context.scope_key,
        "profile_id": context.profile_id,
        "profile_version": context.profile_version,
        "as_of": cutoff.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        **counts,
    }
