import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_import_has_no_runtime_or_provider_side_effects(self) -> None:
        code = (
            "import json, sys; import chrysopoeia.cli; "
            "blocked=('google.adk', 'chrysopoeia.agent', 'chrysopoeia.polymarket', "
            "'dotenv', 'google.genai'); "
            "print(json.dumps([n for n in sys.modules if n in blocked or "
            "n.startswith('google.adk.')]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
    unittest.main()
