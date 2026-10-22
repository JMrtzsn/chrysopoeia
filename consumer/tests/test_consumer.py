import base64
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from paper_consumer.app import create_app
from paper_consumer.core import Config, Consumer, Journal, Quote, TransientFailure, load_validator
from paper_consumer.market import Polymarket, _get

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


class BuildScriptTests(unittest.TestCase):
    def test_local_image_targets_cloud_run_architecture(self) -> None:
        script = (Path(__file__).parents[1] / "build.sh").read_text()

        self.assertIn("docker build --platform linux/amd64", script)
        self.assertNotIn("docker push", script)
        self.assertIn("consumer_outcome.v1.schema.json", script)


def event(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "record_type": "trade_plan_ready",
        "created_at": NOW.isoformat(),
        "market_id": "12345",
        "snapshot_id": "plan-snapshot",
        "instrument_id": "yes-token",
        "outcome": "YES",
        "probability": 0.65,
        "stake": 9.0,
        "max_entry_price": 0.5,
        "exit_plan": {
            "take_profit_roi": 0.1,
            "stop_loss_roi": -0.2,
            "exit_by": (NOW + timedelta(hours=12)).isoformat(),
            "hold_to_resolution": False,
        },
        "reviewer_approved": True,
        "reviewer_citations": ["market_snapshot"],
        "policy_references": ["hard-policy-v1"],
        "evidence_references": ["market_snapshot"],
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "market_end": (NOW + timedelta(days=1)).isoformat(),
    }
    value.update(changes)
    if "event_id" not in changes:
        identity = json.dumps(
            [value["snapshot_id"], value["market_id"]], separators=(",", ":")
        )
        value["event_id"] = "turn-" + sha256(identity.encode()).hexdigest()[:24]
    return value


def envelope(value: dict[str, object]) -> dict[str, object]:
    data = base64.b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()
    # Real Pub/Sub push body, including snake_case duplicates and dead-letter attempt count.
    return {
        "message": {
            "attributes": {"event_id": "id"},
            "data": data,
            "messageId": "1",
            "message_id": "1",
            "publishTime": "2026-10-07T12:00:00Z",
            "publish_time": "2026-10-07T12:00:00Z",
        },
        "subscription": "projects/p/subscriptions/s",
        "deliveryAttempt": 1,
    }


class FakeMarket:
    def __init__(self, quotes: list[Quote | Exception] | None = None) -> None:
        self.quotes = quotes or [quote()]
        self.calls = 0

    def load(self, market_id: str, token_id: str, now: datetime) -> Quote:
        self.calls += 1
        value = self.quotes.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.fail = False

    def publish(self, event: dict[str, object]) -> None:
        if self.fail:
            raise RuntimeError("publish failed")
        self.events.append(deepcopy(event))


def quote(**changes: object) -> Quote:
    values = {
        "snapshot_id": "fresh-snapshot",
        "market_id": "12345",
        "token_id": "yes-token",
        "market_end": (NOW + timedelta(days=1)).isoformat(),
        "captured_at": NOW.isoformat(),
        "asks": ((0.4, 100.0),),
        "bids": ((0.39, 100.0),),
        "resolution": None,
        "outcome": "YES",
    }
    values.update(changes)
    return Quote(**values)


class LocalSendScriptTests(unittest.TestCase):
    def test_script_envelope_is_accepted_by_push_and_fills(self) -> None:
        import importlib.util

        path = Path(__file__).parents[1] / "scripts" / "send_event.py"
        spec = importlib.util.spec_from_file_location("send_event", path)
        assert spec is not None and spec.loader is not None
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp) / "ledger.jsonl"
            client = TestClient(
                create_app(Config(journal=journal, fee_rate=0.01), FakeMarket(), lambda: NOW)
            )
            value = event()

            self.assertEqual(value["event_id"], script.event_id("plan-snapshot", "12345"))
            self.assertEqual(client.post("/push", json=script.envelope(value)).status_code, 204)
            self.assertEqual(json.loads(journal.read_text())["status"], "filled")


