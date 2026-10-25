import asyncio
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from collections.abc import Awaitable, Callable
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest

from chrysopoeia.agent import app, build_agents, root_agent
from chrysopoeia.configuration import (
    ConfigurationError,
    HarnessConfig,
    load_harness_config,
)

VALID = {
    "session": {
        "bankroll": 1000,
        "maximum_loss": 100,
        "target_win_rate": 0.5,
        "window_minutes": 60,
        "max_cycles": 1,
        "cost_budget": "5",
        "interval_seconds": 300,
        "daily_cloud_cost_budget": 5,
    },
    "risk": {
        "maximum_market_exposure": 0.01,
        "maximum_total_exposure": 0.10,
        "market_exposure": 0,
        "total_exposure": 0,
    },
    "runtime": {"adapter": "adk", "mode": "paper"},
    "venue": {
        "adapter": "polymarket",
        "paper_fee_rate": 0.02,
        "paper_fee_source": "paper-assumption:flat-2pct-v1",
        "series": "btc-updown-5m",
    },
    "models": {
        "location": "us",
        "root": "gemini-3.5-flash",
        "context": "gemini-3.5-flash",
        "trader": "gemini-3.5-flash",
        "reviewer": "gemini-3.5-flash",
    },
    "cost": {
        "model": "gemini-3.5-flash",
        "input_usd_per_million_tokens": "1.65",
        "output_usd_per_million_tokens": "9.90",
        "maximum_input_tokens_per_call": 8192,
        "maximum_output_tokens_per_call": 3072,
        "maximum_model_calls_per_cycle": 12,
    },
}


