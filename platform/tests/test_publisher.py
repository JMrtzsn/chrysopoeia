import json
import unittest
from unittest.mock import Mock, call

from publisher import drain, main

EVENT = {
    "schema_version": 1,
    "record_type": "trade_plan_ready",
    "event_id": "turn-1",
}


class PublisherTests(unittest.TestCase):
    def test_disabled_mode_forwards_cli_unchanged(self) -> None:
        run = Mock(return_value=Mock(returncode=7))

        self.assertEqual(main(["book", "--journal", "/mnt/journal"], environ={}, run=run), 7)

        run.assert_called_once_with(["chrysopoeia", "book", "--journal", "/mnt/journal"])

    def test_enabled_mode_forwards_nonproducer_commands_unchanged(self) -> None:
        run = Mock(return_value=Mock(returncode=0))

        self.assertEqual(
            main(
                ["book", "--journal", "/mnt/journal"],
                environ={"CHRYSOPOEIA_PUBSUB_TOPIC": "topic"},
                run=run,
            ),
            0,
        )

        run.assert_called_once_with(["chrysopoeia", "book", "--journal", "/mnt/journal"])

    def test_enabled_mode_drains_before_and_after_producer_then_acks(self) -> None:
        line = json.dumps(EVENT, sort_keys=True, separators=(",", ":")) + "\n"
        run = Mock(
            side_effect=[
                Mock(returncode=0, stdout=line),
                Mock(returncode=0),
                Mock(returncode=0),
                Mock(returncode=0, stdout=line),
                Mock(returncode=0),
            ]
        )
        future = Mock()
        publisher = Mock()
        publisher.publish.return_value = future

        code = main(
            ["cycle", "--journal", "/mnt/journal", "--market", "1"],
            environ={"CHRYSOPOEIA_PUBSUB_TOPIC": "projects/p/topics/t"},
            run=run,
            publisher=publisher,
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            run.call_args_list,
            [
                call(["chrysopoeia", "outbox-pending", "--journal", "/mnt/journal"], capture_output=True, text=True),
                call(["chrysopoeia", "outbox-ack", "--journal", "/mnt/journal", "turn-1"]),
                call(["chrysopoeia", "cycle", "--journal", "/mnt/journal", "--market", "1"]),
                call(["chrysopoeia", "outbox-pending", "--journal", "/mnt/journal"], capture_output=True, text=True),
                call(["chrysopoeia", "outbox-ack", "--journal", "/mnt/journal", "turn-1"]),
            ],
        )
        self.assertEqual(
            publisher.publish.call_args_list,
            [call("projects/p/topics/t", line.rstrip().encode(), event_id="turn-1")] * 2,
        )
        self.assertEqual(future.result.call_args_list, [call(timeout=30)] * 2)

    def test_enabled_mode_accepts_equals_journal_argument(self) -> None:
        run = Mock(
            side_effect=[
                Mock(returncode=0, stdout=""),
                Mock(returncode=0),
                Mock(returncode=0, stdout=""),
            ]
        )

        self.assertEqual(
            main(
                ["cycle", "--journal=/mnt/journal"],
                environ={"CHRYSOPOEIA_PUBSUB_TOPIC": "topic"},
                run=run,
                publisher=Mock(),
            ),
            0,
        )
        self.assertEqual(
            run.call_args_list,
            [
                call(["chrysopoeia", "outbox-pending", "--journal", "/mnt/journal"], capture_output=True, text=True),
                call(["chrysopoeia", "cycle", "--journal=/mnt/journal"]),
                call(["chrysopoeia", "outbox-pending", "--journal", "/mnt/journal"], capture_output=True, text=True),
            ],
        )

    def test_publish_or_ack_failure_stops_without_hiding_pending_state(self) -> None:
        line = json.dumps(EVENT) + "\n"
        for failure in (RuntimeError("publish"), None):
            with self.subTest(failure=failure):
                run = Mock(side_effect=[Mock(returncode=0, stdout=line), Mock(returncode=2)])
                publisher = Mock()
                publisher.publish.return_value.result.side_effect = failure
                self.assertEqual(
                    drain("topic", "/journal", publisher, run=run),
                    1 if failure else 2,
                )
                if failure:
                    self.assertEqual(run.call_count, 1)

    def test_publish_confirmation_failure_does_not_ack(self) -> None:
        line = json.dumps(EVENT) + "\n"
        run = Mock(return_value=Mock(returncode=0, stdout=line))
        publisher = Mock()
        publisher.publish.return_value.result.side_effect = TimeoutError

        self.assertEqual(drain("topic", "/journal", publisher, run=run), 1)

        publisher.publish.return_value.result.assert_called_once_with(timeout=30)
        run.assert_called_once_with(
            ["chrysopoeia", "outbox-pending", "--journal", "/journal"],
            capture_output=True,
            text=True,
        )

    def test_enabled_mode_requires_journal_and_does_not_run_producer(self) -> None:
        run = Mock()
        self.assertEqual(
            main(["cycle"], environ={"CHRYSOPOEIA_PUBSUB_TOPIC": "topic"}, run=run, publisher=Mock()),
            2,
        )
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