class ConsumerTests(unittest.TestCase):
    def test_outcome_events_are_published_after_the_ledger_write(self) -> None:
        publisher = FakePublisher()
        client = TestClient(
            create_app(self.config, FakeMarket(), lambda: NOW, publisher=publisher)
        )
        plan = event()

        self.assertEqual(client.post("/push", json=envelope(plan)).status_code, 204)

        self.assertEqual(len(publisher.events), 1)
        outcome = publisher.events[0]
        self.assertEqual(outcome["record_type"], "consumer_outcome")
        self.assertEqual(outcome["status"], "filled")
        self.assertEqual(outcome["trade_plan_event_id"], plan["event_id"])
        self.assertEqual(outcome["market_id"], plan["market_id"])

    def test_rejection_outcomes_are_published_without_raw_plan_content(self) -> None:
        publisher = FakePublisher()
        client = TestClient(
            create_app(self.config, FakeMarket(), lambda: NOW, publisher=publisher)
        )

        self.assertEqual(
            client.post("/push", json=envelope(event(stake="invalid"))).status_code,
            204,
        )

        self.assertEqual(len(publisher.events), 1)
        outcome = publisher.events[0]
        self.assertEqual(outcome["status"], "rejected")
        self.assertNotIn("stake", outcome)
        self.assertEqual(outcome["market_id"], "12345")

    def test_failed_outcome_publish_retries_without_repeating_the_fill(self) -> None:
        publisher = FakePublisher()
        publisher.fail = True
        market = FakeMarket()
        client = TestClient(
            create_app(self.config, market, lambda: NOW, publisher=publisher)
        )
        request = envelope(event())

        self.assertEqual(client.post("/push", json=request).status_code, 503)
        publisher.fail = False
        restarted = TestClient(
            create_app(self.config, market, lambda: NOW, publisher=publisher)
        )
        self.assertEqual(restarted.post("/push", json=request).status_code, 204)

        self.assertEqual(market.calls, 1)
        self.assertEqual(len(publisher.events), 1)
        self.assertEqual(publisher.events[0]["status"], "filled")

    def test_outcome_delivery_is_bounded_per_flush(self) -> None:
        publisher = FakePublisher()
        consumer = Consumer(self.config, FakeMarket(), load_validator(), publisher)
        for index in range(6):
            consumer.journal.append(
                {
                    "event_id": f"turn-{index:024x}",
                    "recorded_at": NOW.isoformat(),
                    "status": "rejected",
                    "reason": "bounded test",
                }
            )

        consumer.flush_outbox(NOW)
        self.assertEqual(len(publisher.events), 5)
        consumer.flush_outbox(NOW)

        self.assertEqual(len(publisher.events), 6)

    def test_sweep_publishes_a_distinct_settlement_outcome(self) -> None:
        publisher = FakePublisher()
        market = FakeMarket([
            quote(),
            quote(resolution="YES", asks=(), bids=()),
        ])
        client = TestClient(
            create_app(self.config, market, lambda: NOW, publisher=publisher)
        )
        plan = event()

        self.assertEqual(client.post("/push", json=envelope(plan)).status_code, 204)
        self.assertEqual(client.post("/sweep").status_code, 204)

        self.assertEqual([item["status"] for item in publisher.events], ["filled", "settled"])
        self.assertNotEqual(publisher.events[0]["event_id"], publisher.events[1]["event_id"])

    def test_sweep_publishes_a_closed_outcome_with_realized_pnl(self) -> None:
        publisher = FakePublisher()
        market = FakeMarket([
            quote(asks=((0.3, 100.0),), bids=((0.29, 100.0),)),
            quote(asks=((0.4, 100.0),), bids=((0.39, 100.0),)),
        ])
        client = TestClient(
            create_app(self.config, market, lambda: NOW, publisher=publisher)
        )

        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)
        self.assertEqual(client.post("/sweep").status_code, 204)

        self.assertEqual(publisher.events[-1]["status"], "closed")
        pnl = publisher.events[-1]["pnl"]
        assert isinstance(pnl, (int, float))
        self.assertGreater(pnl, 0)

    def test_v2_no_plan_fills_no_token_and_settles_when_no_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config(Path(directory) / "journal.jsonl")
            market = FakeMarket([
                quote(token_id="no-token", outcome="NO"),
                quote(token_id="no-token", outcome="NO", resolution="YES", asks=(), bids=()),
            ])
            app = create_app(config, market, lambda: NOW)
            client = TestClient(app)
            plan = event(schema_version=2, outcome="NO", instrument_id="no-token")
            self.assertEqual(client.post("/push", json=envelope(plan)).status_code, 204)
            terminal, positions = Journal(config.journal).replay()
            self.assertEqual(terminal[str(plan["event_id"])]["status"], "filled")
            self.assertEqual(next(iter(positions.values()))["token_id"], "no-token")
            self.assertEqual(client.post("/sweep").status_code, 204)
            terminal, positions = Journal(config.journal).replay()
            self.assertFalse(positions)
            pnl = terminal[str(plan["event_id"])]["pnl"]
            self.assertTrue(isinstance(pnl, (int, float)) and pnl > 0)

    def test_no_plan_cannot_use_yes_quote_even_if_token_id_is_forged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config(Path(directory) / "journal.jsonl")
            market = FakeMarket([quote(token_id="no-token", outcome="YES")])
            client = TestClient(create_app(config, market, lambda: NOW))
            plan = event(schema_version=2, outcome="NO", instrument_id="no-token")
            self.assertEqual(client.post("/push", json=envelope(plan)).status_code, 204)
            terminal, positions = Journal(config.journal).replay()
            self.assertFalse(positions)
            self.assertEqual(terminal[str(plan["event_id"])]["status"], "rejected")
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "consumer.jsonl"
        self.config = Config(journal=self.path, bankroll=1_000, fee_rate=0.01)

    def client(self, market: FakeMarket) -> TestClient:
        return TestClient(create_app(self.config, market, lambda: NOW))

    def test_valid_push_is_durable_and_redelivery_does_not_repeat_fill(self) -> None:
        market = FakeMarket()
        client = self.client(market)

        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)
        before = self.path.read_bytes()
        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)

        self.assertEqual(market.calls, 1)
        self.assertEqual(self.path.read_bytes(), before)
        record = json.loads(before)
        self.assertEqual(record["status"], "filled")
        self.assertEqual(record["plan_snapshot_id"], "plan-snapshot")
        self.assertEqual(record["quote_snapshot_id"], "fresh-snapshot")

    def test_mismatched_attribute_does_not_override_valid_plan_payload(self) -> None:
        market = FakeMarket()
        client = self.client(market)

        value = envelope(event())
        message = value["message"]
        assert isinstance(message, dict)
        attributes = message["attributes"]
        assert isinstance(attributes, dict)
        attributes["record_type"] = "turn_outcome"

        self.assertEqual(client.post("/push", json=value).status_code, 204)

        self.assertEqual(market.calls, 1)
        self.assertEqual(json.loads(self.path.read_text())["status"], "filled")

    def test_non_plan_payload_is_ignored(self) -> None:
        market = FakeMarket()

        self.assertEqual(
            self.client(market)
            .post("/push", json=envelope(event(record_type="turn_outcome")))
            .status_code,
            204,
        )

        self.assertFalse(self.path.exists())
        self.assertEqual(market.calls, 0)

    def test_malformed_trade_plan_is_still_rejected(self) -> None:
        value = envelope(event(stake="invalid"))
        message = value["message"]
        assert isinstance(message, dict)
        attributes = message["attributes"]
        assert isinstance(attributes, dict)
        attributes["record_type"] = "trade_plan_ready"

        self.assertEqual(self.client(FakeMarket()).post("/push", json=value).status_code, 204)
        self.assertTrue(self.path.exists())
        self.assertEqual(json.loads(self.path.read_text())["status"], "rejected")

    def test_restart_replays_deduplication(self) -> None:
        first = FakeMarket()
        self.assertEqual(self.client(first).post("/push", json=envelope(event())).status_code, 204)
        second = FakeMarket()

        self.assertEqual(self.client(second).post("/push", json=envelope(event())).status_code, 204)

        self.assertEqual(second.calls, 0)

    def test_invalid_identifier_redelivery_does_not_repeat_rejection(self) -> None:
        client = self.client(FakeMarket())
        value = envelope(event(event_id="bad id"))
        self.assertEqual(client.post("/push", json=value).status_code, 204)
        before = self.path.read_bytes()

        self.assertEqual(client.post("/push", json=value).status_code, 204)

        self.assertEqual(self.path.read_bytes(), before)

    def test_strict_envelope_and_json_are_rejected(self) -> None:
        client = self.client(FakeMarket())
        cases = [
            {"message": {"data": "***"}},
            {**envelope(event()), "unknown": True},
            {"message": {"data": base64.b64encode(b'{"x":NaN}').decode()}},
            {"message": {"data": base64.b64encode(b'{"x":1,"x":2}').decode()}},
            {"message": {"data": base64.b64encode(b"x" * 262_145).decode()}},
        ]
        for value in cases:
            with self.subTest(value=str(value)[:40]):
                self.assertEqual(client.post("/push", json=value).status_code, 400)

    def test_invalid_or_expired_event_is_recorded_and_acked_without_market_call(self) -> None:
        for changes in (
            {"schema_version": 3},
            {"unknown": True},
            {"reviewer_approved": False},
            {"outcome": "NO"},
            {"policy_references": ["other"]},
            {"expires_at": NOW.isoformat()},
            {"event_id": "bad id"},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                config = Config(Path(directory) / "journal.jsonl")
                market = FakeMarket()
                response = TestClient(create_app(config, market, lambda: NOW)).post(
                    "/push", json=envelope(event(**changes))
                )
                self.assertEqual(response.status_code, 204)
                self.assertEqual(market.calls, 0)
                self.assertEqual(json.loads(config.journal.read_text())["status"], "rejected")

    def test_event_id_must_match_snapshot_and_market(self) -> None:
        market = FakeMarket()

        response = self.client(market).post(
            "/push",
            json=envelope(event(event_id="turn-0123456789abcdef01234567")),
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(market.calls, 0)
        self.assertEqual(json.loads(self.path.read_text())["status"], "rejected")

    def test_quote_failures_retry_but_risk_and_quote_mismatch_are_acked(self) -> None:
        transient = FakeMarket([RuntimeError("network secret")])
        response = self.client(transient).post("/push", json=envelope(event()))
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.path.exists())

        cases = (
            quote(captured_at=(NOW - timedelta(minutes=6)).isoformat()),
            quote(market_id="999"),
            quote(token_id="other"),
            quote(market_end=(NOW + timedelta(days=2)).isoformat()),
            quote(asks=((0.51, 100),)),
            quote(asks=((0.4, 1),)),
            quote(asks=((0.61, 100),)),
        )
        for fresh in cases:
            with self.subTest(fresh=fresh), tempfile.TemporaryDirectory() as directory:
                config = Config(Path(directory) / "journal.jsonl")
                response = TestClient(create_app(config, FakeMarket([fresh]), lambda: NOW)).post(
                    "/push",
                    json=envelope(
                        event(max_entry_price=0.7) if fresh.asks[0][0] == 0.61 else event()
                    ),
                )
                self.assertEqual(response.status_code, 204)
                self.assertEqual(json.loads(config.journal.read_text())["status"], "rejected")

    def test_entry_stake_and_exposure_limits_are_independent(self) -> None:
        for changes, config_changes in (
            ({"stake": 11}, {}),
            ({"stake": 9}, {"maximum_market_exposure": 0.005}),
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                values = deepcopy(self.config.__dict__)
                values.update(config_changes)
                values["journal"] = Path(directory) / "journal.jsonl"
                config = Config(**values)
                response = TestClient(create_app(config, FakeMarket(), lambda: NOW)).post(
                    "/push", json=envelope(event(**changes))
                )
                self.assertEqual(response.status_code, 204)
                self.assertEqual(json.loads(config.journal.read_text())["status"], "rejected")

    def test_second_open_position_in_same_market_is_rejected(self) -> None:
        config = Config(self.path, maximum_market_exposure=0.1)
        market = FakeMarket([quote(), quote()])
        client = TestClient(create_app(config, market, lambda: NOW))
        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)

        response = client.post(
            "/push", json=envelope(event(snapshot_id="another-snapshot"))
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(json.loads(self.path.read_text().splitlines()[-1])["status"], "rejected")

    def test_realized_maximum_loss_blocks_entries_but_not_sweeps(self) -> None:
        config = Config(self.path, maximum_loss=1)
        market = FakeMarket([quote(), quote(bids=((0.3, 100),))])
        client = TestClient(create_app(config, market, lambda: NOW))
        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)
        self.assertEqual(client.post("/sweep").status_code, 204)
        self.assertEqual(json.loads(self.path.read_text().splitlines()[-1])["status"], "closed")

        response = client.post(
            "/push",
            json=envelope(event(snapshot_id="next", market_id="12346")),
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(market.calls, 2)
        self.assertEqual(json.loads(self.path.read_text().splitlines()[-1])["status"], "rejected")

    def test_default_fee_is_in_total_cost_and_exit_roi(self) -> None:
        config = Config(self.path)
        market = FakeMarket([quote(), quote(asks=((0.5, 100),), bids=((0.45, 100),))])
        client = TestClient(create_app(config, market, lambda: NOW))

        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)
        fill = json.loads(self.path.read_text())
        self.assertEqual(config.fee_rate, 0.02)
        self.assertAlmostEqual(fill["fee"], 0.18)
        self.assertAlmostEqual(fill["total_cost"], 9.18)
        self.assertEqual(client.post("/sweep").status_code, 204)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)

    def _opened(self, exit_plan: dict[str, object] | None = None) -> tuple[TestClient, FakeMarket]:
        value = event(exit_plan=exit_plan) if exit_plan else event()
        market = FakeMarket([quote(), quote(bids=((0.5, 100),))])
        client = self.client(market)
        self.assertEqual(client.post("/push", json=envelope(value)).status_code, 204)
        return client, market

    def test_sweep_closes_on_take_profit_stop_loss_and_exit_by(self) -> None:
        default_plan = event()["exit_plan"]
        assert isinstance(default_plan, dict)
        cases = (
            (quote(asks=((0.6, 100),), bids=((0.5, 100),)), default_plan),
            (quote(bids=((0.3, 100),)), default_plan),
            (
                quote(asks=((0.5, 100),), bids=((0.4, 100),)),
                {**default_plan, "exit_by": (NOW - timedelta(seconds=1)).isoformat()},
            ),
        )
        for exit_quote, plan in cases:
            with self.subTest(exit_quote=exit_quote), tempfile.TemporaryDirectory() as directory:
                config = Config(Path(directory) / "journal.jsonl", fee_rate=0.01)
                market = FakeMarket([quote(), exit_quote])
                client = TestClient(create_app(config, market, lambda: NOW))
                # Time-trigger plan must be valid when entered, then clock advances for sweep.
                if plan["exit_by"] < NOW.isoformat():
                    plan = {**plan, "exit_by": (NOW + timedelta(seconds=1)).isoformat()}
                    clock = iter((NOW, NOW + timedelta(seconds=2)))
                    client = TestClient(create_app(config, market, lambda clock=clock: next(clock)))
                self.assertEqual(
                    client.post("/push", json=envelope(event(exit_plan=plan))).status_code, 204
                )
                self.assertEqual(client.post("/sweep").status_code, 204)
                records = [json.loads(line) for line in config.journal.read_text().splitlines()]
                self.assertEqual(records[-1]["status"], "closed")

    def test_insufficient_exit_depth_leaves_position_open(self) -> None:
        market = FakeMarket([quote(), quote(bids=((0.39, 1),))])
        client = self.client(market)
        client.post("/push", json=envelope(event()))

        self.assertEqual(client.post("/sweep").status_code, 204)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)

    def test_transient_exit_quote_failure_retries(self) -> None:
        market = FakeMarket([quote(), RuntimeError("temporary")])
        client = self.client(market)
        client.post("/push", json=envelope(event()))

        self.assertEqual(client.post("/sweep").status_code, 503)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)

    def test_yes_and_no_resolution_settle_idempotently(self) -> None:
        for resolution in ("YES", "NO"):
            with self.subTest(resolution=resolution), tempfile.TemporaryDirectory() as directory:
                config = Config(Path(directory) / "journal.jsonl")
                market = FakeMarket([quote(), quote(resolution=resolution, asks=(), bids=())])
                client = TestClient(create_app(config, market, lambda: NOW))
                client.post("/push", json=envelope(event()))
                self.assertEqual(client.post("/sweep").status_code, 204)
                before = config.journal.read_bytes()
                self.assertEqual(client.post("/sweep").status_code, 204)
                self.assertEqual(config.journal.read_bytes(), before)
                self.assertEqual(json.loads(before.splitlines()[-1])["status"], "settled")

    def test_corrupt_journal_fails_closed(self) -> None:
        self.path.write_text("not json\n")
        response = self.client(FakeMarket()).post("/push", json=envelope(event()))
        self.assertEqual(response.status_code, 503)

    def test_replay_rejects_duplicate_keys_and_non_finite_numbers(self) -> None:
        for record in (
            '{"schema_version":1,"record_type":"consumer_ledger","event_id":"x",'
            '"status":"rejected","recorded_at":"2026-10-07T12:00:00Z",'
            '"reason":"one","reason":"two"}\n',
            '{"schema_version":1,"record_type":"consumer_ledger","event_id":"x",'
            '"status":"rejected","recorded_at":"2026-10-07T12:00:00Z",'
            '"reason":NaN}\n',
        ):
            with self.subTest(record=record), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "journal.jsonl"
                path.write_text(record)
                response = TestClient(
                    create_app(Config(path), FakeMarket(), lambda: NOW)
                ).post("/push", json=envelope(event()))
                self.assertEqual(response.status_code, 503)

    def test_replay_rejects_unknown_records_and_invalid_transitions(self) -> None:
        malformed = (
            {"schema_version": 2, "record_type": "consumer_ledger", "event_id": "x"},
            {
                "schema_version": 1,
                "record_type": "consumer_ledger",
                "event_id": "x",
                "status": "unknown",
                "recorded_at": NOW.isoformat(),
            },
            {
                "schema_version": 1,
                "record_type": "consumer_ledger",
                "event_id": "x",
                "status": "closed",
                "recorded_at": NOW.isoformat(),
                "market_id": "12345",
                "quote_snapshot_id": "q",
                "proceeds": 1,
                "pnl": -1,
                "price": 0.4,
                "fee": 0.1,
            },
        )
        for record in malformed:
            with self.subTest(record=record), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "journal.jsonl"
                path.write_text(json.dumps(record) + "\n")
                response = TestClient(
                    create_app(Config(path), FakeMarket(), lambda: NOW)
                ).post("/push", json=envelope(event()))
                self.assertEqual(response.status_code, 503)

    def test_replay_rejects_terminal_record_that_does_not_match_fill(self) -> None:
        client = self.client(FakeMarket())
        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)
        self.path.write_text(
            self.path.read_text()
            + json.dumps(
                {
                    "schema_version": 1,
                    "record_type": "consumer_ledger",
                    "event_id": event()["event_id"],
                    "status": "closed",
                    "recorded_at": NOW.isoformat(),
                    "market_id": "999",
                    "quote_snapshot_id": "q",
                    "proceeds": 10,
                    "pnl": 10,
                    "price": 0.4,
                    "fee": 0.1,
                }
            )
            + "\n"
        )

        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 503)

    def test_replay_rejects_malformed_filled_values(self) -> None:
        client = self.client(FakeMarket())
        self.assertEqual(client.post("/push", json=envelope(event())).status_code, 204)
        record = json.loads(self.path.read_text())
        record["exit_plan"]["hold_to_resolution"] = "false"
        self.path.write_text(json.dumps(record) + "\n")

        with self.assertRaises(TransientFailure):
            Journal(self.path).replay()