class HarnessConfigurationTests(unittest.TestCase):
    def test_operating_settings_and_profiles_are_validated_before_runtime(self) -> None:
        config = HarnessConfig.from_mapping(VALID)
        self.assertEqual(config.session.cost_budget, Decimal("5"))
        self.assertEqual(config.operating.bankroll, 1000)
        self.assertEqual(config.risk.total_exposure, 0)
        self.assertFalse(config.history.enabled)
        self.assertFalse(config.context_learning.enabled)
        for table, key, invalid in (
            ("session", "bankroll", True),
            ("session", "bankroll", 0),
            ("session", "maximum_loss", 1001),
            ("session", "target_win_rate", 1.1),
            ("session", "window_minutes", math.inf),
            ("session", "max_cycles", 1001),
            ("session", "max_cycles", 1.5),
            ("session", "cost_budget", "NaN"),
            ("session", "cost_budget", "-1"),
            ("session", "interval_seconds", -1),
            ("session", "interval_seconds", 30),
            ("session", "daily_cloud_cost_budget", 0),
            ("risk", "maximum_market_exposure", 0.2),
            ("risk", "maximum_total_exposure", 2),
            ("risk", "market_exposure", 1),
            ("risk", "total_exposure", 1001),
            ("venue", "series", "unsupported"),
        ):
            value = {name: fields.copy() for name, fields in VALID.items()}
            value[table][key] = invalid
            with self.subTest(table=table, key=key), self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)
        for table in ("session", "risk"):
            value = {name: fields.copy() for name, fields in VALID.items()}
            del value[table]
            with self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)
        base = Path(__file__).parents[1] / "configs"
        btc = load_harness_config(base / "btc5m.toml")
        self.assertEqual((btc.venue.series, btc.session.interval_seconds), ("btc-updown-5m", 300))
        self.assertEqual(btc.session.max_cycles, 20)
        platform = load_harness_config(base / "platform.toml")
        self.assertEqual(platform.session.max_cycles, 2)
        self.assertEqual(platform.venue.series, "btc-updown-5m")
        self.assertFalse(platform.research.enabled)
        self.assertFalse(btc.research.enabled)
        self.assertTrue(platform.history.enabled)
        self.assertFalse(btc.history.enabled)
        self.assertTrue(platform.context_learning.enabled)
        self.assertFalse(btc.context_learning.enabled)
        self.assertEqual(platform.cost.maximum_output_tokens_per_call, 3072)
        self.assertEqual(btc.venue.forecast_offset_seconds, 120.0)
        self.assertTrue(btc.venue.window_baseline)
        self.assertTrue(platform.venue.window_baseline)
        for key, invalid in (
            ("forecast_offset_seconds", -1),
            ("forecast_offset_seconds", 300),
            ("forecast_offset_seconds", True),
            ("forecast_offset_seconds", "120"),
            ("window_baseline", "true"),
        ):
            value = {name: fields.copy() for name, fields in VALID.items()}
            value["venue"][key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)
        self.assertTrue(HarnessConfig.from_mapping(VALID).research.enabled)
        self.assertFalse(HarnessConfig.from_mapping(VALID).history.enabled)
        self.assertFalse(HarnessConfig.from_mapping(VALID).context_learning.enabled)
        for invalid in ({"enabled": "false"}, {"enabled": 0}, {}):
            value = {name: fields.copy() for name, fields in VALID.items()}
            value["history"] = invalid
            with self.subTest(history=invalid), self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)
        for invalid in ({"enabled": "false"}, {"enabled": 0}, {}):
            value = {name: fields.copy() for name, fields in VALID.items()}
            value["context_learning"] = invalid
            with self.subTest(context_learning=invalid), self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)
        for invalid in ({"enabled": "false"}, {"enabled": 0}, {}):
            value = {name: fields.copy() for name, fields in VALID.items()}
            value["research"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)
        with self.assertRaises(ConfigurationError):
            HarnessConfig.from_mapping({
                **{name: fields.copy() for name, fields in VALID.items()},
                "venue": {"adapter": "polymarket", "paper_fee_rate": 0.02,
                          "paper_fee_source": "paper-assumption:flat-2pct-v1"},
            })

    def test_context_learning_requires_a_thinking_sized_output_ceiling(self) -> None:
        from chrysopoeia.configuration import CONTEXT_LEARNING_OUTPUT_TOKEN_CEILING

        learning = {name: fields.copy() for name, fields in VALID.items()}
        learning["context_learning"] = {"enabled": True}
        learning["cost"]["maximum_output_tokens_per_call"] = 1024
        with self.assertRaises(ConfigurationError):
            HarnessConfig.from_mapping(learning)

        learning["cost"]["maximum_output_tokens_per_call"] = (
            CONTEXT_LEARNING_OUTPUT_TOKEN_CEILING
        )
        config = HarnessConfig.from_mapping(learning)

        self.assertTrue(config.context_learning.enabled)

    def test_valid_mapping_is_exact_immutable_configuration(self) -> None:
        config = HarnessConfig.from_mapping(VALID)

        self.assertEqual(config.runtime.adapter, "adk")
        self.assertEqual(config.venue.paper_fee_rate, 0.02)
        self.assertEqual(config.models.trader, "gemini-3.5-flash")
        self.assertEqual(config.models.location, "us")
        self.assertEqual(
            config.cost_policy,
            {
                "version": "project-estimate-2026-10-v1",
                "model": "gemini-3.5-flash",
                "input_usd_per_million_tokens": "1.65",
                "output_usd_per_million_tokens": "9.90",
                "maximum_input_tokens_per_call": 8192,
                "maximum_output_tokens_per_call": 3072,
                "maximum_model_calls_per_cycle": 12,
            },
        )
        self.assertEqual(config.cost.input_usd_per_million_tokens, Decimal("1.65"))
        with self.assertRaises(FrozenInstanceError):
            config.runtime.adapter = "other"

    def test_checked_in_toml_loads(self) -> None:
        config = load_harness_config(Path(__file__).parents[1] / "chrysopoeia.toml")
        self.assertEqual(config, HarnessConfig.from_mapping(VALID))

    def test_all_gemini_agents_use_vertex_us_without_initializing_a_client(self) -> None:
        agents = build_agents(HarnessConfig.from_mapping(VALID))

        for agent in agents.model_agents:
            self.assertIsInstance(agent.model, Gemini)
            self.assertEqual(
                agent.model.client_kwargs,
                {"vertexai": True, "location": "us"},
            )
            self.assertIsNone(agent.model.__dict__.get("api_client"))

    def test_malformed_toml_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.toml"
            path.write_text("[runtime\nadapter = 'adk'", encoding="utf-8")
            with self.assertRaises(ConfigurationError) as raised:
                load_harness_config(path)
        self.assertNotIn("runtime", str(raised.exception))

    def test_invalid_schema_and_values_fail_closed(self) -> None:
        cases = []
        for table, key in (
            ("runtime", "mode"),
            ("venue", "adapter"),
            ("models", "root"),
            ("cost", "model"),
            ("session", "bankroll"),
            ("risk", "market_exposure"),
        ):
            value = {name: fields.copy() for name, fields in VALID.items()}
            del value[table][key]
            cases.append(value)
        for table, key, value in (
            ("top", "api_key", "secret"),
            ("runtime", "project", "secret-project"),
            ("venue", "wallet", "secret-wallet"),
            ("models", "project", "secret-project"),
            ("cost", "daily_budget", "1"),
            ("session", "unknown", 1),
            ("risk", "unknown", 1),
        ):
            candidate = {name: fields.copy() for name, fields in VALID.items()}
            (candidate if table == "top" else candidate[table])[key] = value
            cases.append(candidate)
        for table, key, value in (
            ("runtime", "adapter", "other"),
            ("runtime", "mode", "live"),
            ("venue", "adapter", "other"),
            ("venue", "paper_fee_rate", True),
            ("venue", "paper_fee_rate", math.inf),
            ("venue", "paper_fee_rate", -0.1),
            ("venue", "paper_fee_rate", 1.0),
            ("venue", "paper_fee_source", " "),
            ("models", "trader", ""),
            ("models", "location", " us"),
            ("cost", "input_usd_per_million_tokens", "NaN"),
            ("cost", "input_usd_per_million_tokens", " 1"),
            ("cost", "output_usd_per_million_tokens", "-1"),
            ("cost", "maximum_input_tokens_per_call", True),
            ("cost", "maximum_output_tokens_per_call", 0),
            ("cost", "maximum_model_calls_per_cycle", 100_000_001),
        ):
            candidate = {name: fields.copy() for name, fields in VALID.items()}
            candidate[table][key] = value
            cases.append(candidate)
        mixed = {name: fields.copy() for name, fields in VALID.items()}
        mixed["models"]["reviewer"] = "another-adk-model"
        cases.append(mixed)
        no_fee_lie = {name: fields.copy() for name, fields in VALID.items()}
        no_fee_lie["venue"]["paper_fee_source"] = "paper-assumption:no-fee-v1"
        cases.append(no_fee_lie)

        for value in cases:
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                HarnessConfig.from_mapping(value)

    def test_independent_agent_sets_use_their_own_models_and_cost_policies(
        self,
    ) -> None:
        first_mapping = {name: fields.copy() for name, fields in VALID.items()}
        second_mapping = {name: fields.copy() for name, fields in VALID.items()}
        second_mapping["venue"]["paper_fee_rate"] = 0.03
        second_mapping["venue"]["paper_fee_source"] = "paper-assumption:test-v1"
        for mapping, model in (
            (first_mapping, "gemini-first-model"),
            (second_mapping, "gemini-second-model"),
        ):
            mapping["cost"]["model"] = model
            for role in ("root", "context", "trader", "reviewer"):
                mapping["models"][role] = model
        first = build_agents(HarnessConfig.from_mapping(first_mapping))
        second = build_agents(HarnessConfig.from_mapping(second_mapping))

        self.assertEqual(
            [agent.model.model for agent in first.model_agents], ["gemini-first-model"] * 4
        )
        self.assertEqual(
            [agent.model.model for agent in second.model_agents], ["gemini-second-model"] * 4
        )
        for agents, model in ((first, "gemini-first-model"), (second, "gemini-second-model")):
            callbacks = [agent.before_model_callback for agent in agents.model_agents]
            self.assertTrue(all(callback is callbacks[0] for callback in callbacks))
            self.assertEqual(callbacks[0].keywords["default_policy"]["model"], model)
        first_state: dict[str, object] = {}
        second_state: dict[str, object] = {}
        first.configure_operation(SimpleNamespace(state=first_state))
        second.configure_operation(SimpleNamespace(state=second_state))
        self.assertEqual(first_state["model_cost_policy"]["model"], "gemini-first-model")
        self.assertEqual(second_state["model_cost_policy"]["model"], "gemini-second-model")
        first_state["model_cost_policy"]["model"] = "mutated"
        self.assertEqual(second_state["model_cost_policy"]["model"], "gemini-second-model")
        second_state["market_snapshot"] = {}
        with patch(
            "chrysopoeia.agent.load_market_snapshot", side_effect=ValueError
        ) as load:
            with self.assertRaises(ValueError):
                second.capture_market_snapshot(
                    "12345", SimpleNamespace(state=second_state)
                )
        self.assertEqual(
            load.call_args.kwargs,
            {
                "paper_fee_rate": 0.03,
                "paper_fee_source": "paper-assumption:test-v1",
                "include_no_book": True,
            },
        )

    def test_alternate_toml_controls_every_bound_runtime_value(self) -> None:
        from tests.eval import paper_cycle_evaluation as evaluation

        default_model = root_agent.model.model
        text = (Path(__file__).parents[1] / "chrysopoeia.toml").read_text()
        text = (
            text.replace("gemini-3.5-flash", "gemini-alternate-model")
            .replace("paper_fee_rate = 0.02", "paper_fee_rate = 0.03")
            .replace("paper-assumption:flat-2pct-v1", "paper-assumption:alternate-v1")
            .replace(
                'input_usd_per_million_tokens = "1.65"',
                'input_usd_per_million_tokens = "7"',
            )
            .replace(
                'output_usd_per_million_tokens = "9.90"',
                'output_usd_per_million_tokens = "11"',
            )
            .replace(
                "maximum_input_tokens_per_call = 8192",
                "maximum_input_tokens_per_call = 321",
            )
            .replace(
                "maximum_output_tokens_per_call = 3072",
                "maximum_output_tokens_per_call = 123",
            )
            .replace(
                "maximum_model_calls_per_cycle = 12",
                "maximum_model_calls_per_cycle = 4",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alternate.toml"
            path.write_text(text)
            config = load_harness_config(path)
        agents = build_agents(config)

        state: dict[str, object] = {}
        callback_context = SimpleNamespace(
            state=state, agent_name="chrysopoeia", invocation_id="alternate"
        )
        callback = cast(
            Callable[[object, LlmRequest], Awaitable[object]],
            agents.root_agent.before_model_callback,
        )
        self.assertIsNone(
            asyncio.run(callback(callback_context, LlmRequest(model="gemini-alternate-model")))
        )
        record = state["model_cost_ledger"][0]
        self.assertEqual(
            (
                record["model"],
                record["input_token_ceiling"],
                record["output_token_ceiling"],
                record["input_usd_per_million_tokens"],
                record["output_usd_per_million_tokens"],
            ),
            ("gemini-alternate-model", 321, 123, "7", "11"),
        )
        operation_state: dict[str, object] = {}
        agents.configure_operation(SimpleNamespace(state=operation_state))
        self.assertEqual(operation_state["model_cost_policy"], config.cost_policy)
        self.assertEqual(
            [agent.model.model for agent in agents.model_agents], ["gemini-alternate-model"] * 4
        )
        self.assertEqual(
            evaluation.reserved_ceiling(config, model_calls=2),
            Decimal("0.0072"),
        )
        with patch(
            "chrysopoeia.agent.load_market_snapshot", side_effect=ValueError
        ) as load:
            with self.assertRaises(ValueError):
                agents.capture_market_snapshot(
                    "12345", SimpleNamespace(state=operation_state)
                )
        self.assertEqual(
            load.call_args.kwargs,
            {
                "paper_fee_rate": 0.03,
                "paper_fee_source": "paper-assumption:alternate-v1",
                "include_no_book": True,
            },
        )
        self.assertEqual(root_agent.model.model, default_model)

    def test_default_exports_use_checked_in_configuration_outside_cwd(self) -> None:
        self.assertIs(app.root_agent, root_agent)
        self.assertEqual(root_agent.model.model, "gemini-3.5-flash")
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import chrysopoeia.agent as a; print(a.root_agent.model.model)",
                ],
                cwd=directory,
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.stdout.strip(), "gemini-3.5-flash")

    def test_configuration_boundary_does_not_import_adk(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, sys; import chrysopoeia.configuration; "
                "print(json.dumps([n for n in sys.modules if n == 'google.adk' or n.startswith('google.adk.')]))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), [])


class ModelAdapterTests(unittest.TestCase):
    def multi_model(self, **overrides: object) -> dict[str, object]:
        mapping: dict[str, object] = json.loads(json.dumps(VALID))
        models = mapping["models"]  # type: ignore[index]
        assert isinstance(models, dict)
        cost = mapping["cost"]  # type: ignore[index]
        assert isinstance(cost, dict)
        models["adapter"] = "adk-registry"
        models["trader"] = "ollama/llama3.1:8b"
        cost["models"] = {
            "gemini-3.5-flash": {
                "input_usd_per_million_tokens": "1.65",
                "output_usd_per_million_tokens": "9.90",
            },
            "ollama/llama3.1:8b": {
                "input_usd_per_million_tokens": "0",
                "output_usd_per_million_tokens": "0",
            },
        }
        assert isinstance(mapping, dict)
        deep = mapping
        return deep if not overrides else json.loads(json.dumps(deep))

    def test_registry_adapter_accepts_per_model_pricing(self) -> None:
        config = HarnessConfig.from_mapping(self.multi_model())
        self.assertEqual(config.models.adapter, "adk-registry")
        self.assertEqual(
            {
                (price.model, price.input_usd_per_million_tokens)
                for price in config.cost.prices
            },
            {
                ("gemini-3.5-flash", Decimal("1.65")),
                ("ollama/llama3.1:8b", Decimal("0")),
            },
        )
        self.assertEqual(
            config.cost_policy["models"],
            {  # type: ignore[typeddict-item]
                "gemini-3.5-flash": {
                    "input_usd_per_million_tokens": "1.65",
                    "output_usd_per_million_tokens": "9.90",
                },
                "ollama/llama3.1:8b": {
                    "input_usd_per_million_tokens": "0",
                    "output_usd_per_million_tokens": "0",
                },
            },
        )

    def test_registry_adapter_accepts_non_gemini_context(self) -> None:
        value = self.multi_model()
        models = value["models"]  # type: ignore[index]
        cost = value["cost"]  # type: ignore[index]
        assert isinstance(models, dict) and isinstance(cost, dict)
        models["context"] = "openrouter/openai/gpt-4.1-mini"
        cost["models"]["openrouter/openai/gpt-4.1-mini"] = {
            "input_usd_per_million_tokens": "0.40",
            "output_usd_per_million_tokens": "1.60",
        }
        config = HarnessConfig.from_mapping(value)
        self.assertEqual(config.models.context, "openrouter/openai/gpt-4.1-mini")

    def test_bundled_openrouter_config_is_valid(self) -> None:
        path = Path(__file__).parents[1] / "configs" / "openrouter.toml"
        config = load_harness_config(path)
        self.assertEqual(config.models.adapter, "adk-registry")
        self.assertTrue(config.models.context.startswith("openrouter/"))

    def test_unpriced_configured_model_is_rejected(self) -> None:
        value = self.multi_model()
        models = value["models"]  # type: ignore[index]
        assert isinstance(models, dict)
        models["trader"] = "ollama/other:1b"
        with self.assertRaises(ConfigurationError):
            HarnessConfig.from_mapping(value)

    def test_unconfigured_priced_model_is_rejected(self) -> None:
        value = self.multi_model()
        cost = value["cost"]  # type: ignore[index]
        assert isinstance(cost, dict)
        cost["models"]["gpt-4o"] = {
            "input_usd_per_million_tokens": "1",
            "output_usd_per_million_tokens": "1",
        }
        with self.assertRaises(ConfigurationError):
            HarnessConfig.from_mapping(value)

    def test_unsupported_adapters_are_rejected(self) -> None:
        value = self.multi_model()
        models = value["models"]  # type: ignore[index]
        assert isinstance(models, dict)
        models["adapter"] = "litellm-plugin"
        with self.assertRaises(ConfigurationError):
            HarnessConfig.from_mapping(value)

    def test_gemini_adapter_defaults_from_flat_configuration(self) -> None:
        value = {name: fields.copy() for name, fields in VALID.items()}
        del value["models"]["location"]
        config = HarnessConfig.from_mapping(value)
        self.assertEqual(config.models.adapter, "adk-gemini")
        self.assertEqual(config.models.location, "us")
        self.assertEqual(len(config.cost.prices), 1)

    def test_config_path_env_override_wins_over_repo_default(self) -> None:
        from pathlib import Path

        from chrysopoeia.cli import DEFAULT_CONFIG_ENV, default_config_path

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cfg.toml"
            target.write_text("[runtime]\nadapter = 'adk'\nmode = 'paper'\n")
            with unittest.mock.patch.dict(
                os.environ, {DEFAULT_CONFIG_ENV: str(target)}
            ):
                self.assertEqual(default_config_path(), target)
        # the repo default still resolves when the override is absent
        self.assertIn("chrysopoeia.toml", str(default_config_path()))


if __name__ == "__main__":
    unittest.main()
