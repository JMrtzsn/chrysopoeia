import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from chrysopoeia import cli
from chrysopoeia.paper_cycle import _canonical_evidence, external_evidence
from chrysopoeia.trading import BookLevel, MarketSnapshot, market_snapshot_identity


class EvidenceCliTests(unittest.TestCase):
    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(arguments)
            except SystemExit as exc:
                code = int(exc.code)
        return code, stdout.getvalue(), stderr.getvalue()

    def snapshot(self) -> MarketSnapshot:
        value = MarketSnapshot(
            "placeholder",
            "market-1",
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
            asks=(BookLevel(0.4, 10),),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )
        return replace(value, snapshot_id=market_snapshot_identity(value))

    def test_cycle_accepts_hand_authored_evidence_bundle_without_fetching(self) -> None:
        market = self.snapshot()
        external = external_evidence(
            market, "https://example.com/report", "Report", "2026-09-02T00:00:00Z"
        )
        envelope = {
            "schema_version": 1,
            "record_type": "evidence_bundle",
            "snapshot_id": market.snapshot_id,
            "market_id": market.market_id,
            "evidence": [
                *[record.model_dump() for record in _canonical_evidence(market)],
                external.model_dump(),
            ],
            "provenance": "operator-supplied-unverified",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, evidence_path = (
                root / "snapshot.json",
                root / "evidence.json",
            )
            snapshot_path.write_text(json.dumps(cli.serialize_market_snapshot(market)))
            evidence_path.write_text(json.dumps(envelope))
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value={"status": "abstained"}),
                ) as run,
                patch("chrysopoeia.cli.polymarket_fetch") as fetch,
            ):
                code, _, stderr = self.invoke(
                    "cycle",
                    "--snapshot",
                    str(snapshot_path),
                    "--evidence",
                    str(evidence_path),
                )

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(run.call_args.kwargs["evidence"][-1], external)
        fetch.assert_not_called()

    def test_cycle_rejects_invalid_evidence_with_safe_error(self) -> None:
        market = self.snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path, evidence_path = (
                root / "snapshot.json",
                root / "evidence.json",
            )
            snapshot_path.write_text(json.dumps(cli.serialize_market_snapshot(market)))
            evidence_path.write_text('{"secret":"do-not-leak"}')
            with patch("chrysopoeia.cycle_runner.run_paper_cycle") as run:
                result = self.invoke(
                    "cycle",
                    "--snapshot",
                    str(snapshot_path),
                    "--evidence",
                    str(evidence_path),
                )

        self.assertEqual(result, (2, "", "cycle failed: invalid evidence\n"))
        self.assertNotIn("secret", result[2])
        self.assertNotIn("Traceback", result[2])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
