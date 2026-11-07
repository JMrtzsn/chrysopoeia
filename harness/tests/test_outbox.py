import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chrysopoeia import cli
from chrysopoeia.accounting import (
    JournalError,
    acknowledge_event,
    cycle_turn_id,
    enqueue_event,
    journal_path,
    pending_events,
    replay,
)
from chrysopoeia.events import configured_sink


def event(stake: float = 4.0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "trade_plan_ready",
        "event_id": cycle_turn_id("s1", "m1"),
        "created_at": "2026-10-08T00:00:00+00:00",
        "market_id": "m1",
        "snapshot_id": "s1",
        "instrument_id": "yes-token",
        "outcome": "YES",
        "probability": 0.6,
        "stake": stake,
        "max_entry_price": 0.5,
        "exit_plan": {
            "take_profit_roi": 0.1,
            "stop_loss_roi": -0.2,
            "exit_by": "2026-10-08T12:00:00+00:00",
            "hold_to_resolution": False,
        },
        "reviewer_approved": True,
        "reviewer_citations": ["market_snapshot"],
        "policy_references": ["hard-policy-v1"],
        "evidence_references": ["market_snapshot"],
        "expires_at": "2026-10-09T00:00:00+00:00",
        "market_end": "2026-10-09T00:00:00+00:00",
    }


class OutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())

    def test_enqueue_replay_pending_and_ack_are_durable_and_idempotent(self) -> None:
        value = event()
        enqueue_event(self.directory, value)
        enqueue_event(self.directory, value)

        self.assertEqual(pending_events(self.directory), [value])
        self.assertEqual(replay(self.directory).outbox[value["event_id"]], value)
        self.assertEqual(len(journal_path(self.directory).read_text().splitlines()), 1)

        acknowledge_event(self.directory, str(value["event_id"]))
        acknowledge_event(self.directory, str(value["event_id"]))

        self.assertEqual(pending_events(self.directory), [])
        self.assertEqual(len(journal_path(self.directory).read_text().splitlines()), 2)

    def test_conflicting_or_invalid_enqueue_and_unknown_ack_fail_closed(self) -> None:
        value = event()
        enqueue_event(self.directory, value)

        with self.assertRaises(JournalError):
            enqueue_event(self.directory, {**value, "stake": 5.0})
        with self.assertRaises(ValueError):
            enqueue_event(self.directory, {**value, "record_type": "fill_recorded"})
        with self.assertRaises(JournalError):
            acknowledge_event(self.directory, "missing")

        records = [
            json.loads(line)
            for line in journal_path(self.directory).read_text().splitlines()
        ]
        self.assertEqual(
            [record["record_type"] for record in records], ["outbox_enqueued"]
        )

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(arguments)
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_pending_and_ack_cli_expose_only_canonical_payloads(self) -> None:
        value = event()
        enqueue_event(self.directory, value)

        code, output, error = self.invoke(
            "outbox-pending", "--journal", str(self.directory)
        )
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(
            output, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        )

        code, output, error = self.invoke(
            "outbox-ack", "--journal", str(self.directory), str(value["event_id"])
        )
        self.assertEqual((code, output, error), (0, "", ""))
        self.assertEqual(pending_events(self.directory), [])

    def test_enabled_cycle_without_journal_fails_before_configuration_or_model_work(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {"CHRYSOPOEIA_EVENT_SINK": "pubsub:projects/p/topics/t"},
            clear=False,
        ):
            code, output, error = self.invoke("cycle")

        self.assertEqual((code, output), (2, ""))
        self.assertTrue(error.endswith("cycle failed: event sink requires --journal\n"))

    def test_invalid_sink_fails_before_configuration_or_model_work(self) -> None:
        with (
            patch.dict(os.environ, {"CHRYSOPOEIA_EVENT_SINK": "ftp://private"}),
            patch("chrysopoeia.configuration.load_harness_config") as load,
        ):
            code, output, error = self.invoke("cycle")

        self.assertEqual((code, output), (2, ""))
        self.assertIn("invalid CHRYSOPOEIA_EVENT_SINK", error)
        load.assert_not_called()

    def test_unset_sink_does_not_create_outbox_or_publish(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("chrysopoeia.events.publish") as publish,
        ):
            self.assertIsNone(configured_sink())

        publish.assert_not_called()
        self.assertFalse(journal_path(self.directory).exists())


if __name__ == "__main__":
    unittest.main()
