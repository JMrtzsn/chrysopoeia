import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from chrysopoeia import cli
from chrysopoeia.polymarket import PolymarketError
from chrysopoeia.trading import MarketSnapshot

ROOT = Path(__file__).parents[1]
EXPECTED = {
    "command": "inspect",
    "config_path": "chrysopoeia.toml",
    "cost_policy": {
        "input_usd_per_million_tokens": "1",
        "maximum_input_tokens_per_call": 8192,
        "maximum_model_calls_per_cycle": 12,
        "maximum_output_tokens_per_call": 1024,
        "model": "gemini-flash-latest",
        "output_usd_per_million_tokens": "3",
        "version": "project-estimate-2026-08-v1",
    },
    "models": {
        "context": "gemini-flash-latest",
        "reviewer": "gemini-flash-latest",
        "root": "gemini-flash-latest",
        "trader": "gemini-flash-latest",
    },
    "runtime": {"adapter": "adk", "mode": "paper"},
    "schema_version": 1,
    "valid": True,
    "venue": {
        "adapter": "polymarket",
        "execution": "paper-only",
        "market_data": "public-read-only",
        "paper_fee_rate": 0.02,
        "paper_fee_source": "paper-assumption:flat-2pct-v1",
    },
}


class OperatorCliTests(unittest.TestCase):
    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = cli.main(arguments)
            except SystemExit as exc:
                code = int(exc.code)
        return code, stdout.getvalue(), stderr.getvalue()

    def fixture_fetch(self, calls: list[str] | None = None):
        now = datetime.now(timezone.utc)
        metadata = {
            "id": "12345",
            "slug": "will-it-rain",
            "eventSlug": "will-it-rain",
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "outcomes": ["Yes", "No"],
            "clobTokenIds": ["yes-token", "no-token"],
            "question": "Will it rain?",
            "description": "Resolves Yes if measurable rain is recorded.",
            "endDate": (now + timedelta(days=1)).isoformat(),
            "updatedAt": (now - timedelta(seconds=1)).isoformat(),
        }
        book = {
            "asset_id": "yes-token",
            "timestamp": str(int((now - timedelta(seconds=1)).timestamp() * 1000)),
            "asks": [
                {"price": "0.44", "size": "10"},
                {"price": "0.42", "size": "20"},
            ],
            "bids": [{"price": "0.40", "size": "5"}],
        }

        def fetch(url: str, _timeout: float, _max_bytes: int) -> bytes:
            if calls is not None:
                calls.append(url)
            value = book if "clob.polymarket.com" in url else metadata
            return json.dumps(value).encode()

        return fetch

    def run_cli(
        self, *arguments: str, cwd: str | Path | None = None, console: bool = False
    ) -> subprocess.CompletedProcess[str]:
        command = ["chrysopoeia"] if console else [sys.executable, "-m", "chrysopoeia"]
        return subprocess.run(
            [*command, *arguments], cwd=cwd, capture_output=True, text=True
        )

    def test_default_configuration_validates_as_json(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "chrysopoeia", "validate", "--json"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command"], "validate")
        self.assertEqual(result.stderr, "")

    def test_inspect_json_has_exact_stable_schema(self) -> None:
        first = self.run_cli("inspect", "--json")
        second = self.run_cli("inspect", "--json")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout), EXPECTED)
        self.assertEqual(first.stdout, second.stdout)
        self.assertNotIn("daily", first.stdout)

    def test_default_is_cwd_independent_and_entry_points_are_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            module = self.run_cli("validate", "--json", cwd=directory)
            console = self.run_cli("validate", "--json", cwd=directory, console=True)

        self.assertEqual(module.returncode, 0, module.stderr)
        self.assertEqual(console.returncode, 0, console.stderr)
        self.assertEqual(module.stdout, console.stdout)

    def test_alternate_configuration_uses_supplied_relative_label(self) -> None:
        text = (ROOT / "chrysopoeia.toml").read_text(encoding="utf-8")
        text = text.replace("gemini-flash-latest", "alternate-model").replace(
            'input_usd_per_million_tokens = "1"',
            'input_usd_per_million_tokens = "1.50"',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alternate.toml"
            path.write_text(text, encoding="utf-8")
            result = self.run_cli(
                "inspect", "--config", "alternate.toml", "--json", cwd=directory
            )

        summary = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(summary["config_path"], "alternate.toml")
        self.assertEqual(summary["models"]["root"], "alternate-model")
        self.assertEqual(summary["cost_policy"]["input_usd_per_million_tokens"], "1.50")

    def test_absolute_config_label_is_sanitized_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alternate.toml"
            path.write_text((ROOT / "chrysopoeia.toml").read_text(), encoding="utf-8")
            result = self.run_cli("inspect", "--config", str(path), "--json")

        label = json.loads(result.stdout)["config_path"]
        self.assertEqual(label, "alternate.toml")
        self.assertLessEqual(len(label), 200)

    def test_invalid_files_fail_safely(self) -> None:
        cases = {
            "malformed.toml": "[runtime\napi_key = 'very-secret-value'",
            "unknown.toml": (ROOT / "chrysopoeia.toml").read_text(encoding="utf-8")
            + "\napi_key = 'very-secret-value'\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, content in cases.items():
                path = Path(directory) / name
                path.write_text(content, encoding="utf-8")
                with self.subTest(name=name):
                    result = self.run_cli("validate", "--config", str(path), "--json")
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("configuration invalid:", result.stderr)
                    self.assertNotIn(directory, result.stderr)
                    self.assertNotIn("very-secret-value", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

            missing = Path(directory) / "missing.toml"
            result = self.run_cli("validate", "--config", str(missing))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(str(missing), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_human_output_and_argument_misuse(self) -> None:
        result = self.run_cli("validate")
        misuse = self.run_cli("validate", "--unknown")
        console_misuse = self.run_cli("validate", "--unknown", console=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("configuration valid: chrysopoeia.toml", result.stdout)
        self.assertIn("runtime: adk (paper)", result.stdout)
        self.assertIn("public-read-only, paper-only", result.stdout)
        self.assertEqual(misuse.returncode, 2)
        self.assertEqual(console_misuse.returncode, 2)
        self.assertNotIn("Traceback", misuse.stderr)

    def test_discover_accepts_default_and_bounded_limits(self) -> None:
        with patch("chrysopoeia.cli.discover_markets", return_value=()) as discover:
            code, stdout, stderr = self.invoke("discover")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["candidates"], [])
        discover.assert_called_once_with(limit=10, fetch=cli.polymarket_fetch)

        for limit in ("1", "20"):
            with (
                self.subTest(limit=limit),
                patch("chrysopoeia.cli.discover_markets", return_value=()) as discover,
            ):
                code, _, stderr = self.invoke("discover", "--limit", limit)
                self.assertEqual((code, stderr), (0, ""))
                discover.assert_called_once_with(
                    limit=int(limit), fetch=cli.polymarket_fetch
                )

        for limit in ("0", "21", "1.0", "true"):
            with self.subTest(limit=limit):
                code, stdout, stderr = self.invoke("discover", "--limit", limit)
                self.assertEqual((code, stdout), (2, ""))
                self.assertNotIn("Traceback", stderr)

    def test_discover_emits_exact_metadata_only_json_and_empty_success(self) -> None:
        from chrysopoeia.polymarket import MarketCandidate

        candidates = (
            MarketCandidate(
                "12345",
                "Will it rain?",
                "2026-09-14T12:00:00+00:00",
                "https://polymarket.com/event/will-it-rain",
                "12345",
            ),
        )
        with patch("chrysopoeia.cli.discover_markets", return_value=candidates):
            code, stdout, stderr = self.invoke("discover", "--limit", "1")

        expected = {
            "schema_version": 1,
            "record_type": "market_discovery",
            "venue": "polymarket",
            "mode": "public-read-only",
            "candidates": [
                {
                    "market_id": "12345",
                    "question": "Will it rain?",
                    "end_time": "2026-09-14T12:00:00+00:00",
                    "source_url": "https://polymarket.com/event/will-it-rain",
                    "capture": "12345",
                }
            ],
        }
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            stdout, json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
        )
        for forbidden in ("price", "liquidity", "volume", "bestAsk", "depth", "score"):
            self.assertNotIn(forbidden, stdout)

        with patch("chrysopoeia.cli.discover_markets", return_value=()):
            code, stdout, stderr = self.invoke("discover")
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["candidates"], [])

    def test_discover_failures_are_safe_and_config_precedes_io(self) -> None:
        secret = "private provider body /private/config.toml"
        with patch(
            "chrysopoeia.cli.discover_markets", side_effect=RuntimeError(secret)
        ):
            code, stdout, stderr = self.invoke("discover")
        self.assertEqual(
            (code, stdout, stderr),
            (2, "", "discovery failed: market data unavailable\n"),
        )
        self.assertNotIn(secret, stderr)
        self.assertNotIn("Traceback", stderr)

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "private.toml"
            config.write_text("[runtime\nsecret='do-not-leak'")
            with patch("chrysopoeia.cli.discover_markets") as discover:
                code, stdout, stderr = self.invoke("discover", "--config", str(config))
        self.assertEqual(
            (code, stdout, stderr),
            (2, "", "discovery failed: invalid configuration\n"),
        )
        discover.assert_not_called()

    def test_capture_accepts_url_and_identifier_and_emits_exact_public_record(
        self,
    ) -> None:
        for market in ("12345", "https://polymarket.com/event/weather/will-it-rain"):
            calls: list[str] = []
            with (
                self.subTest(market=market),
                patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch(calls)),
            ):
                code, stdout, stderr = self.invoke("capture", market)

            record = json.loads(stdout)
            self.assertEqual(code, 0, stderr)
            self.assertEqual(stderr, "")
            self.assertEqual(
                set(record),
                {"schema_version", "record_type", "venue", "mode", "snapshot"},
            )
            self.assertEqual(
                set(record["snapshot"]),
                {
                    "snapshot_id",
                    "market_id",
                    "price",
                    "question",
                    "resolution_rules",
                    "end_time",
                    "captured_at",
                    "source_url",
                    "yes_token_id",
                    "asks",
                    "fee_rate",
                    "fee_source",
                },
            )
            self.assertEqual(record["schema_version"], 1)
            self.assertEqual(record["record_type"], "market_snapshot")
            self.assertEqual((record["venue"], record["mode"]), ("polymarket", "paper"))
            self.assertEqual(record["snapshot"]["market_id"], "12345")
            self.assertEqual(record["snapshot"]["question"], "Will it rain?")
            self.assertEqual(
                record["snapshot"]["asks"],
                [{"price": 0.42, "size": 20.0}, {"price": 0.44, "size": 10.0}],
            )
            self.assertNotIn("bankroll", stdout)
            self.assertNotIn("exposure", stdout)
            self.assertEqual(
                stdout,
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
            )
            self.assertEqual(len(calls), 2)

    def test_capture_serializer_rejects_legacy_empty_metadata(self) -> None:
        snapshot = MarketSnapshot("snapshot", "12345", 0.5, 1, 0, 0)

        with self.assertRaises(ValueError):
            cli.serialize_market_snapshot(snapshot)

    def test_capture_passes_neutral_adapter_inputs(self) -> None:
        snapshot = MarketSnapshot("snapshot", "12345", 0.5, 1, 0, 0)
        load = Mock(return_value=snapshot)

        with patch("chrysopoeia.cli.load_market_snapshot", load):
            code, stdout, stderr = self.invoke("capture", "12345")

        self.assertEqual((code, stdout), (2, ""))
        self.assertEqual(stderr, "capture failed: market data unavailable\n")
        load.assert_called_once_with(
            "12345",
            bankroll=1.0,
            market_exposure=0.0,
            total_exposure=0.0,
            fetch=cli.polymarket_fetch,
            paper_fee_rate=0.02,
            paper_fee_source="paper-assumption:flat-2pct-v1",
        )

    def test_capture_output_matches_stdout_and_refuses_existing_or_symlink(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = set(root.iterdir())
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke("capture", "12345")
            self.assertEqual((code, stderr), (0, ""))
            self.assertTrue(stdout.endswith("\n"))
            self.assertEqual(set(root.iterdir()), before)

            output = root / "snapshot.json"
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(output)
                )
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(output.read_bytes(), stdout.encode())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

            output.write_bytes(b"preserve")
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(output)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: output unavailable\n")
            self.assertEqual(output.read_bytes(), b"preserve")

            target = root / "target"
            target.write_bytes(b"target")
            link = root / "link"
            link.symlink_to(target)
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(link)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: output unavailable\n")
            self.assertEqual(target.read_bytes(), b"target")

            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(root)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: output unavailable\n")

    def test_capture_output_failures_leave_no_target_or_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing" / "snapshot.json"
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(missing)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: output unavailable\n")
            self.assertFalse(missing.exists())

            output = root / "snapshot.json"
            with (
                patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()),
                patch(
                    "chrysopoeia.cli.os.link",
                    side_effect=OSError("private path or body"),
                ),
            ):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(output)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: output unavailable\n")
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [])

            with (
                patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()),
                patch("chrysopoeia.cli.os.fsync", side_effect=OSError("write failed")),
            ):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--output", str(output)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: output unavailable\n")
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_capture_uses_configured_fee_and_fails_safely_before_output(self) -> None:
        text = (
            (ROOT / "chrysopoeia.toml")
            .read_text(encoding="utf-8")
            .replace("paper_fee_rate = 0.02", "paper_fee_rate = 0.03")
            .replace("paper-assumption:flat-2pct-v1", "paper-assumption:test-v1")
        )
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "capture.toml"
            config.write_text(text, encoding="utf-8")
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--config", str(config)
                )
            snapshot = json.loads(stdout)["snapshot"]
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(
                (snapshot["fee_rate"], snapshot["fee_source"]),
                (0.03, "paper-assumption:test-v1"),
            )

            config.write_text("[runtime\nsecret='do-not-leak'", encoding="utf-8")
            with patch("chrysopoeia.cli.polymarket_fetch") as fetch:
                code, stdout, stderr = self.invoke(
                    "capture", "12345", "--config", str(config)
                )
            self.assertEqual((code, stdout), (2, ""))
            self.assertEqual(stderr, "capture failed: invalid configuration\n")
            fetch.assert_not_called()

            module = self.run_cli(
                "capture", "12345", "--config", str(config), cwd=directory
            )
            console = self.run_cli(
                "capture",
                "12345",
                "--config",
                str(config),
                cwd=directory,
                console=True,
            )
            self.assertEqual(module.returncode, 2)
            self.assertEqual(
                (module.stdout, module.stderr), (console.stdout, console.stderr)
            )

        secret = "private-response-body"
        with patch(
            "chrysopoeia.cli.load_market_snapshot",
            side_effect=PolymarketError(secret),
        ):
            code, stdout, stderr = self.invoke("capture", "12345")
        self.assertEqual((code, stdout), (2, ""))
        self.assertEqual(stderr, "capture failed: market data unavailable\n")
        self.assertNotIn(secret, stderr)
        self.assertNotIn("Traceback", stderr)

        with patch(
            "chrysopoeia.cli.load_market_snapshot", side_effect=RuntimeError(secret)
        ):
            code, stdout, stderr = self.invoke("capture", "12345")
        self.assertEqual((code, stdout), (2, ""))
        self.assertEqual(stderr, "capture failed: market data unavailable\n")
        self.assertNotIn(secret, stderr)

    def test_capture_default_config_is_cwd_independent(self) -> None:
        previous = Path.cwd()
        try:
            with (
                tempfile.TemporaryDirectory() as directory,
                patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()),
            ):
                os.chdir(directory)
                first = self.invoke("capture", "12345")
            with patch("chrysopoeia.cli.polymarket_fetch", self.fixture_fetch()):
                second = self.invoke("capture", "12345")
        finally:
            os.chdir(previous)

        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(second[0], 0, second[2])
        self.assertEqual(json.loads(first[1])["snapshot"]["market_id"], "12345")
        self.assertEqual(set(json.loads(first[1])), set(json.loads(second[1])))

    def test_import_has_no_runtime_or_provider_side_effects(self) -> None:
        code = (
            "import json, sys; import chrysopoeia.cli; "
            "blocked=('google.adk', 'chrysopoeia.agent', "
            "'dotenv', 'google.genai'); "
            "print(json.dumps([n for n in sys.modules if n in blocked or "
            "n.startswith('google.adk.')]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_cycle_runs_from_capture_without_market_fetch_and_emits_exact_result(
        self,
    ) -> None:
        from chrysopoeia.trading import BookLevel, market_snapshot_identity

        snapshot = MarketSnapshot(
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
            asks=(BookLevel(0.4, 20),),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )
        snapshot = replace(snapshot, snapshot_id=market_snapshot_identity(snapshot))
        result = {
            "schema_version": 1,
            "record_type": "paper_cycle_result",
            "snapshot_id": snapshot.snapshot_id,
            "market_id": "12345",
            "status": "abstained",
            "reason": "trader_abstained",
            "trader_called": True,
            "reviewer_called": False,
            "fill": None,
            "ledger_statuses": ["completed"],
            "actual_estimated_cost_usd": "0.000032",
            "maximum_reserved_cost_usd": "0.022528",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            output = Path(directory) / "result.json"
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ) as run,
                patch("chrysopoeia.cli.polymarket_fetch") as fetch,
            ):
                code, stdout, stderr = self.invoke(
                    "cycle",
                    "--snapshot",
                    str(source),
                    "--market-exposure",
                    "2",
                    "--total-exposure",
                    "3",
                    "--output",
                    str(output),
                )
            written = output.read_bytes()

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            stdout, json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
        )
        self.assertEqual(written, stdout.encode())
        fetch.assert_not_called()
        operating = run.call_args.args[2]
        snapshot_arg = run.call_args.args[1]
        self.assertEqual(
            (snapshot_arg.market_exposure, snapshot_arg.total_exposure), (2, 3)
        )
        self.assertEqual(operating.trader_agents, 1)

    def test_cycle_failures_are_sanitized_and_leave_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "bad.json"
            bad.write_text('{"secret":"model rationale"}')
            output = root / "result.json"
            code, stdout, stderr = self.invoke(
                "cycle", "--snapshot", str(bad), "--output", str(output)
            )
            self.assertEqual(
                (code, stdout, stderr), (2, "", "cycle failed: invalid snapshot\n")
            )
            self.assertFalse(output.exists())

            code, stdout, stderr = self.invoke(
                "cycle", "--snapshot", str(bad), "--bankroll", "0"
            )
            self.assertEqual(
                (code, stdout, stderr),
                (2, "", "cycle failed: invalid operating configuration\n"),
            )

    def test_cycle_model_failure_leaves_no_output_or_private_error(self) -> None:
        from chrysopoeia.trading import BookLevel, market_snapshot_identity

        snapshot = MarketSnapshot(
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
            asks=(BookLevel(0.4, 20),),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )
        snapshot = replace(snapshot, snapshot_id=market_snapshot_identity(snapshot))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            output = root / "result.json"
            with patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(side_effect=RuntimeError("secret model response")),
            ):
                code, stdout, stderr = self.invoke(
                    "cycle", "--snapshot", str(source), "--output", str(output)
                )

            self.assertEqual(
                (code, stdout, stderr),
                (2, "", "cycle failed: model/workflow unavailable\n"),
            )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
