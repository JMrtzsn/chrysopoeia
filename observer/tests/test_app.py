import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from observer.app import create_app

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


class ObserverAppTests(unittest.TestCase):
    def test_insights_are_pulled_from_bigquery_at_read_time(self) -> None:
        job = Mock()
        job.result.return_value = []
        archive = Mock()
        archive.query.return_value = job
        client = TestClient(
            create_app(table="project.dataset.raw_events", client=archive, clock=lambda: NOW)
        )

        first = client.get("/v1/insights")
        second = client.get("/v1/insights")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["contexts"], [])
        self.assertEqual(first.json()["as_of"], NOW.isoformat())
        self.assertEqual(second.status_code, 200)
        self.assertEqual(archive.query.call_count, 2)

    def test_health_does_not_query_the_archive(self) -> None:
        archive = Mock()
        client = TestClient(create_app(table="project.dataset.raw_events", client=archive))

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        archive.query.assert_not_called()

    def test_archive_failure_is_sanitized(self) -> None:
        archive = Mock()
        archive.query.side_effect = ValueError("internal credential detail")
        client = TestClient(create_app(table="project.dataset.raw_events", client=archive))

        response = client.get("/v1/insights")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("credential", response.text)
