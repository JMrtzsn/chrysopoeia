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
from unittest.mock import AsyncMock, Mock, call, patch

from chrysopoeia import cli
from chrysopoeia.accounting import cycle_turn_id
from chrysopoeia.polymarket import PolymarketError
from chrysopoeia.trading import (
    BookLevel,
    ExitPlan,
    MarketSnapshot,
    market_snapshot_identity,
)
from tests.test_configuration import VALID

ROOT = Path(__file__).parents[1]
EXPECTED = {
    "command": "inspect",
    "config_path": "chrysopoeia.toml",
    "cost_policy": {
        "input_usd_per_million_tokens": "1.65",
        "maximum_input_tokens_per_call": 8192,
        "maximum_model_calls_per_cycle": 12,
        "maximum_output_tokens_per_call": 3072,
        "model": "gemini-3.5-flash",
        "output_usd_per_million_tokens": "9.90",
        "version": "project-estimate-2026-10-v1",
    },
    "models": {
        "context": "gemini-3.5-flash",
        "location": "us",
        "reviewer": "gemini-3.5-flash",
        "root": "gemini-3.5-flash",
        "trader": "gemini-3.5-flash",
    },
    "runtime": {"adapter": "adk", "mode": "paper"},
    "research": {"enabled": True},
    "history": {"enabled": False},
    "context_learning": {"enabled": False},
    "session": VALID["session"],
    "risk": VALID["risk"],
    "schema_version": 1,
    "valid": True,
    "venue": {
        "adapter": "polymarket",
        "execution": "paper-only",
        "market_data": "public-read-only",
        "paper_fee_rate": 0.02,
        "paper_fee_source": "paper-assumption:flat-2pct-v1",
        "series": "btc-updown-5m",
        "forecast_offset_seconds": 0.0,
        "window_baseline": False,
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

    def test_cycle_accepts_market_context_draft_or_no_target(self) -> None:
        result = {
            "schema_version": 1, "record_type": "paper_cycle_result",
            "snapshot_id": "", "market_id": "", "status": "abstained",
            "reason": "no_target", "trader_called": True, "reviewer_called": False,
            "fill": None, "event": None, "ledger_statuses": ["completed"],
            "actual_estimated_cost_usd": "0", "maximum_reserved_cost_usd": "0.2838528",
        }
        snapshot = MarketSnapshot("snapshot", "12345", 0.4, 1_000, 0, 0)
        with (
            patch("chrysopoeia.cli.load_market_snapshot", return_value=snapshot),
            patch("chrysopoeia.cycle_runner.run_paper_cycle", AsyncMock(return_value=result)) as run,
        ):
            for arguments in (
                ("--market", "12345"),
                ("--context", "weather only"),
                ("--draft", '{"action":"abstain"}'),
                (),
            ):
                with self.subTest(arguments=arguments):
                    code, _stdout, stderr = self.invoke("cycle", *arguments)
                    self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(run.await_count, 4)

    def test_cycle_rejects_conflicting_targets_and_bad_bounded_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.json"
            source.write_text("{}")
            for arguments in (
                ("--snapshot", str(source), "--market", "123"),
                ("--context", "x" * 2001),
                ("--draft", "[]"),
            ):
                with self.subTest(arguments=arguments):
                    code, _stdout, _stderr = self.invoke("cycle", *arguments)
                    self.assertEqual(code, 2)

    def test_cycle_with_journal_requires_a_target_before_admission(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "chrysopoeia.operations.run_journal_turn", AsyncMock()
        ) as run:
            code, stdout, stderr = self.invoke("cycle", "--journal", directory)

        self.assertEqual((code, stdout), (2, ""))
        self.assertEqual(stderr, "cycle failed: --journal requires --snapshot or --market\n")
        run.assert_not_called()

    def test_cycle_rejects_unknown_nested_draft_fields(self) -> None:
        code, stdout, stderr = self.invoke(
            "cycle", "--draft", '{"exit_plan":{"api_key":"secret"}}'
        )

        self.assertEqual((code, stdout), (2, ""))
        self.assertEqual(stderr, "cycle failed: invalid context or draft\n")

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
            if "token_id=no-token" in url:
                value = {**book, "asset_id": "no-token"}
            return json.dumps(value).encode()

        return fetch

    def test_operating_flags_are_rejected_without_running_models(self) -> None:
        invalid = (
            ("--bankroll", "0"),
            ("--maximum-loss", "nan"),
            ("--target-win-rate", "1.1"),
            ("--window-minutes", "0"),
            ("--max-cycles", "0"),
            ("--max-cycles", "1001"),
            ("--cost-budget", "-1"),
            ("--interval-seconds", "-1"),
            ("--maximum-market-exposure", "0"),
            ("--maximum-total-exposure", "2"),
            ("--daily-cloud-cost-budget", "0"),
            ("--series", "btc-updown-5m"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for flag, value in invalid:
                with self.subTest(flag=flag, value=value):
                    code, output, error = self.invoke(
                        "run",
                        "--journal",
                        directory,
                        flag,
                        value,
                    )
                    self.assertEqual((code, output), (2, ""))
                    self.assertIn("unrecognized arguments", error)

    def test_run_command_prints_iteration_lines_and_session_report(self) -> None:
        report = {"stop_reason": "max_cycles", "cycles_run": 1}
        iterations = [{"iteration": 1, "result": {"status": "abstained"}}]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "chrysopoeia.loop.run_loop",
                AsyncMock(return_value=(report, iterations)),
            ) as run,
        ):
            code, output, error = self.invoke(
                "run", "--journal", directory
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), report)
        self.assertEqual(json.loads(error), iterations[0])
        self.assertEqual(run.call_args.args[0].interval_seconds, 300)
        self.assertEqual(run.call_args.args[0].max_cycles, 1)

    def test_configured_zero_budget_stops_before_market_or_model_calls(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("chrysopoeia.loop.discover_markets") as discover,
            patch("chrysopoeia.cycle_runner.run_paper_cycle", AsyncMock()) as model,
        ):
            config = Path(directory) / "no-spend.toml"
            config.write_text((ROOT / "chrysopoeia.toml").read_text().replace(
                'cost_budget = "5"', 'cost_budget = "0"'
            ))
            code, output, error = self.invoke(
                "run", "--config", str(config), "--journal", str(Path(directory) / "journal")
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output)["stop_reason"], "cost_budget")
            discover.assert_not_called()
            model.assert_not_awaited()

    def test_run_rejects_configured_external_exposure_before_opening_a_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "exposed.toml"
            journal = Path(directory) / "journal"
            config.write_text((ROOT / "chrysopoeia.toml").read_text().replace(
                "\ntotal_exposure = 0", "\ntotal_exposure = 1"
            ))
            code, output, error = self.invoke("run", "--config", str(config), "--journal", str(journal))
            self.assertEqual((code, output), (2, ""))
            self.assertIn("run uses its journal", error)
            self.assertFalse(journal.exists())

    def test_run_uses_benchmark_config_and_rejects_invalid_cadence(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("chrysopoeia.loop.run_loop", AsyncMock(return_value=({}, []))) as run,
        ):
            args = (
                "run",
                "--journal",
                directory,
                "--config",
                str(ROOT / "configs" / "btc5m.toml"),
            )
            code, _, _ = self.invoke(*args)
            self.assertEqual(code, 0)
            self.assertEqual(run.call_args.args[0].series, "btc-updown-5m")
            self.assertEqual(run.call_args.args[0].interval_seconds, 300)
            self.assertEqual(run.call_args.args[0].max_cycles, 20)
            invalid = Path(directory) / "bad.toml"
            invalid.write_text((ROOT / "configs" / "btc5m.toml").read_text().replace(
                "interval_seconds = 300", "interval_seconds = 30"
            ))
            code, _, _ = self.invoke("run", "--journal", directory, "--config", str(invalid))
            self.assertEqual(code, 2)
            self.assertEqual(run.await_count, 1)

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
        self.assertEqual(json.loads(first.stdout)["session"]["daily_cloud_cost_budget"], 5)

    def test_default_is_cwd_independent_and_entry_points_are_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            module = self.run_cli("validate", "--json", cwd=directory)
            console = self.run_cli("validate", "--json", cwd=directory, console=True)

        self.assertEqual(module.returncode, 0, module.stderr)
        self.assertEqual(console.returncode, 0, console.stderr)
        self.assertEqual(module.stdout, console.stdout)

    def test_alternate_configuration_uses_supplied_relative_label(self) -> None:
        text = (ROOT / "chrysopoeia.toml").read_text(encoding="utf-8")
        text = text.replace("gemini-3.5-flash", "gemini-alternate-model").replace(
            'input_usd_per_million_tokens = "1.65"',
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
        self.assertEqual(summary["models"]["root"], "gemini-alternate-model")
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

    def test_discover_is_bound_to_configured_series_and_rejects_the_old_limit_flag(self) -> None:
        with patch("chrysopoeia.cli.discover_markets", return_value=()) as discover:
            code, stdout, stderr = self.invoke("discover")

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["candidates"], [])
        discover.assert_called_once_with(
            series="btc-updown-5m", fetch=cli.polymarket_fetch
        )

        for limit in ("1", "20", "0", "21", "1.0", "true"):
            with self.subTest(limit=limit):
                code, stdout, stderr = self.invoke("discover", "--limit", limit)
                self.assertEqual((code, stdout), (2, ""))
                self.assertIn("unrecognized arguments", stderr)

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
            code, stdout, stderr = self.invoke("discover")

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
                    "no_token_id", "no_asks", "no_bids", "no_book_captured_at",
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
            self.assertEqual(len(calls), 3)

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
            include_no_book=True,
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
            "maximum_reserved_cost_usd": "0.0473088",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            output = Path(directory) / "result.json"
            config = Path(directory) / "exposure.toml"
            config.write_text((ROOT / "chrysopoeia.toml").read_text().replace(
                "\nmarket_exposure = 0", "\nmarket_exposure = 2"
            ).replace("\ntotal_exposure = 0", "\ntotal_exposure = 3"))
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
                    "--config",
                    str(config),
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

    def cycle_fill_result(self) -> dict[str, object]:
        from chrysopoeia.paper_cycle import build_turn_outcome
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
        fill = {
            "price": 0.4,
            "amount": 4.0,
            "shares": 10.0,
            "fee": 0.08,
            "total_cost": 4.08,
            "levels_consumed": 1,
            "exit_plan": {
                "take_profit_roi": 0.1,
                "stop_loss_roi": -0.2,
                "exit_by": "2026-10-01T00:00:00+00:00",
                "hold_to_resolution": False,
            },
        }
        result = {
            "schema_version": 1,
            "record_type": "paper_cycle_result",
            "snapshot_id": snapshot.snapshot_id,
            "market_id": "12345",
            "status": "approved",
            "reason": "approved by review and deterministic risk policy",
            "trader_called": True,
            "reviewer_called": True,
            "fill": None,
            "event": {
                "schema_version": 1,
                "record_type": "trade_plan_ready",
                "event_id": cycle_turn_id(snapshot.snapshot_id, snapshot.market_id),
                "created_at": snapshot.captured_at,
                "market_id": snapshot.market_id,
                "snapshot_id": snapshot.snapshot_id,
                "instrument_id": snapshot.yes_token_id,
                "outcome": "YES",
                "probability": 0.46,
                "stake": fill["amount"],
                "max_entry_price": 0.41,
                "exit_plan": fill["exit_plan"],
                "reviewer_approved": True,
                "reviewer_citations": ["market_snapshot"],
                "policy_references": ["hard-policy-v1"],
                "evidence_references": ["market_snapshot"],
                "expires_at": snapshot.end_time,
                "market_end": snapshot.end_time,
            },
            "ledger_statuses": ["completed", "completed"],
            "actual_estimated_cost_usd": "0.000064",
            "maximum_reserved_cost_usd": "0.0473088",
        }
        result["outcome_event"] = build_turn_outcome(
            proposal={
                "snapshot_id": snapshot.snapshot_id, "market_id": snapshot.market_id,
                "action": "trade", "probability": 0.46, "amount": 4.0,
                "max_entry_price": 0.41, "exit_plan": fill["exit_plan"],
                "citations": ["market_snapshot"], "rationale": "Evidence supports a trade.",
            },
            review={
                "snapshot_id": snapshot.snapshot_id, "market_id": snapshot.market_id,
                "approved": True, "reason": "supported", "citations": ["market_snapshot"],
            },
            policy={"allowed": True, "reason": result["reason"]},
            status="plan_ready", reason=str(result["reason"]),
            created_at=snapshot.captured_at,
            trade_plan_event_id=result["event"]["event_id"],
            model_cost_usd=str(result["actual_estimated_cost_usd"]),
        )
        return snapshot, result

    def test_cycle_without_journal_returns_event_without_consuming_it(self) -> None:
        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ),
                patch("chrysopoeia.operations.consume_trade_plan") as consume,
            ):
                code, stdout, stderr = self.invoke("cycle", "--snapshot", str(source))

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["event"], result["event"])
        self.assertIsNone(json.loads(stdout)["fill"])
        consume.assert_not_called()

    def test_cycle_with_journal_records_fill_and_book_after(self) -> None:
        from chrysopoeia.accounting import journal_path, replay

        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            source = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            output = Path(directory) / "result.json"
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ),
                patch(
                    "chrysopoeia.operations.consume_trade_plan",
                    wraps=__import__("chrysopoeia.trading", fromlist=["consume_trade_plan"]).consume_trade_plan,
                ) as consume,
                patch("chrysopoeia.cli.polymarket_fetch"),
            ):
                code, stdout, stderr = self.invoke(
                    "cycle",
                    "--snapshot",
                    str(source),
                    "--journal",
                    str(journal),
                    "--output",
                    str(output),
                )
            self.assertEqual((code, stderr), (0, ""))
            reported = json.loads(stdout)
            consume.assert_called_once()
            self.assertEqual(reported["event"], result["event"])
            self.assertEqual(reported["fill"]["amount"], result["event"]["stake"])
            self.assertEqual(reported["book_after"]["open_positions"], 1)
            self.assertAlmostEqual(reported["book_after"]["open_exposure"], 4.08)
            self.assertEqual(reported["book_after"]["status"], "open")
            state = replay(journal)
            self.assertIn("12345", state.positions)
            position = state.positions["12345"]
            self.assertEqual(position.trade_plan.event_id, result["event"]["event_id"])
            self.assertEqual(position.trade_plan.stake, result["event"]["stake"])
            self.assertEqual(position.amount, reported["fill"]["amount"])
            self.assertEqual(len(state.admitted_turns), 1)
            self.assertEqual(set(state.finished_turns.values()), {"filled"})
            self.assertEqual(
                len(journal_path(journal).read_text().splitlines()),
                5,  # session_opened, turn_admitted, outcome, fill_recorded, turn_finished
            )

            before = journal_path(journal).read_bytes()
            with (
                patch("chrysopoeia.cycle_runner.run_paper_cycle", AsyncMock()) as run,
                patch("chrysopoeia.operations.consume_trade_plan") as consume_again,
            ):
                code, stdout, stderr = self.invoke(
                    "cycle", "--snapshot", str(source), "--journal", str(journal)
                )
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(json.loads(stdout), {"status": "filled"})
            self.assertEqual(journal_path(journal).read_bytes(), before)
            run.assert_not_called()
            consume_again.assert_not_called()

    def test_journal_cycle_forwards_draft_context_and_no_evidence_as_none(self) -> None:
        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            source = journal / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            with patch(
                "chrysopoeia.cycle_runner.run_paper_cycle", AsyncMock(return_value=result)
            ) as run:
                code, _stdout, stderr = self.invoke(
                    "cycle", "--snapshot", str(source), "--journal", str(journal),
                    "--context", "focus on liquidity", "--draft", '{"action":"abstain"}',
                )

        self.assertEqual((code, stderr), (0, ""))
        self.assertIsNone(run.call_args.kwargs["evidence"])
        self.assertEqual(run.call_args.kwargs["context"], "focus on liquidity")
        self.assertEqual(run.call_args.kwargs["draft"], {"action": "abstain"})

    def test_cycle_sink_acknowledges_success_and_keeps_failure_pending(self) -> None:
        from chrysopoeia.accounting import pending_events

        snapshot, result = self.cycle_fill_result()
        for failure in (None, RuntimeError("private payload")):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                journal = Path(directory)
                source = journal / "snapshot.json"
                source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
                sender = Mock(side_effect=failure)
                with (
                    patch.dict(
                        os.environ,
                        {"CHRYSOPOEIA_EVENT_SINK": "http://127.0.0.1:8080/push"},
                    ),
                    patch(
                        "chrysopoeia.cycle_runner.run_paper_cycle",
                        AsyncMock(return_value=result),
                    ),
                    patch("chrysopoeia.events.publish", sender),
                ):
                    code, stdout, stderr = self.invoke(
                        "cycle", "--snapshot", str(source), "--journal", str(journal)
                    )

                self.assertEqual(code, 0)
                self.assertEqual(json.loads(stdout)["status"], "filled")
                self.assertNotIn("private payload", stderr)
                self.assertEqual(
                    pending_events(journal),
                    [result["outcome_event"], result["event"]] if failure else [],
                )
                expected = [call("http://127.0.0.1:8080/push", result["outcome_event"])]
                if failure is None:
                    expected.append(call("http://127.0.0.1:8080/push", result["event"]))
                self.assertEqual(sender.call_args_list, expected)

    def test_cycle_with_journal_finishes_abstain_review_reject_and_risk_reject(
        self,
    ) -> None:
        from chrysopoeia.accounting import replay

        snapshot, result = self.cycle_fill_result()
        for status, reason in (
            ("abstained", "trader_abstained"),
            ("rejected", "review_rejected"),
            ("rejected", "maximum_market_exposure_exceeded"),
        ):
            with (
                self.subTest(reason=reason),
                tempfile.TemporaryDirectory() as directory,
            ):
                journal = Path(directory)
                source = journal / "snapshot.json"
                source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
                result = {
                    **result,
                    "status": status,
                    "reason": reason,
                    "fill": None,
                    "event": None,
                }
                self.assertIsInstance(result["outcome_event"], dict)
                outcome = {**result["outcome_event"]}
                outcome.update(
                    status=("abstained" if status == "abstained" else "reviewer_rejected" if reason == "review_rejected" else "policy_rejected"),
                    reason=reason,
                    trade_plan_event_id=None,
                    review=None if status == "abstained" else outcome["review"],
                    policy=None if status == "abstained" else {"allowed": False, "reason": reason},
                )
                if reason == "review_rejected":
                    outcome["review"] = {"approved": False, "reason": "rejected", "citations": []}
                elif status != "abstained":
                    outcome["review"] = {"approved": True, "reason": "supported", "citations": ["market_snapshot"]}
                result["outcome_event"] = outcome
                with patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ):
                    code, _stdout, stderr = self.invoke(
                        "cycle", "--snapshot", str(source), "--journal", str(journal)
                    )
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(set(replay(journal).finished_turns.values()), {status})

    def test_cycle_with_journal_finishes_invalid_evidence_and_model_failure(
        self,
    ) -> None:
        from chrysopoeia.accounting import replay

        snapshot, _result = self.cycle_fill_result()
        for failure in ("evidence", "model"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                journal = Path(directory)
                source = journal / "snapshot.json"
                source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
                arguments = [
                    "cycle",
                    "--snapshot",
                    str(source),
                    "--journal",
                    str(journal),
                ]
                if failure == "evidence":
                    evidence = journal / "evidence.json"
                    evidence.write_text("{}")
                    arguments.extend(("--evidence", str(evidence)))
                with patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(side_effect=RuntimeError("private")),
                ) as run:
                    code, _stdout, _stderr = self.invoke(*arguments)
                self.assertEqual(code, 2)
                self.assertEqual(
                    set(replay(journal).finished_turns.values()), {"failed"}
                )
                if failure == "evidence":
                    run.assert_not_called()
                    self.assertEqual(replay(journal).model_cost_usd, 0)

    def test_cycle_with_journal_finishes_failed_when_fill_is_refused(self) -> None:
        from chrysopoeia.accounting import replay

        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            source = journal / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ),
                patch(
                    "chrysopoeia.accounting.record_fill",
                    side_effect=ValueError("refused"),
                ),
            ):
                code, _stdout, stderr = self.invoke(
                    "cycle", "--snapshot", str(source), "--journal", str(journal)
                )
            self.assertEqual(code, 2)
            self.assertIn("journal workflow rejected", stderr)
            self.assertEqual(set(replay(journal).finished_turns.values()), {"failed"})

    def test_cycle_recovers_open_turns_before_admission_without_running_them(
        self,
    ) -> None:
        from chrysopoeia.accounting import admit_turn, open_session, replay

        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            open_session(journal, 1_000.0, 100.0)
            admit_turn(journal, "old-turn", "old-snapshot", "old-market")
            source = journal / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            with patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(return_value={**result, "status": "abstained", "fill": None}),
            ) as run:
                code, _stdout, stderr = self.invoke(
                    "cycle", "--snapshot", str(source), "--journal", str(journal)
                )
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(replay(journal).finished_turns["old-turn"], "abandoned")

    def test_cycle_repeat_of_finished_turn_reports_outcome_without_model_or_records(
        self,
    ) -> None:
        from chrysopoeia.accounting import (
            admit_turn,
            cycle_turn_id,
            finish_turn,
            journal_path,
            open_session,
        )

        snapshot, _result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            open_session(journal, 1_000.0, 100.0)
            turn_id = cycle_turn_id(snapshot.snapshot_id, snapshot.market_id)
            admit_turn(journal, turn_id, snapshot.snapshot_id, snapshot.market_id)
            finish_turn(journal, turn_id, "abstained")
            before = journal_path(journal).read_bytes()
            source = journal / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            with patch("chrysopoeia.cycle_runner.run_paper_cycle", AsyncMock()) as run:
                code, stdout, stderr = self.invoke(
                    "cycle", "--snapshot", str(source), "--journal", str(journal)
                )
            self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["status"], "abstained")
            self.assertEqual(journal_path(journal).read_bytes(), before)
            run.assert_not_called()

    def test_cycle_with_journal_refuses_same_market_position_before_operating(
        self,
    ) -> None:
        from chrysopoeia.accounting import Position as BookPosition
        from chrysopoeia.accounting import admit_turn, open_session, record_fill

        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            open_session(journal, 1_000.0, 100.0)
            admit_turn(journal, "existing", snapshot.snapshot_id, "12345")
            record_fill(
                journal,
                BookPosition(
                    market_id="12345",
                    snapshot_id=snapshot.snapshot_id,
                    entered_at="2026-09-15T00:00:00+00:00",
                    price=0.41,
                    amount=10.0,
                    shares=24.39,
                    fee=0.2,
                    total_cost=10.2,
                    exit_plan=ExitPlan(0.1, -0.2, "2026-10-01T00:00:00+00:00"),
                ),
                "existing",
            )
            source = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            output = Path(directory) / "result.json"
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ) as run,
                patch("chrysopoeia.cli.polymarket_fetch"),
            ):
                code, _stdout, stderr = self.invoke(
                    "cycle",
                    "--snapshot",
                    str(source),
                    "--journal",
                    str(journal),
                    "--output",
                    str(output),
                )
            self.assertEqual(code, 2)
            self.assertIn("open journal position", stderr)
            run.assert_not_called()
            self.assertFalse(output.exists())

    def test_cycle_with_journal_derives_total_exposure_from_book(self) -> None:
        from chrysopoeia.accounting import Position as BookPosition
        from chrysopoeia.accounting import admit_turn, open_session, record_fill

        snapshot, result = self.cycle_fill_result()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            open_session(journal, 1_000.0, 100.0)
            admit_turn(journal, "existing", snapshot.snapshot_id, "other-market")
            other = BookPosition(
                market_id="other-market",
                snapshot_id=snapshot.snapshot_id,
                entered_at="2026-09-15T00:00:00+00:00",
                price=0.5,
                amount=10.0,
                shares=20.0,
                fee=0.2,
                total_cost=10.2,
                exit_plan=ExitPlan(0.1, -0.2, "2026-10-01T00:00:00+00:00"),
            )
            record_fill(journal, other, "existing")
            source = Path(directory) / "snapshot.json"
            source.write_text(json.dumps(cli.serialize_market_snapshot(snapshot)))
            with (
                patch(
                    "chrysopoeia.cycle_runner.run_paper_cycle",
                    AsyncMock(return_value=result),
                ) as run,
                patch("chrysopoeia.cli.polymarket_fetch"),
            ):
                code, _stdout, stderr = self.invoke(
                    "cycle",
                    "--snapshot",
                    str(source),
                    "--journal",
                    str(journal),
                )
                self.assertEqual((code, stderr), (0, ""))
                snapshot_arg = run.call_args.args[1]
                self.assertEqual(snapshot_arg.total_exposure, 10.2)
                self.assertEqual(snapshot_arg.market_exposure, 0.0)

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

            config = root / "invalid.toml"
            config.write_text((ROOT / "chrysopoeia.toml").read_text().replace("bankroll = 1000", "bankroll = 0"))
            code, stdout, stderr = self.invoke("cycle", "--snapshot", str(bad), "--config", str(config))
            self.assertEqual(
                (code, stdout, stderr),
                (2, "", "cycle failed: model/workflow unavailable\n"),
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
