import unittest
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from observer.app import create_app
from observer.health import MAXIMUM_BYTES_BILLED, query_health

# 2026-11-13 is a Friday; 14:30 UTC is inside the 13:40-23:00 scheduled window.
NOW = datetime(2026, 11, 13, 14, 30, tzinfo=timezone.utc)
LATE = datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc)


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "last_decision_at": NOW - timedelta(minutes=30),
        "last_completed_at": NOW - timedelta(hours=2),
        "decisions_24h": 8,
        "abstained_24h": 6,
        "fills_24h": 2,
        "winning_24h": 1,
        "realized_pnl_24h": -0.25,
        "model_cost_24h": 0.5,
        "stuck_settlements": 0,
        "settlement_lag_seconds": 7200,
        "revisions_since_last_outcome": 0,
    }
    value.update(changes)
    return value


def client_with(rows: list[dict[str, object]]) -> Mock:
    job = Mock()
    job.result.return_value = rows
    client = Mock()
    client.query.return_value = job
    return client


class HealthQueryTests(unittest.TestCase):
    def test_query_returns_one_bounded_read_of_journey_health(self) -> None:
        client = client_with([row()])

        result = query_health(NOW, table="project.dataset.raw_events", client=client)

        sql = client.query.call_args.args[0]
        job_config = client.query.call_args.kwargs["job_config"]
        self.assertIn("FROM `project.dataset.raw_events`", sql)
        self.assertNotIn("``", sql)
        self.assertIn("publish_time >=", sql)
        self.assertIn("publish_time < @as_of", sql)
        self.assertIn("PARTITION BY JSON_VALUE(payload, '$.record_type')", sql)
        self.assertIn("turn_outcome", sql)
        self.assertIn("consumer_outcome", sql)
        self.assertIn("trade_plan_ready", sql)
        self.assertEqual(job_config.maximum_bytes_billed, MAXIMUM_BYTES_BILLED)
        parameters = {item.name: item.value for item in job_config.query_parameters}
        self.assertEqual(parameters["as_of"], NOW)
        self.assertEqual(parameters["lookback_days"], 90)
        self.assertEqual(parameters["grace_hours"], 24)
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["reasons"], [])
        self.assertTrue(result["in_scheduled_window"])
        metrics = cast(dict[str, object], result["metrics"])
        self.assertEqual(metrics["decisions_24h"], 8)
        self.assertEqual(metrics["abstention_rate_24h"], 0.75)
        self.assertEqual(metrics["fills_24h"], 2)
        self.assertEqual(metrics["winning_24h"], 1)
        self.assertEqual(metrics["realized_pnl_24h"], -0.25)
        self.assertEqual(metrics["model_cost_24h_usd"], 0.5)
        self.assertIsNone(metrics["daily_cost_budget_usd"])
        self.assertEqual(metrics["settlement_lag_hours_max"], 2.0)
        self.assertEqual(metrics["revisions_since_last_outcome"], 0)

    def test_in_window_silence_is_degraded(self) -> None:
        stale = row(last_decision_at=NOW - timedelta(hours=5))
        result = query_health(NOW, table="project.dataset.raw_events", client=client_with([stale]))
        self.assertEqual(result["reasons"], ["stale_outcome"])
        self.assertEqual(result["status"], "degraded")

    def test_overnight_silence_is_by_design(self) -> None:
        stale = row(last_decision_at=NOW - timedelta(hours=5))
        result = query_health(LATE, table="project.dataset.raw_events", client=client_with([stale]))
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["status"], "healthy")
        self.assertFalse(result["in_scheduled_window"])

    def test_stuck_settlements_degrade_day_and_night(self) -> None:
        stuck = row(stuck_settlements=1)
        for as_of in (NOW, LATE):
            with self.subTest(as_of=as_of):
                result = query_health(as_of, table="project.dataset.raw_events", client=client_with([stuck]))
                self.assertEqual(result["reasons"], ["stuck_settlements"])

    def test_cost_budget_exceeded_only_when_configured(self) -> None:
        with patch.dict("os.environ", {"OBSERVER_DAILY_COST_BUDGET_USD": "0.25"}):
            result = query_health(NOW, table="project.dataset.raw_events", client=client_with([row()]))
        metrics = cast(dict[str, object], result["metrics"])
        self.assertEqual(metrics["daily_cost_budget_usd"], 0.25)
        self.assertEqual(result["reasons"], ["daily_cost_budget_exceeded"])

        with patch.dict("os.environ", {"OBSERVER_DAILY_COST_BUDGET_USD": "1.0"}):
            result = query_health(NOW, table="project.dataset.raw_events", client=client_with([row()]))
        self.assertEqual(result["reasons"], [])

    def test_invalid_budget_fails_closed(self) -> None:
        for invalid in ("-1", "not-a-number", "inf"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ", {"OBSERVER_DAILY_COST_BUDGET_USD": invalid}
            ), self.assertRaises(ValueError):
                query_health(NOW, table="project.dataset.raw_events", client=client_with([row()]))

    def test_empty_archive_is_healthy_outside_the_window(self) -> None:
        result = query_health(LATE, table="project.dataset.raw_events", client=client_with([]))
        self.assertEqual(result["status"], "healthy")
        metrics = cast(dict[str, object], result["metrics"])
        self.assertIsNone(metrics["last_decision_at"])
        self.assertIsNone(metrics["last_completed_at"])
        self.assertEqual(metrics["decisions_24h"], 0)
        self.assertEqual(metrics["model_cost_24h_usd"], 0.0)

    def test_invalid_aggregate_result_fails_closed(self) -> None:
        client = client_with([row(winning_24h=3)])
        with self.assertRaises(ValueError):
            query_health(NOW, table="project.dataset.raw_events", client=client)

    def test_invalid_table_identifier_is_rejected_before_query(self) -> None:
        client = client_with([])
        with self.assertRaises(ValueError):
            query_health(NOW, table="project.dataset.raw_events; DROP TABLE x", client=client)
        client.query.assert_not_called()


class HealthEndpointTests(unittest.TestCase):
    def test_health_route_returns_journey_status(self) -> None:
        archive = client_with([row()])
        client = TestClient(
            create_app(table="project.dataset.raw_events", client=archive, clock=lambda: NOW)
        )

        response = client.get("/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertEqual(response.json()["record_type"], "observer_health")

    def test_health_route_failure_is_sanitized(self) -> None:
        archive = Mock()
        archive.query.side_effect = ValueError("internal credential detail")
        client = TestClient(create_app(table="project.dataset.raw_events", client=archive))

        response = client.get("/v1/health")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("credential", response.text)


if __name__ == "__main__":
    unittest.main()
