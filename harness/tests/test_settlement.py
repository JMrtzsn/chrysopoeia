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
from chrysopoeia.polymarket import PolymarketError, load_market_resolution


def gamma_response(**overrides: object) -> dict[str, object]:
    return {
        "id": "559651",
        "closed": True,
        "outcomePrices": ["1", "0"],
        **overrides,
    }


def fetch_of(data: object):
    return lambda url, timeout, max_bytes: json.dumps(data).encode()


class ResolutionAdapterTests(unittest.TestCase):
    def test_resolved_yes_normalizes_from_venue_data(self) -> None:
        resolution = load_market_resolution("559651", fetch=fetch_of(gamma_response()))
        self.assertEqual(resolution.resolution, "resolved_yes")
        self.assertEqual(resolution.market_id, "559651")

    def test_resolved_no_indexes_the_winning_outcome(self) -> None:
        resolution = load_market_resolution(
            "559651", fetch=fetch_of(gamma_response(outcomePrices=["0", "1"]))
        )
        self.assertEqual(resolution.resolution, "resolved_no")

    def test_unclosed_markets_do_not_resolve(self) -> None:
        with self.assertRaises(PolymarketError):
            load_market_resolution(
                "559651", fetch=fetch_of(gamma_response(closed=False))
            )

    def test_unpriced_markets_do_not_resolve(self) -> None:
        for prices in (
            ["0.4", "0.6"],
            ["stale", "0"],
            ["0.5"],
            ["2.0", "1.0"],
            ["0", "0"],
            ["0.999", "0.999"],
        ):
            with self.assertRaises(PolymarketError):
                load_market_resolution(
                    "559651", fetch=fetch_of(gamma_response(outcomePrices=prices))
                )

    def test_named_stale_outcomes_still_normalize_when_dominant(self) -> None:
        # Gamma often leaves settled markets at ~0.000001 / ~0.999999
        prices = ["0.0000010245195095", "0.9999989754804904"]
        resolution = load_market_resolution(
            "559651", fetch=fetch_of(gamma_response(outcomePrices=prices))
        )
        self.assertEqual(resolution.resolution, "resolved_no")

    def test_malformed_ids_are_refused(self) -> None:
        with self.assertRaises(PolymarketError):
            load_market_resolution("559651", fetch=fetch_of(gamma_response(id="nope")))


@contextlib.contextmanager
def venue_resolution(market_id: str, resolution: str):
    def loader(market: str, **_: object):
        if market != market_id:
            raise PolymarketError("no such market")
        record = Mock()
        record.as_dict = Mock(
            return_value={
                "market_id": market_id,
                "resolution": resolution,
                "resolved_at": "2026-09-15T12:00:00+00:00",
            }
        )
        return record

    with patch(
        "chrysopoeia.polymarket.load_market_resolution", Mock(side_effect=loader)
    ):
        yield


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


class SettleCliTests(unittest.TestCase):
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

    def test_settlement_realizes_pnl_against_venue_resolution(self) -> None:
        open_filled_journal(self.journal)
        with venue_resolution("559651", "resolved_yes"):
            code, stdout, stderr = self.invoke(
                "settle", "--journal", str(self.journal), "--market", "559651"
            )
        self.assertEqual((code, stderr), (0, ""))
        report = json.loads(stdout)
        self.assertEqual(report["resolution"], "resolved_yes")
        # 24_000 shares * 1.0 * (1 - 0.02 fee) = 23,520 gross - 122.4 cost
        self.assertAlmostEqual(report["realized_pnl"], 23_397.6)
        self.assertEqual(report["open_positions"], 0)
        self.assertEqual(
            len(journal_path(self.journal).read_text().splitlines()),
            3,  # session, fill, settled
        )

    def test_loss_settlement_crossing_the_budget_halts_the_session(self) -> None:
        open_filled_journal(self.journal)
        with venue_resolution("559651", "resolved_no"):
            code, stdout, stderr = self.invoke(
                "settle", "--journal", str(self.journal), "--market", "559651"
            )
        self.assertEqual((code, stderr), (0, ""))
        report = json.loads(stdout)
        # -$122.4 crosses the $100 cumulative-loss budget: halted
        self.assertEqual(report["resolution"], "resolved_no")
        self.assertAlmostEqual(report["realized_pnl"], -122.4)
        self.assertEqual(report["status"], "halted_on_loss")
        self.assertEqual(replay(self.journal).status, "halted_on_loss")
        self.assertEqual(
            len(journal_path(self.journal).read_text().splitlines()),
            4,  # session, fill, settled, session_halted
        )

    def test_settle_refuses_markets_without_an_open_position(self) -> None:
        open_filled_journal(self.journal)
        with venue_resolution("559651", "resolved_yes"):
            code, _stdout, stderr = self.invoke(
                "settle", "--journal", str(self.journal), "--market", "999"
            )
        self.assertEqual(code, 2)
        self.assertIn("no open position", stderr)

    def test_settle_refuses_an_unavailable_resolution(self) -> None:
        open_filled_journal(self.journal)
        with patch(
            "chrysopoeia.polymarket.load_market_resolution",
            Mock(side_effect=PolymarketError("down")),
        ):
            code, _stdout, stderr = self.invoke(
                "settle", "--journal", str(self.journal), "--market", "559651"
            )
        self.assertEqual(code, 2)
        self.assertIn("settle failed", stderr)


if __name__ == "__main__":
    unittest.main()
