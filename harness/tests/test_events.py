import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call
from urllib.error import URLError

from chrysopoeia.accounting import cycle_turn_id, enqueue_event, pending_events
from chrysopoeia.events import drain, publish, validate_sink


def event(snapshot: str = "s1", market: str = "m1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "trade_plan_ready",
        "event_id": cycle_turn_id(snapshot, market),
        "created_at": "2026-10-08T00:00:00+00:00",
        "market_id": market,
        "snapshot_id": snapshot,
        "instrument_id": "yes-token",
        "outcome": "YES",
        "probability": 0.6,
        "stake": 4.0,
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


class Response:
    status = 204

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class EventPublishingTests(unittest.TestCase):
    def test_http_publish_uses_consumer_compatible_pubsub_envelope(self) -> None:
        opened = Mock(return_value=Response())
        value = event()

        publish("http://127.0.0.1:8080/push", value, urlopen=opened)

        request = opened.call_args.args[0]
        self.assertEqual(opened.call_args.kwargs, {"timeout": 30})
        self.assertEqual(request.method, "POST")
        envelope = json.loads(request.data)
        self.assertEqual(set(envelope), {"message", "subscription", "deliveryAttempt"})
        self.assertEqual(
            set(envelope["message"]),
            {
                "data",
                "messageId",
                "message_id",
                "publishTime",
                "publish_time",
                "attributes",
            },
        )
        self.assertEqual(
            envelope["message"]["attributes"],
            {
                "event_id": value["event_id"],
                "record_type": "trade_plan_ready",
                "schema_version": "1",
            },
        )
        self.assertEqual(
            json.loads(base64.b64decode(envelope["message"]["data"])), value
        )

    def test_http_publish_rejects_failure_and_remote_plain_http(self) -> None:
        for opened in (
            Mock(side_effect=URLError("private detail")),
            Mock(return_value=type("Failure", (Response,), {"status": 503})()),
        ):
            with self.subTest(opened=opened), self.assertRaises(RuntimeError):
                publish("http://localhost:8080/push", event(), urlopen=opened)
        with self.assertRaises(ValueError):
            validate_sink("http://example.com/push")
        with self.assertRaises(ValueError):
            validate_sink("http://127.0.0.1:8080/other")

    def test_pubsub_publish_waits_for_confirmation(self) -> None:
        client = Mock()
        value = event()

        publish("pubsub:projects/p/topics/t", value, publisher=client)

        client.publish.assert_called_once_with(
            "projects/p/topics/t",
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
            event_id=value["event_id"],
            record_type="trade_plan_ready",
            schema_version="1",
        )
        client.publish.return_value.result.assert_called_once_with(timeout=30)

    def test_drain_publishes_oldest_first_and_stops_without_ack_on_failure(
        self,
    ) -> None:
        directory = Path(tempfile.mkdtemp())
        values = [event("s1", "m1"), event("s2", "m2"), event("s3", "m3")]
        for value in values:
            enqueue_event(directory, value)
        sender = Mock(side_effect=[None, TimeoutError("private")])

        drain(directory, "pubsub:projects/p/topics/t", sender=sender)

        self.assertEqual(
            sender.call_args_list,
            [
                call("pubsub:projects/p/topics/t", values[0]),
                call("pubsub:projects/p/topics/t", values[1]),
            ],
        )
        self.assertEqual(pending_events(directory), values[1:])


if __name__ == "__main__":
    unittest.main()
