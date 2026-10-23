import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from chrysopoeia.bigquery_history import (
    MAXIMUM_BYTES_BILLED,
    query_context_history,
)
from chrysopoeia.context import ContextIdentity


class BigQueryHistoryTests(unittest.TestCase):
    def test_query_is_partition_bounded_profile_scoped_and_byte_capped(self) -> None:
        row = {
            "profile_version_count": 1,
            "decision_count": 12,
            "plan_ready_count": 4,
            "abstained_count": 5,
            "rejected_count": 3,
            "consumer_rejected_count": 1,
            "filled_count": 3,
            "completed_trade_count": 2,
            "winning_trade_count": 1,
            "realized_pnl_usd": -0.25,
            "outcome_watermark": datetime(2026, 10, 20, tzinfo=timezone.utc),
        }
        job = Mock()
        job.result.return_value = [row]
        client = Mock()
        client.query.return_value = job
        identity = ContextIdentity("polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown", 1, "a" * 64)
        as_of = datetime(2026, 10, 21, tzinfo=timezone.utc)

        result = query_context_history(
            identity,
            as_of,
            table="project.dataset.raw_events",
            client=client,
        )

        sql = client.query.call_args.args[0]
        job_config = client.query.call_args.kwargs["job_config"]
        self.assertIn("FROM `project.dataset.raw_events`", sql)
        self.assertNotIn("``", sql)
        self.assertIn("publish_time >=", sql)
        self.assertIn("publish_time < @as_of", sql)
        self.assertIn("$.context.scope_key", sql)
        self.assertIn("$.context.profile_id", sql)
        self.assertIn("consumer_outcome", sql)
        self.assertIn("PARTITION BY JSON_VALUE(payload, '$.record_type')", sql)
        self.assertEqual(job_config.maximum_bytes_billed, MAXIMUM_BYTES_BILLED)
        parameters = {item.name: item.value for item in job_config.query_parameters}
        self.assertEqual(parameters["scope_key"], identity.scope_key)
        self.assertEqual(parameters["profile_id"], identity.profile_id)
        self.assertEqual(parameters["profile_version"], identity.profile_version)
        self.assertEqual(parameters["manifest_hash"], identity.manifest_hash)
        self.assertEqual(result["decision_count"], 12)
        self.assertEqual(result["profile_version_count"], 1)
        self.assertEqual(result["realized_pnl_usd"], -0.25)
        self.assertEqual(result["outcome_watermark"], "2026-10-20T00:00:00+00:00")

    def test_invalid_table_identifier_is_rejected_before_query(self) -> None:
        client = Mock()
        identity = ContextIdentity("polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown", 1, "a" * 64)

        with self.assertRaises(ValueError):
            query_context_history(
                identity,
                datetime.now(timezone.utc),
                table="project.dataset.raw_events; DROP TABLE x",
                client=client,
            )

        client.query.assert_not_called()

    def test_invalid_aggregate_result_fails_closed(self) -> None:
        job = Mock()
        job.result.return_value = [{"decision_count": "not-a-count"}]
        client = Mock()
        client.query.return_value = job
        identity = ContextIdentity("polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown", 1, "a" * 64)

        with self.assertRaises(ValueError):
            query_context_history(
                identity,
                datetime.now(timezone.utc),
                table="project.dataset.raw_events",
                client=client,
            )
