import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chrysopoeia.accounting import (
    Position,
    admit_turn,
    finish_turn,
    journal_path,
    open_session,
    record_fill,
    replay,
)
from chrysopoeia.loop import _report
from chrysopoeia.operations import evaluate_exits
from chrysopoeia.trading import BookLevel, ExitPlan, MarketSnapshot

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def market_snapshot(
    bids: tuple[BookLevel, ...], now: datetime = NOW
) -> MarketSnapshot:
    return MarketSnapshot(
        "exit-snapshot",
        "market-1",
        0.6,
        1_000,
        10.2,
        10.2,
        question="Will it rain?",
        resolution_rules="Resolves from official rainfall data.",
        end_time=(now + timedelta(days=1)).isoformat(),
        captured_at=now.isoformat(),
        source_url="https://polymarket.com/event/will-it-rain",
        yes_token_id="yes-token",
        asks=(BookLevel(0.6, 100),),
        fee_rate=0.02,
        fee_source="paper-assumption:flat-2pct-v1",
        book_captured_at=now.isoformat(),
        bids=bids,
    )


class ExitEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.journal = Path(self.temporary.name)
        open_session(
            self.journal,
            1_000,
            1,
            target_win_rate=0.6,
            window_end=NOW + timedelta(hours=1),
            window_minutes=60,
        )
        admit_turn(self.journal, "entry-turn", "entry-snapshot", "market-1")
        record_fill(
            self.journal,
            Position(
                "market-1",
                "entry-snapshot",
                NOW.isoformat(),
                0.4,
                10,
                25,
                0.2,
                10.2,
                ExitPlan(
                    take_profit_roi=0.1,
                    stop_loss_roi=-0.2,
                    exit_by="2026-09-30T13:00:00+00:00",
                ),
            ),
            "entry-turn",
        )
        finish_turn(self.journal, "entry-turn", "filled")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def evaluate(self, bids: tuple[BookLevel, ...], now: datetime = NOW):
        snapshot = market_snapshot(bids, now)
        return evaluate_exits(
            self.journal,
            ("market-1",),
            now=now,
            fetch=lambda *_: b"",
            paper_fee_rate=0.02,
            paper_fee_source="paper-assumption:flat-2pct-v1",
            load=lambda *_args, **_kwargs: snapshot,
        )

    def test_take_profit_closes_full_position_at_net_executable_roi(self) -> None:
        result = self.evaluate((BookLevel(0.5, 25),))

        book = replay(self.journal)
        self.assertEqual(result[0]["exit_reason"], "take_profit")
        self.assertNotIn("market-1", book.positions)
        self.assertAlmostEqual(book.realized_pnl, 2.05)
        self.assertEqual(book.closed_trades, 1)
        report = _report(book, "max_cycles", 1)
        self.assertEqual(report["win_rate"], 1)
        before = len(journal_path(self.journal).read_text().splitlines())
        self.evaluate((BookLevel(0.5, 25),))
        self.assertEqual(len(journal_path(self.journal).read_text().splitlines()), before)

    def test_stop_loss_closes_the_full_position_after_a_gap(self) -> None:
        result = self.evaluate((BookLevel(0.28, 25),))

        self.assertEqual(result[0]["exit_reason"], "stop_loss")
        self.assertEqual(replay(self.journal).status, "halted_on_loss")
        self.assertNotIn("market-1", replay(self.journal).positions)

    def test_time_exit_closes_at_the_current_quote_after_deadline(self) -> None:
        result = self.evaluate(
            (BookLevel(0.4, 25),), NOW + timedelta(hours=2)
        )

        self.assertEqual(result[0]["exit_reason"], "time")
        self.assertNotIn("market-1", replay(self.journal).positions)

    def test_missing_or_insufficient_bid_depth_keeps_position_open(self) -> None:
        for bids in ((), (BookLevel(0.5, 10),)):
            with self.subTest(bids=bids), self.assertRaisesRegex(
                ValueError, "insufficient executable YES bid depth"
            ):
                self.evaluate(bids, NOW + timedelta(hours=2))
            self.assertIn("market-1", replay(self.journal).positions)
