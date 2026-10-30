import unittest
from datetime import datetime, timezone
from typing import cast
from unittest.mock import Mock

from observer.insights import (
    COMPLETED_TRADE_GATE,
    CONTEXT_LIMIT,
    MAXIMUM_BYTES_BILLED,
    query_insights,
)

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "scope_key": "polymarket:series:btc-updown-5m",
        "profile_id": "crypto.btcusd.5m.updown",
        "profile_version": 1,
        "manifest_hash": "a" * 64,
        "decision_count": 5,
        "plan_ready_count": 2,
        "abstained_count": 2,
        "rejected_count": 1,
        "consumer_rejected_count": 1,
        "filled_count": 2,
        "completed_trade_count": 1,
        "winning_trade_count": 1,
        "realized_pnl_usd": -0.25,
        "actual_model_cost_usd": 0.5,
        "reserved_model_cost_usd": None,
        "outcome_watermark": datetime(2026, 10, 28, tzinfo=timezone.utc),
    }
    value.update(changes)
    return value


def client_with(rows: list[dict[str, object]]) -> Mock:
    job = Mock()
    job.result.return_value = rows
    client = Mock()
    client.query.return_value = job
    return client


class InsightQueryTests(unittest.TestCase):
    def test_query_returns_deduplicated_profile_scoped_bounded_aggregates(self) -> None:
        client = client_with([row()])

        result = query_insights(NOW, table="project.dataset.raw_events", client=client)

        sql = client.query.call_args.args[0]
        job_config = client.query.call_args.kwargs["job_config"]
        self.assertIn("FROM `project.dataset.raw_events`", sql)
        self.assertNotIn("``", sql)
        self.assertIn("publish_time >=", sql)
        self.assertIn("publish_time < @as_of", sql)
        self.assertIn("PARTITION BY JSON_VALUE(payload, '$.record_type')", sql)
        self.assertIn("consumer_outcome", sql)
        self.assertIn("IN (3, 4)", sql)
        self.assertIn("COUNTIF(turns.reserved_model_cost_usd IS NULL) = 0", sql)
        self.assertIn("GROUP BY scope_key, profile_id, profile_version, manifest_hash", sql)
        self.assertEqual(job_config.maximum_bytes_billed, MAXIMUM_BYTES_BILLED)
        self.assertEqual(client.query.call_args.kwargs["timeout"], 20)
        client.query.return_value.result.assert_called_once_with(timeout=20)
        parameters = {item.name: item.value for item in job_config.query_parameters}
        self.assertEqual(parameters["as_of"], NOW)
        self.assertEqual(parameters["lookback_days"], 90)
        context = cast(list[dict[str, object]], result["contexts"])[0]
        self.assertEqual(context["decision_count"], 5)
        self.assertEqual(context["filled_count"], 2)
        self.assertEqual(context["win_rate"], 1.0)
        self.assertEqual(context["realized_pnl_usd"], -0.25)
        self.assertEqual(context["actual_model_cost_usd"], 0.5)
        self.assertIsNone(context["reserved_model_cost_usd"])
        self.assertEqual(
            context["campaign"],
            {
                "required_completed_trades": COMPLETED_TRADE_GATE,
                "remaining_completed_trades": 19,
                "trade_gate_met": False,
            },
        )
        self.assertEqual(context["outcome_watermark"], "2026-10-28T00:00:00+00:00")

    def test_twenty_completed_trades_open_the_profile_gate(self) -> None:
        client = client_with([row(completed_trade_count=20, winning_trade_count=10)])

        result = query_insights(NOW, table="project.dataset.raw_events", client=client)

        context = cast(list[dict[str, object]], result["contexts"])[0]
        self.assertEqual(context["win_rate"], 0.5)
        campaign = cast(dict[str, object], context["campaign"])
        self.assertEqual(campaign["remaining_completed_trades"], 0)
        self.assertTrue(campaign["trade_gate_met"])

    def test_complete_v4_group_returns_reserved_cost(self) -> None:
        client = client_with([row(reserved_model_cost_usd=1.25)])

        result = query_insights(NOW, table="project.dataset.raw_events", client=client)

        context = cast(list[dict[str, object]], result["contexts"])[0]
        self.assertEqual(context["reserved_model_cost_usd"], 1.25)

    def test_invalid_reserved_aggregate_fails_closed(self) -> None:
        for invalid in (-0.1, float("inf"), "not-an-amount"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                query_insights(
                    NOW,
                    table="project.dataset.raw_events",
                    client=client_with([row(reserved_model_cost_usd=invalid)]),
                )

    def test_result_is_bounded_and_reports_truncation(self) -> None:
        client = client_with([row() for _ in range(CONTEXT_LIMIT + 1)])

        result = query_insights(NOW, table="project.dataset.raw_events", client=client)

        contexts = cast(list[dict[str, object]], result["contexts"])
        self.assertEqual(len(contexts), CONTEXT_LIMIT)
        self.assertTrue(result["truncated"])

    def test_invalid_table_identifier_is_rejected_before_query(self) -> None:
        client = client_with([])

        with self.assertRaises(ValueError):
            query_insights(NOW, table="project.dataset.raw_events; DROP TABLE x", client=client)

        client.query.assert_not_called()

    def test_invalid_aggregate_result_fails_closed(self) -> None:
        client = client_with([row(decision_count="not-a-count")])

        with self.assertRaises(ValueError):
            query_insights(NOW, table="project.dataset.raw_events", client=client)
