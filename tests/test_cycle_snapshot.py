import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from chrysopoeia import cli
from chrysopoeia.cli import load_capture_snapshot, serialize_market_snapshot
from chrysopoeia.configuration import load_harness_config
from chrysopoeia.trading import BookLevel, MarketSnapshot, OperatingConfig

ROOT = Path(__file__).parents[1]


class CycleSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_harness_config(ROOT / "chrysopoeia.toml")
        self.operating = OperatingConfig()
        self.snapshot = MarketSnapshot(
            "placeholder",
            "12345",
            0.4,
            1,
            0,
            0,
            question="Will it rain?",
            resolution_rules="Resolves Yes if rain is measured.",
            end_time="2027-01-01T00:00:00+00:00",
            captured_at="2026-09-01T00:00:00+00:00",
            source_url="https://polymarket.com/event/will-it-rain",
            yes_token_id="yes-token",
            asks=(BookLevel(0.4, 20), BookLevel(0.5, 10)),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )

    def write_record(self, path: Path, record: dict[str, object] | None = None) -> None:
        from chrysopoeia.trading import market_snapshot_identity

        snapshot = replace(
            self.snapshot, snapshot_id=market_snapshot_identity(self.snapshot)
        )
        path.write_text(
            json.dumps(record or serialize_market_snapshot(snapshot)), encoding="utf-8"
        )

    def test_reconstructs_with_operating_account_state_and_validates_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            self.write_record(path)
            snapshot = load_capture_snapshot(path, self.config, self.operating, 3, 7)

        self.assertEqual(
            (snapshot.bankroll, snapshot.market_exposure, snapshot.total_exposure),
            (1_000, 3, 7),
        )
        from chrysopoeia.trading import market_snapshot_identity

        self.assertEqual(snapshot.snapshot_id, market_snapshot_identity(snapshot))

    def test_rejects_schema_fee_identity_and_file_boundary_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            self.write_record(valid)
            base = json.loads(valid.read_text())
            cases = []
            for mutate in (
                lambda value: value.update(extra=True),
                lambda value: value["snapshot"].update(extra=True),
                lambda value: value["snapshot"].update(price=True),
                lambda value: value["snapshot"].update(fee_rate=0.03),
                lambda value: value["snapshot"].update(snapshot_id="forged"),
                lambda value: value["snapshot"].update(asks=[]),
            ):
                value = json.loads(json.dumps(base))
                mutate(value)
                cases.append(value)
            for index, value in enumerate(cases):
                path = root / f"bad-{index}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(index=index), self.assertRaises(ValueError):
                    load_capture_snapshot(path, self.config, self.operating, 0, 0)

            link = root / "link.json"
            link.symlink_to(valid)
            with self.assertRaises(ValueError):
                load_capture_snapshot(link, self.config, self.operating, 0, 0)
            oversized = root / "oversized.json"
            oversized.write_bytes(b" " * (512 * 1024 + 1))
            with self.assertRaises(ValueError):
                load_capture_snapshot(oversized, self.config, self.operating, 0, 0)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(ValueError):
                load_capture_snapshot(duplicate, self.config, self.operating, 0, 0)

    def test_rejects_huge_json_integer_safely_in_loader_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huge.json"
            self.write_record(path)
            record = json.loads(path.read_text())
            record["snapshot"]["price"] = 10**10000
            previous = (
                sys.get_int_max_str_digits()
                if hasattr(sys, "get_int_max_str_digits")
                else None
            )
            try:
                if hasattr(sys, "set_int_max_str_digits"):
                    sys.set_int_max_str_digits(0)
                path.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_capture_snapshot(path, self.config, self.operating)

                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        cli.main(("cycle", "--snapshot", str(path)))
            finally:
                if previous is not None:
                    sys.set_int_max_str_digits(previous)

        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "cycle failed: invalid snapshot\n")


if __name__ == "__main__":
    unittest.main()
