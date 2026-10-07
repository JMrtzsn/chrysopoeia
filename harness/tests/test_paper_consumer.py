import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from chrysopoeia import cli
from chrysopoeia.accounting import (
    JournalError,
    Position,
    admit_turn,
    finish_turn,
    journal_path,
    open_session,
    record_fill,
    replay,
    settle,
)
from chrysopoeia.operations import consume_paper_event
from chrysopoeia.trading import (
    BookLevel,
    ExitPlan,
    MarketSnapshot,
    OperatingConfig,
    Proposal,
    Review,
    run_decision_cycle,
)


class PaperConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.journal = Path(self.temporary.name)
        open_session(self.journal, 1_000, 100)
        original = self.snapshot("plan-snapshot", price=0.4)
        proposal = Proposal(
            original.snapshot_id,
            original.market_id,
            0.6,
            9,
            0.5,
            ExitPlan(0.1, -0.2, "2026-10-08T12:00:00+00:00"),
            ("market_snapshot",),
        )
        review = Review(
            original.snapshot_id,
            original.market_id,
            True,
            "supported",
            ("market_snapshot",),
        )
        self.event = run_decision_cycle(original, proposal, review).event
        self.assertIsNotNone(self.event)
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        self.operating = OperatingConfig(bankroll=1_000)

    @staticmethod
    def snapshot(snapshot_id: str, *, price: float = 0.42, **changes: object) -> MarketSnapshot:
        values = {
            "market_id": "12345",
            "bankroll": 1_000,
            "market_exposure": 0,
            "total_exposure": 0,
            "question": "Will it rain?",
            "resolution_rules": "Resolves Yes if rain is measured.",
            "end_time": "2026-10-09T00:00:00+00:00",
            "captured_at": "2026-10-07T12:00:00+00:00",
            "source_url": "https://polymarket.com/event/will-it-rain",
            "yes_token_id": "yes-token",
            "asks": (BookLevel(price, 100),),
            "book_captured_at": "2026-10-07T12:00:00+00:00",
        }
        values.update(changes)
        return MarketSnapshot(snapshot_id, price=price, **values)

    def consume(self, fresh: MarketSnapshot | None = None, **changes: object):
        event = replace(self.event, **changes)
        load = Mock(return_value=fresh or self.snapshot("quote-snapshot"))
        result = consume_paper_event(
            self.journal,
            event,
            self.operating,
            now=self.now,
            load=load,
            fetch=Mock(),
            paper_fee_rate=0,
            paper_fee_source="paper-assumption:no-fee-v1",
        )
        return result, load

    def test_accepted_event_fills_from_fresh_quote_and_preserves_both_snapshot_identities(self) -> None:
        result, load = self.consume()

        self.assertEqual(result["status"], "filled")
        self.assertEqual(result["fill"]["quote_snapshot_id"], "quote-snapshot")
        load.assert_called_once()
        position = replay(self.journal).positions["12345"]
        self.assertEqual(position.snapshot_id, "plan-snapshot")
        self.assertEqual(position.quote_snapshot_id, "quote-snapshot")
        self.assertEqual(position.trade_plan.snapshot_id, "plan-snapshot")
        self.assertEqual(position.price, 0.42)
        fill_record = json.loads(journal_path(self.journal).read_text().splitlines()[2])
        self.assertEqual(fill_record["snapshot_id"], "plan-snapshot")
        self.assertEqual(fill_record["quote_snapshot_id"], "quote-snapshot")

    def test_completed_duplicate_returns_prior_outcome_without_fetch_or_write(self) -> None:
        first, _load = self.consume()
        before = journal_path(self.journal).read_bytes()
        load = Mock()

        duplicate = consume_paper_event(
            self.journal,
            self.event,
            self.operating,
            now=self.now,
            load=load,
            fetch=Mock(),
            paper_fee_rate=0,
            paper_fee_source="paper-assumption:no-fee-v1",
        )

        self.assertEqual(duplicate, {"status": first["status"]})
        load.assert_not_called()
        self.assertEqual(journal_path(self.journal).read_bytes(), before)

    def test_changed_market_instrument_and_invalid_plan_are_rejected(self) -> None:
        cases = (
            (self.snapshot("fresh", market_id="999"), {}, "market identity"),
            (self.snapshot("fresh", yes_token_id="other"), {}, "instrument identity"),
            (None, {"reviewer_approved": False}, "terms"),
            (None, {"expires_at": "2026-10-07T11:00:00+00:00"}, "expired"),
            (None, {"policy_references": ()}, "terms"),
        )
        for fresh, changes, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                self.journal = Path(directory)
                open_session(self.journal, 1_000, 100)
                result, _load = self.consume(fresh, **changes)
                self.assertEqual(result["status"], "rejected")
                self.assertIn(reason, result["reason"])
                self.assertEqual(set(replay(self.journal).finished_turns.values()), {"rejected"})
                self.assertFalse(replay(self.journal).positions)
                if changes:
                    _load.assert_not_called()

    def test_current_price_depth_edge_and_exposure_are_rejected(self) -> None:
        cases = (
            (self.snapshot("fresh", price=0.51), {}, "maximum entry price"),
            (self.snapshot("fresh", asks=(BookLevel(0.42, 1),)), {}, "depth"),
            (self.snapshot("fresh", price=0.56), {"max_entry_price": 0.7}, "edge"),
            (self.snapshot("fresh", total_exposure=95), {}, "total exposure"),
        )
        for fresh, changes, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                self.journal = Path(directory)
                open_session(self.journal, 1_000, 100)
                result, _load = self.consume(fresh, **changes)
                self.assertEqual(result["status"], "rejected")
                self.assertIn(reason, result["reason"])
                self.assertFalse(replay(self.journal).positions)

    def test_quote_failure_does_not_admit_or_fill_and_remains_retryable(self) -> None:
        load = Mock(side_effect=RuntimeError("network secret"))

        with self.assertRaisesRegex(RuntimeError, "network secret"):
            consume_paper_event(
                self.journal,
                self.event,
                self.operating,
                now=self.now,
                load=load,
                fetch=Mock(),
                paper_fee_rate=0,
                paper_fee_source="paper-assumption:no-fee-v1",
            )

        state = replay(self.journal)
        self.assertFalse(state.admitted_turns)
        self.assertFalse(state.positions)

    def test_realized_loss_halts_before_quote_or_admission(self) -> None:
        admit_turn(self.journal, "loss", "loss-snapshot", "loss-market")
        record_fill(
            self.journal,
            Position(
                "loss-market",
                "loss-snapshot",
                self.now.isoformat(),
                0.4,
                101,
                252.5,
                0,
                101,
                ExitPlan(0.1, -0.2, "2026-10-08T12:00:00+00:00"),
            ),
            "loss",
        )
        finish_turn(self.journal, "loss", "filled")
        settle(self.journal, replay(self.journal), "loss-market", "resolved_no")
        self.assertEqual(replay(self.journal).status, "open")
        self.assertLess(replay(self.journal).realized_pnl, -100)
        load = Mock()
        fetch = Mock()

        with self.assertRaisesRegex(JournalError, "open session"):
            consume_paper_event(
                self.journal,
                self.event,
                self.operating,
                now=self.now,
                load=load,
                fetch=fetch,
                paper_fee_rate=0,
                paper_fee_source="paper-assumption:no-fee-v1",
            )

        state = replay(self.journal)
        self.assertEqual(state.status, "halted_on_loss")
        self.assertFalse(state.positions)
        self.assertNotIn(self.event.event_id, state.admitted_turns)
        load.assert_not_called()
        fetch.assert_not_called()

    def test_requires_an_existing_open_session(self) -> None:
        empty = self.journal / "empty"
        with self.assertRaisesRegex(Exception, "open session"):
            consume_paper_event(
                empty,
                self.event,
                self.operating,
                now=self.now,
                load=Mock(),
                fetch=Mock(),
                paper_fee_rate=0,
                paper_fee_source="paper-assumption:no-fee-v1",
            )

    def test_cli_consumes_event_with_mocked_public_quote_and_reports_duplicate(self) -> None:
        source = self.journal / "event.json"
        source.write_text(json.dumps(asdict(self.event)))
        fresh = self.snapshot("quote-snapshot")
        with MockCli(), MockQuote(fresh) as load:
            first = cli.main(("consume", "--event", str(source), "--journal", str(self.journal)))
            second = cli.main(("consume", "--event", str(source), "--journal", str(self.journal)))

        self.assertEqual((first, second), (0, 0))
        self.assertEqual(load.call_count, 1)

    def test_cli_rejects_unsafe_event_input_and_sanitizes_quote_failure(self) -> None:
        source = self.journal / "event.json"
        source.write_text('{"schema_version":1,"schema_version":1}')
        with MockCli() as output:
            with self.assertRaisesRegex(SystemExit, "2"):
                cli.main(("consume", "--event", str(source), "--journal", str(self.journal)))
        self.assertEqual(output.stderr.getvalue(), "consume failed: invalid event\n")

        source.write_text(json.dumps(asdict(self.event)))
        with MockCli() as output, MockQuote(side_effect=RuntimeError("private token")):
            with self.assertRaisesRegex(SystemExit, "2"):
                cli.main(("consume", "--event", str(source), "--journal", str(self.journal)))
        self.assertEqual(output.stderr.getvalue(), "consume failed: market data unavailable\n")
        self.assertNotIn("private token", output.stderr.getvalue())


class MockCli:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(contextlib.redirect_stdout(self.stdout))
        self.stack.enter_context(contextlib.redirect_stderr(self.stderr))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class MockQuote:
    def __init__(self, value=None, *, side_effect=None) -> None:
        self.mock = Mock(return_value=value, side_effect=side_effect)

    def __enter__(self):
        self.patch = __import__("unittest.mock", fromlist=["patch"]).patch(
            "chrysopoeia.cli.load_market_snapshot", self.mock
        )
        self.patch.start()
        return self.mock

    def __exit__(self, *args):
        self.patch.stop()


if __name__ == "__main__":
    unittest.main()
