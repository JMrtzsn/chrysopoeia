import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from chrysopoeia import cli
from chrysopoeia.accounting import Position as BookPosition
from chrysopoeia.accounting import (
    journal_path,
    open_session,
    record_fill,
    replay,
)


def open_filled_journal(journal: Path, market_id: str = "559651") -> None:
    open_session(journal, 1_000.0, 100.0)
    record_fill(
        journal,
        replay(journal),
        BookPosition(
            market_id=market_id,
            snapshot_id="snap-1",
            entered_at="2026-09-15T00:00:00+00:00",
            price=0.005,
            amount=120.0,
            shares=24_000.0,
            fee=2.4,
            total_cost=122.4,
        ),
    )


def capture_stub(price: float, captured_at: str):
    record = Mock()
    record.price = price
    record.captured_at = captured_at
    return Mock(return_value=record)


class MarkCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.journal = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(arguments)
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_mark_records_fresh_venue_prices(self) -> None:
        open_filled_journal(self.journal)
        with patch(
            "chrysopoeia.cli.load_market_snapshot",
            capture_stub(0.02, "2026-09-15T12:00:00+00:00"),
        ):
            code, stdout, stderr = self.invoke("mark", "--journal", str(self.journal))
        self.assertEqual((code, stderr), (0, ""))
        report = json.loads(stdout)
        self.assertEqual(report["record_type"], "book_mark_report")
        self.assertEqual(report["marked"][0]["entry_price"], 0.005)
        self.assertEqual(report["marked"][0]["mark_price"], 0.02)
        self.assertAlmostEqual(report["unrealized_pnl"], 24_000.0 * 0.02 - 122.4)
        self.assertEqual(
            len(journal_path(self.journal).read_text().splitlines()),
            3,  # session, fill, mark
        )

    def test_mark_with_no_open_positions_reports_without_captures(self) -> None:
        open_session(self.journal, 1_000.0, 100.0)
        with patch(
            "chrysopoeia.cli.load_market_snapshot", Mock(side_effect=AssertionError)
        ):
            code, stdout, stderr = self.invoke("mark", "--journal", str(self.journal))
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["marked"], [])

    def test_mark_failure_leaves_no_mark_record(self) -> None:
        open_filled_journal(self.journal)
        with patch(
            "chrysopoeia.cli.load_market_snapshot",
            Mock(side_effect=Exception("down")),
        ):
            code, _stdout, stderr = self.invoke("mark", "--journal", str(self.journal))
        self.assertEqual(code, 2)
        self.assertIn("mark capture for market 559651 failed", stderr)
        # the failed capture must not have journaled a mark
        self.assertEqual(len(journal_path(self.journal).read_text().splitlines()), 2)
        state = replay(self.journal)
        self.assertIn("559651", state.positions)
        self.assertNotIn("559651", state.marks)


if __name__ == "__main__":
    unittest.main()
