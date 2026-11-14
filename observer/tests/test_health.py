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


def scan_row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "last_decision_at": NOW - timedelta(minutes=30),
        "decisions_24h": 8,
        "abstained_24h": 6,
        "fills_24h": 2,
        "winning_24h": 1,
        "realized_pnl_24h": -0.25,
        "model_cost_24h": 0.5,
        "revisions_since_last_outcome": 0,
    }
    value.update(changes)
    return value


def positions_row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "stuck_settlements": 0,
        "settlement_lag_seconds": 7200,
        "last_completed_at": NOW - timedelta(hours=2),
    }
    value.update(changes)
    return value


def client_with(
    scan_rows: list[dict[str, object]],
    positions_rows: list[dict[str, object]] | None = None,
) -> Mock:
    positions_job = Mock()
    positions_job.result.return_value = positions_rows or [positions_row()]
    scan_job = Mock()
    scan_job.result.return_value = scan_rows
    client = Mock()
    client.query.side_effect = [positions_job, scan_job]
    return client


class HealthQueryTests(unittest.TestCase):
    def test_health_reads_the_projection_then_a_bounded_scan(self) -> None:
        client = client_with([scan_row()])

        result = query_health(NOW, table="project.dataset.raw_events", client=client)

        positions_sql = client.query.call_args_list[0].args[0]
        positions_config = client.query.call_args_list[0].kwargs["job_config"]
        scan_sql = client.query.call_args_list[1].args[0]
        scan_config = client.query.call_args_list[1].kwargs["job_config"]
        self.assertIn("FROM `project.dataset.open_positions`", positions_sql)
        self.assertNotIn("``", positions_sql)
        self.assertIn("COUNTIF(status = 'open'", positions_sql)
        self.assertIn("FROM `project.dataset.raw_events`", scan_sql)
        self.assertIn("publish_time >=", scan_sql)
        self.assertIn("publish_time < @as_of", scan_sql)
        self.assertIn("PARTITION BY JSON_VALUE(payload, '$.record_type')", scan_sql)
        self.assertIn("TIMESTAMP_SUB(@as_of, INTERVAL 24 HOUR)", scan_sql)
        self.assertIn("IF(@last_completed IS NULL", scan_sql)
        positions_parameters = {
            item.name: item.value for item in positions_config.query_parameters
        }
        self.assertEqual(positions_parameters["grace_hours"], 24)
        scan_parameters = {item.name: item.value for item in scan_config.query_parameters}
        self.assertEqual(scan_parameters["as_of"], NOW)
        self.assertEqual(scan_parameters["lookback_days"], 90)
        self.assertEqual(
            scan_parameters["last_completed"], NOW - timedelta(hours=2)
        )
        self.assertEqual(
            positions_config.maximum_bytes_billed, MAXIMUM_BYTES_BILLED
        )
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
        self.assertEqual(
            metrics["last_completed_at"], (NOW - timedelta(hours=2)).isoformat()
        )

    def test_scan_starts_at_the_last_completed_trade_when_older(self) -> None:
        client = client_with(
            [scan_row()],
            [positions_row(last_completed_at=NOW - timedelta(days=3))],
        )

        query_health(NOW, table="project.dataset.raw_events", client=client)

        scan_parameters = {
            item.name: item.value
            for item in client.query.call_args_list[1].kwargs["job_config"].query_parameters
        }
        self.assertEqual(scan_parameters["last_completed"], NOW - timedelta(days=3))

    def test_scan_starts_at_24_hours_when_the_last_trade_is_recent(self) -> None:
        client = client_with(
            [scan_row()],
            [positions_row(last_completed_at=NOW - timedelta(minutes=5))],
        )

        query_health(NOW, table="project.dataset.raw_events", client=client)

        scan_parameters = {
            item.name: item.value
            for item in client.query.call_args_list[1].kwargs["job_config"].query_parameters
        }
        self.assertEqual(scan_parameters["last_completed"], NOW - timedelta(minutes=5))

    def test_no_completed_trade_passes_null_and_zeroes_revisions(self) -> None:
        client = client_with(
            [scan_row(revisions_since_last_outcome=0)],
            [positions_row(last_completed_at=None)],
        )

        result = query_health(NOW, table="project.dataset.raw_events", client=client)

        scan_parameters = {
            item.name: item.value
            for item in client.query.call_args_list[1].kwargs["job_config"].query_parameters
        }
        self.assertIsNone(scan_parameters["last_completed"])
        metrics = cast(dict[str, object], result["metrics"])
        self.assertEqual(metrics["revisions_since_last_outcome"], 0)

    def test_in_window_silence_is_degraded(self) -> None:
        stale = scan_row(last_decision_at=NOW - timedelta(hours=5))
        result = query_health(NOW, table="project.dataset.raw_events", client=client_with([stale]))
        self.assertEqual(result["reasons"], ["stale_outcome"])
        self.assertEqual(result["status"], "degraded")

    def test_overnight_silence_is_by_design(self) -> None:
        stale = scan_row(last_decision_at=NOW - timedelta(hours=5))
        result = query_health(LATE, table="project.dataset.raw_events", client=client_with([stale]))
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["status"], "healthy")
        self.assertFalse(result["in_scheduled_window"])

    def test_projection_stuck_settlements_degrade_day_and_night(self) -> None:
        stuck = [positions_row(stuck_settlements=1)]
        for as_of in (NOW, LATE):
            with self.subTest(as_of=as_of):
                result = query_health(as_of, table="project.dataset.raw_events", client=client_with([scan_row()], stuck))
                self.assertEqual(result["reasons"], ["stuck_settlements"])

    def test_cost_budget_exceeded_only_when_configured(self) -> None:
        with patch.dict("os.environ", {"OBSERVER_DAILY_COST_BUDGET_USD": "0.25"}):
            result = query_health(NOW, table="project.dataset.raw_events", client=client_with([scan_row()]))
        metrics = cast(dict[str, object], result["metrics"])
        self.assertEqual(metrics["daily_cost_budget_usd"], 0.25)
        self.assertEqual(result["reasons"], ["daily_cost_budget_exceeded"])

        with patch.dict("os.environ", {"OBSERVER_DAILY_COST_BUDGET_USD": "1.0"}):
            result = query_health(NOW, table="project.dataset.raw_events", client=client_with([scan_row()]))
        self.assertEqual(result["reasons"], [])

    def test_invalid_budget_fails_closed(self) -> None:
        for invalid in ("-1", "not-a-number", "inf"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ", {"OBSERVER_DAILY_COST_BUDGET_USD": invalid}
            ), self.assertRaises(ValueError):
                query_health(NOW, table="project.dataset.raw_events", client=client_with([scan_row()]))

    def test_empty_results_are_healthy_outside_the_window(self) -> None:
        result = query_health(
            LATE,
            table="project.dataset.raw_events",
            client=client_with([], [positions_row(last_completed_at=None)]),
        )
        self.assertEqual(result["status"], "healthy")
        metrics = cast(dict[str, object], result["metrics"])
        self.assertIsNone(metrics["last_decision_at"])
        self.assertIsNone(metrics["last_completed_at"])
        self.assertEqual(metrics["decisions_24h"], 0)
        self.assertEqual(metrics["model_cost_24h_usd"], 0.0)

    def test_invalid_aggregate_result_fails_closed(self) -> None:
        client = client_with([scan_row(winning_24h=3)])
        with self.assertRaises(ValueError):
            query_health(NOW, table="project.dataset.raw_events", client=client)

    def test_invalid_positions_result_fails_closed(self) -> None:
        client = client_with([scan_row()], [positions_row(stuck_settlements="no")])
        with self.assertRaises(ValueError):
            query_health(NOW, table="project.dataset.raw_events", client=client)

    def test_invalid_table_identifier_is_rejected_before_query(self) -> None:
        client = client_with([])
        with self.assertRaises(ValueError):
            query_health(NOW, table="project.dataset.raw_events; DROP TABLE x", client=client)
        client.query.assert_not_called()


class HealthEndpointTests(unittest.TestCase):
    def test_health_route_returns_journey_status(self) -> None:
        archive = client_with([scan_row()])
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