class PublicMarketTests(unittest.TestCase):
    def test_down_token_resolves_as_winning_position_when_market_resolves_down(self) -> None:
        metadata = {
            "id": "12345", "clobTokenIds": ["up-token", "down-token"],
            "outcomes": ["Up", "Down"], "outcomePrices": ["0", "1"],
            "endDate": (NOW + timedelta(days=1)).isoformat(),
            "updatedAt": NOW.isoformat(), "closed": True,
        }
        with patch("paper_consumer.market._get", return_value=metadata):
            result = Polymarket().load("12345", "down-token", NOW)
        self.assertEqual(result.outcome, "NO")
        self.assertEqual(result.resolution, "YES")

    def test_public_json_rejects_duplicate_keys_and_non_finite_numbers(self) -> None:
        class Response:
            def __init__(self, body: bytes) -> None:
                self.body = body

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, _size: int) -> bytes:
                return self.body

        for body in (b'{"id":"1","id":"2"}', b'{"price":NaN}', b'{"price":Infinity}'):
            with self.subTest(body=body), patch(
                "paper_consumer.market.urlopen", return_value=Response(body)
            ):
                with self.assertRaisesRegex(ValueError, "malformed"):
                    _get("https://example.invalid")

    def test_public_requests_identify_the_client(self) -> None:
        with patch("paper_consumer.market.urlopen", side_effect=OSError("stop")) as opened:
            with self.assertRaises(RuntimeError):
                _get("https://example.invalid")

        self.assertEqual(opened.call_args.args[0].get_header("User-agent"), "chrysopoeia-consumer/0.1")

    def test_metadata_may_be_old_but_book_must_be_fresh_and_not_future_dated(self) -> None:
        metadata = {
            "id": "12345",
            "clobTokenIds": '["yes-token","no-token"]',
            "outcomes": '["Yes","No"]',
            "endDate": (NOW + timedelta(days=1)).isoformat(),
            "updatedAt": (NOW - timedelta(days=30)).isoformat(),
            "closed": False,
            "active": True,
            "acceptingOrders": True,
        }
        fresh_book = {
            "asset_id": "yes-token",
            "timestamp": str(int(NOW.timestamp() * 1_000)),
            "asks": [{"price": "0.4", "size": "10"}],
            "bids": [],
        }
        with patch("paper_consumer.market._get", side_effect=[metadata, fresh_book]):
            self.assertEqual(Polymarket().load("12345", "yes-token", NOW).market_id, "12345")

        for captured in (NOW - timedelta(minutes=6), NOW + timedelta(seconds=6)):
            stale_book = {**fresh_book, "timestamp": str(int(captured.timestamp() * 1_000))}
            with self.subTest(captured=captured), patch(
                "paper_consumer.market._get", side_effect=[metadata, stale_book]
            ):
                with self.assertRaisesRegex(ValueError, "book.*stale|book.*future"):
                    Polymarket().load("12345", "yes-token", NOW)

        deep_book = {
            **fresh_book,
            "asks": [{"price": f"0.{90 - i:02d}", "size": "1"} for i in range(80)],
            "bids": [{"price": f"0.0{i % 9 + 1}", "size": "1"} for i in range(80)],
        }
        with patch("paper_consumer.market._get", side_effect=[metadata, deep_book]):
            loaded = Polymarket().load("12345", "yes-token", NOW)
        self.assertEqual((len(loaded.asks), len(loaded.bids)), (50, 50))
        self.assertEqual((loaded.asks[0][0], loaded.bids[0][0]), (0.11, 0.09))

    def test_metadata_more_than_five_seconds_in_future_is_rejected(self) -> None:
        metadata = {
            "id": "12345",
            "clobTokenIds": '["yes-token","no-token"]',
            "outcomes": '["Yes","No"]',
            "endDate": (NOW + timedelta(days=1)).isoformat(),
            "updatedAt": (NOW + timedelta(seconds=6)).isoformat(),
            "closed": False,
            "active": True,
            "acceptingOrders": True,
        }
        with patch("paper_consumer.market._get", return_value=metadata):
            with self.assertRaisesRegex(ValueError, "future"):
                Polymarket().load("12345", "yes-token", NOW)


if __name__ == "__main__":
    unittest.main()
