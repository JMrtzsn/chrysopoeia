import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chrysopoeia import cli
from chrysopoeia.accounting import (
    Book,
    JournalError,
    Position,
    admit_turn,
    check_halt,
    close_session,
    finish_turn,
    journal_path,
    open_session,
    record_fill,
    record_mark,
    recover_open_turns,
    replay,
    settle,
)


def _position(market_id: str = "m1", **overrides: float) -> Position:
    values: dict[str, object] = {
        "snapshot_id": "snap-1",
        "price": 0.4,
        "amount": 10.0,
        "shares": 25.0,
        "fee": 0.2,
        "total_cost": 10.2,
    }
    values |= overrides
    return Position(
        market_id=market_id, entered_at="2026-09-15T00:00:00+00:00", **values
    )


def _record_fill(directory: Path, position: Position) -> None:
    turn_id = f"turn-{position.market_id}"
    admit_turn(directory, turn_id, position.snapshot_id, position.market_id)
    record_fill(directory, position, turn_id)
    finish_turn(directory, turn_id, "filled")


class AccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())

    def book(self) -> Book:
        return open_session(self.directory, 1_000.0, 100.0)

    def test_empty_journal_replays_as_empty_book(self) -> None:
        self.assertEqual(replay(self.directory).status, "empty")

    def test_open_session_is_idempotent_with_same_configuration(self) -> None:
        first = self.book()
        second = self.book()
        self.assertEqual(first.bankroll, second.bankroll)
        self.assertEqual(len(journal_path(self.directory).read_text().splitlines()), 1)

    def test_open_session_rejects_configuration_change(self) -> None:
        self.book()
        with self.assertRaises(JournalError):
            open_session(self.directory, 2_000.0, 100.0)

    def test_turn_admission_is_a_no_op_for_a_repeated_identity(self) -> None:
        self.book()
        first = admit_turn(self.directory, "t1", "snap-1", "m1")
        second = admit_turn(self.directory, "t1", "snap-1", "m1")
        self.assertEqual(first, second)
        self.assertEqual(len(replay(self.directory).admitted_turns), 1)

    def test_turn_admission_rejects_a_conflicting_identity(self) -> None:
        self.book()
        admit_turn(self.directory, "t1", "snap-1", "m1")
        with self.assertRaises(JournalError):
            admit_turn(self.directory, "t1", "snap-2", "m1")

    def test_turn_finish_exposes_only_admitted_unfinished_turns(self) -> None:
        self.book()
        admit_turn(self.directory, "t1", "snap-1", "m1")
        admit_turn(self.directory, "t2", "snap-2", "m2")
        finish_turn(self.directory, "t1", "abstained")

        book = replay(self.directory)

        self.assertEqual(set(book.open_turns), {"t2"})
        self.assertEqual(book.finished_turns["t1"], "abstained")

    def test_replay_rejects_unknown_or_duplicate_turn_finish(self) -> None:
        self.book()
        finish = {
            "schema_version": 1,
            "record_type": "turn_finished",
            "recorded_at": "2026-09-15T00:00:00+00:00",
            "turn_id": "missing",
            "outcome": "failed",
        }
        with journal_path(self.directory).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(finish) + "\n")
        with self.assertRaises(JournalError):
            replay(self.directory)

        journal_path(self.directory).write_text("")
        self.book()
        admit_turn(self.directory, "t1", "snap-1", "m1")
        finish_turn(self.directory, "t1", "abstained")
        with journal_path(self.directory).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**finish, "turn_id": "t1"}) + "\n")
        with self.assertRaises(JournalError):
            replay(self.directory)

    def test_fill_requires_an_open_known_turn_on_write_and_replay(self) -> None:
        self.book()
        with self.assertRaises(JournalError):
            record_fill(self.directory, _position(), "missing")

        admit_turn(self.directory, "t1", "snap-1", "m1")
        finish_turn(self.directory, "t1", "abstained")
        with self.assertRaises(JournalError):
            record_fill(self.directory, _position(), "t1")

        record = {
            "schema_version": 1,
            "record_type": "fill_recorded",
            "recorded_at": "2026-09-15T00:00:00+00:00",
            "turn_id": "missing",
            "market_id": "m1",
            "snapshot_id": "snap-1",
            "price": 0.4,
            "amount": 10.0,
            "shares": 25.0,
            "fee": 0.2,
            "total_cost": 10.2,
        }
        with journal_path(self.directory).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        with self.assertRaises(JournalError):
            replay(self.directory)

        journal_path(self.directory).write_text("")
        self.book()
        admit_turn(self.directory, "t1", "snap-1", "m1")
        finish_turn(self.directory, "t1", "abstained")
        with journal_path(self.directory).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**record, "turn_id": "t1"}) + "\n")
        with self.assertRaises(JournalError):
            replay(self.directory)

    def test_legacy_fill_without_turn_id_still_replays(self) -> None:
        self.book()
        record = {
            "schema_version": 1,
            "record_type": "fill_recorded",
            "recorded_at": "2026-09-15T00:00:00+00:00",
            "market_id": "m1",
            "snapshot_id": "snap-1",
            "price": 0.4,
            "amount": 10.0,
            "shares": 25.0,
            "fee": 0.2,
            "total_cost": 10.2,
        }
        with journal_path(self.directory).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        self.assertIn("m1", replay(self.directory).positions)

    def test_recovery_finishes_filled_turns_and_abandons_the_rest_once(self) -> None:
        self.book()
        admit_turn(self.directory, "filled", "snap-1", "m1")
        record_fill(self.directory, _position(), "filled")
        admit_turn(self.directory, "empty", "snap-2", "m2")

        recovered = recover_open_turns(self.directory)
        count = len(journal_path(self.directory).read_text().splitlines())
        recovered_again = recover_open_turns(self.directory)

        self.assertEqual(recovered, {"filled": "filled", "empty": "abandoned"})
        self.assertEqual(recovered_again, {})
        self.assertEqual(
            len(journal_path(self.directory).read_text().splitlines()), count
        )
        records = [
            json.loads(line)
            for line in journal_path(self.directory).read_text().splitlines()
        ]
        self.assertEqual(
            sum(record["record_type"] == "fill_recorded" for record in records), 1
        )

    def test_journal_append_fsyncs_the_single_append_write(self) -> None:
        calls = []
        write_record = __import__("os").write
        with (
            patch(
                "chrysopoeia.accounting.os.write",
                side_effect=lambda descriptor, line: (
                    calls.append("write") or write_record(descriptor, line)
                ),
            ) as write,
            patch(
                "chrysopoeia.accounting.os.fsync",
                side_effect=lambda _descriptor: calls.append("fsync"),
            ) as fsync,
        ):
            self.book()
        write.assert_called_once()
        fsync.assert_called_once()
        self.assertEqual(calls, ["write", "fsync"])

    def test_replay_rejects_a_torn_final_line(self) -> None:
        self.book()
        journal = journal_path(self.directory)
        journal.write_bytes(journal.read_bytes().rstrip(b"\n"))
        with self.assertRaises(JournalError):
            replay(self.directory)

    def test_turn_admission_and_fills_require_an_open_session(self) -> None:
        close_session(self.directory, self.book())
        with self.assertRaises(JournalError):
            admit_turn(self.directory, "t1", "snap-1", "m1")
        with self.assertRaises(JournalError):
            record_fill(self.directory, _position(), "t1")
        self.assertEqual(replay(self.directory).status, "closed")

    def test_fill_marks_market_position_open(self) -> None:
        self.book()
        _record_fill(self.directory, _position())
        replayed = replay(self.directory)
        self.assertIn("m1", replayed.positions)
        self.assertEqual(replayed.open_exposure, 10.2)
        with self.assertRaises(JournalError):
            record_fill(self.directory, _position(), "turn-m1")

    def test_settlement_yes_realizes_fee_inclusive_gain(self) -> None:
        self.book()
        _record_fill(self.directory, _position())
        book = replay(self.directory)
        settle(self.directory, book, "m1", "resolved_yes")
        final = replay(self.directory)
        # 25 shares at 1.0 gross, 0.02 fee => 24.5 - 10.2 = 14.3
        self.assertAlmostEqual(final.realized_pnl, 14.3)
        self.assertNotIn("m1", final.positions)

    def test_settlement_no_realizes_total_loss(self) -> None:
        self.book()
        _record_fill(self.directory, _position())
        settle(self.directory, replay(self.directory), "m1", "resolved_no")
        self.assertAlmostEqual(replay(self.directory).realized_pnl, -10.2)

    def test_cumulative_loss_crossing_the_budget_halts_the_session(self) -> None:
        self.book()
        _record_fill(self.directory, _position())
        settle(self.directory, replay(self.directory), "m1", "resolved_no")
        self.assertIsNone(check_halt(self.directory, replay(self.directory)))
        _record_fill(self.directory, _position("m2"))
        _record_fill(self.directory, _position("m3"))
        for market in ("m2", "m3"):
            settle(self.directory, replay(self.directory), market, "resolved_no")
        halted = replay(self.directory)
        self.assertIsNone(check_halt(self.directory, halted))
        # two settlements of -10.2 do not cross the 100 budget; force one that does
        for market in ("m4", "m5", "m6", "m7", "m8", "m9", "m10"):
            _record_fill(self.directory, _position(market))
            settle(self.directory, replay(self.directory), market, "resolved_no")
        final = replay(self.directory)
        recorded = check_halt(self.directory, final)
        self.assertIsNotNone(recorded)
        self.assertEqual(replay(self.directory).status, "halted_on_loss")
        with self.assertRaises(JournalError):
            admit_turn(self.directory, "late", "snap-1", "m11")

    def test_marks_drive_unrealized_pnl(self) -> None:
        self.book()
        _record_fill(self.directory, _position())
        record_mark(self.directory, replay(self.directory), "m1", 0.6)
        book = replay(self.directory)
        self.assertAlmostEqual(book.unrealized_pnl, 25.0 * 0.6 - 10.2)
        with self.assertRaises(ValueError):
            record_mark(self.directory, book, "m1", 1.4)

    def test_corrupt_journal_is_refused(self) -> None:
        self.book()
        with journal_path(self.directory).open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        with self.assertRaises(JournalError):
            replay(self.directory)


class BookCliTests(unittest.TestCase):
    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(arguments)
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_book_reports_position_and_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            open_session(journal, 1_000.0, 100.0)
            _record_fill(journal, _position())
            record_mark(journal, replay(journal), "m1", 0.5)
            code, output, _error = self.invoke("book", "--journal", str(journal))
            self.assertEqual(code, 0)
            report = json.loads(output)
            self.assertEqual(report["status"], "open")
            self.assertEqual(report["open_positions"][0]["market_id"], "m1")
            self.assertAlmostEqual(report["open_exposure"], 10.2)
            self.assertAlmostEqual(report["unrealized_pnl"], 2.3)
            self.assertEqual(report["open_turns"], 0)

    def test_book_reports_corrupt_journal_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "chrysopoeia.jsonl").write_text("garbage\n")
            code, _output, error = self.invoke("book", "--journal", directory)
            self.assertEqual(code, 2)
            self.assertIn("book failed", error)


if __name__ == "__main__":
    unittest.main()
