import copy
import math
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions.state import State
from google.genai import types

from chrysopoeia.agent import DEFAULT_HARNESS_CONFIG, configure_operation, context_agent, reviewer_agent, root_agent, trader_agent
from chrysopoeia.cost import CostPolicy, after_model_cost, before_model_cost, configured_before_model_cost, on_model_cost_error
from chrysopoeia.cost import release_model_call, reserve_model_call, settle_model_call


NOW = datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc)


def configured_state(budget: float = 1.0) -> dict[str, object]:
    return {
        "operating_config": {
            "bankroll": 1_000, "trader_agents": 1, "maximum_market_exposure": 0.01,
            "maximum_total_exposure": 0.10, "maximum_loss": 100, "daily_cloud_cost_budget": budget,
        },
        "cycle_id": "cycle-1",
        "model_cost_policy": {
            "version": "test-v1", "model": "gemini-flash-latest",
            "input_usd_per_million_tokens": "1", "output_usd_per_million_tokens": "2",
            "maximum_input_tokens_per_call": 100, "maximum_output_tokens_per_call": 50,
            "maximum_model_calls_per_cycle": 2,
        },
    }


async def configured_before(context: object, request: LlmRequest, *, now: datetime = NOW):
    callback = configured_before_model_cost(configured_state()["model_cost_policy"])
    return await callback(context, request, now=now)


def context(state: object, invocation: str = "invocation-1", agent: str = "paper_market_trader") -> SimpleNamespace:
    return SimpleNamespace(state=state, agent_name=agent, invocation_id=invocation)


def usage(input_tokens: int = 25, output_tokens: int = 10) -> LlmResponse:
    return LlmResponse(usage_metadata=types.GenerateContentResponseUsageMetadata(
        prompt_token_count=input_tokens, candidates_token_count=output_tokens,
    ))


class RoundTripState(dict[str, object]):
    def __setitem__(self, key: str, value: object) -> None:
        super().__setitem__(key, copy.deepcopy(value))


class ModelCostLedgerTests(unittest.TestCase):
    def test_reservation_settlement_uses_explicit_reserved_prices(self) -> None:
        state = configured_state()
        reserved = reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 100, 50, "call-1", NOW)
        state["model_cost_policy"] = {**state["model_cost_policy"], "input_usd_per_million_tokens": "999"}
        completed = settle_model_call(state, "call-1", 25, 10)
        self.assertEqual(reserved["estimated_reserved_usd"], "0.0002")
        self.assertEqual(completed["actual_cost_usd"], "0.000045")
        self.assertEqual(completed["status"], "completed")

    def test_call_cycle_and_daily_limits_deny_before_reservation(self) -> None:
        for input_tokens, output_tokens, budget, message in (
            (101, 50, 1.0, "input token"), (100, 51, 1.0, "output token"),
            (100, 50, 0.0001, "daily model cost budget"),
        ):
            state = configured_state(budget)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", input_tokens, output_tokens, "call-1", NOW)
            self.assertNotIn("model_cost_ledger", state)
        state = configured_state()
        for number in (1, 2):
            reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 1, 1, f"call-{number}", NOW)
        with self.assertRaisesRegex(ValueError, "cycle model-call"):
            reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 1, 1, "call-3", NOW)

    def test_daily_budget_aggregates_cycles_and_rolls_over_at_utc_date(self) -> None:
        state = configured_state(0.0003)
        reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 100, 50, "call-1", NOW)
        settle_model_call(state, "call-1", 100, 50)
        state["cycle_id"] = "cycle-2"
        with self.assertRaisesRegex(ValueError, "daily model cost budget"):
            reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 100, 50, "call-2", NOW)
        tomorrow = datetime(2026, 8, 21, tzinfo=timezone.utc)
        self.assertEqual(reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 100, 50, "call-2", tomorrow)["date"], "2026-08-21")

    def test_finalization_overage_and_malformed_state_fail_closed(self) -> None:
        state = configured_state()
        reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 100, 50, "call-1", NOW)
        self.assertEqual(release_model_call(state, "call-1")["status"], "released")
        with self.assertRaises(ValueError):
            release_model_call(state, "call-1")
        state = configured_state()
        reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 100, 50, "call-1", NOW)
        with self.assertRaisesRegex(ValueError, "exceeded"):
            settle_model_call(state, "call-1", 101, 1)
        self.assertEqual(state["model_cost_ledger"][0]["status"], "violation")
        for invalid in (-1, True, math.inf):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                CostPolicy.from_mapping({**configured_state()["model_cost_policy"], "input_usd_per_million_tokens": invalid})
        malformed = configured_state()
        malformed["model_cost_ledger"] = [{"unexpected": "record"}]
        with self.assertRaisesRegex(ValueError, "ledger"):
            reserve_model_call(malformed, "chrysopoeia", "gemini-flash-latest", 1, 1, "call-2", NOW)


class ModelCostCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_policy_allows_exactly_one_root_bootstrap_call(self) -> None:
        state: dict[str, object] = {}
        callback = configured_before_model_cost(DEFAULT_HARNESS_CONFIG.cost_policy)

        self.assertIsNone(
            await callback(
                context(state, agent="chrysopoeia"),
                LlmRequest(model=DEFAULT_HARNESS_CONFIG.models.root),
                now=NOW,
            )
        )
        record = state["model_cost_ledger"][0]
        self.assertEqual(record["estimated_reserved_usd"], "0.011264")
        self.assertEqual(record["date"], "2026-08-20")
        self.assertNotIn("operating_config", state)
        denied = await callback(
            context(state, "invocation-2", "chrysopoeia"),
            LlmRequest(model=DEFAULT_HARNESS_CONFIG.models.root),
            now=NOW,
        )
        self.assertEqual(denied.error_code, "MODEL_COST_POLICY_DENIED")

    async def test_before_callback_denies_unhashable_ledger_status(self) -> None:
        state = configured_state()
        reserve_model_call(state, "chrysopoeia", "gemini-flash-latest", 1, 1, "call-1", NOW)
        state["model_cost_ledger"][0]["status"] = []

        denied = await configured_before(context(state), LlmRequest(model="gemini-flash-latest"))

        self.assertEqual(denied.error_code, "MODEL_COST_POLICY_DENIED")
        self.assertEqual(denied.error_message, "Model call denied: model cost ledger is invalid.")

    async def test_reservation_settles_after_adk_state_round_trip(self) -> None:
        state = RoundTripState(configured_state())
        callback = context(state, "invocation-copy")
        self.assertIsNone(await configured_before(callback, LlmRequest(model="gemini-flash-latest")))
        persisted = copy.deepcopy(dict(state))
        self.assertIsNone(await after_model_cost(context(persisted, "invocation-copy"), usage()))
        self.assertEqual(persisted["model_cost_ledger"][0]["status"], "completed")
        delta: dict[str, object] = {}
        adk_state = State(configured_state(), delta)
        self.assertIsNone(await configured_before(context(adk_state, "invocation-adk"), LlmRequest(model="gemini-flash-latest")))
        self.assertIn("model_cost_ledger", delta)

    async def test_bootstrap_is_root_only_bounded_and_not_operating_config(self) -> None:
        state: dict[str, object] = {}
        self.assertIsNone(await configured_before(context(state, agent="chrysopoeia"), LlmRequest(model="gemini-flash-latest")))
        self.assertNotIn("operating_config", state)
        self.assertEqual(state["model_cost_ledger"][0]["cycle_id"], "bootstrap:invocation-1")
        for callback in (context({}, agent="paper_market_trader"), context(state, "invocation-2", "chrysopoeia")):
            denied = await configured_before(callback, LlmRequest(model="gemini-flash-latest"))
            self.assertEqual(denied.error_code, "MODEL_COST_POLICY_DENIED")

    async def test_callbacks_deny_limits_settle_and_release_provider_error(self) -> None:
        state = configured_state()
        request = LlmRequest(model="gemini-flash-latest")
        self.assertIsNone(await configured_before(context(state), request))
        self.assertEqual(request.config.max_output_tokens, 50)
        self.assertIsNone(await after_model_cost(context(state), usage()))
        self.assertEqual(state["model_cost_ledger"][0]["status"], "completed")
        denied_state = configured_state(0)
        denied = await configured_before(context(denied_state), LlmRequest(model="gemini-flash-latest"))
        self.assertEqual(denied.error_code, "MODEL_COST_POLICY_DENIED")
        self.assertNotIn("model_cost_ledger", denied_state)
        error_state = configured_state()
        await configured_before(context(error_state), LlmRequest(model="gemini-flash-latest"))
        self.assertIsNone(await on_model_cost_error(context(error_state), LlmRequest(), RuntimeError("secret")))
        self.assertEqual(error_state["model_cost_ledger"][0]["status"], "released")

    async def test_missing_bad_and_excess_usage_are_conservative_violations(self) -> None:
        responses = (LlmResponse(), usage(-1, 1), usage(101, 1))
        for number, response in enumerate(responses):
            state = configured_state()
            callback = context(state, f"invocation-{number}")
            await configured_before(callback, LlmRequest(model="gemini-flash-latest"))
            denied = await after_model_cost(callback, response)
            record = state["model_cost_ledger"][0]
            self.assertEqual(denied.error_code, "MODEL_COST_USAGE_INVALID")
            self.assertEqual(record["status"], "violation")
            if number < 2:
                self.assertEqual(record["actual_cost_usd"], record["estimated_reserved_usd"])

    def test_all_model_agents_are_gated_and_configuration_installs_default_policy(self) -> None:
        for agent in (root_agent, trader_agent, reviewer_agent, context_agent):
            self.assertEqual(agent.before_model_callback.func, before_model_cost)
            self.assertIs(agent.after_model_callback, after_model_cost)
            self.assertIs(agent.on_model_error_callback, on_model_cost_error)
            self.assertFalse(any("cost_policy" in str(tool).lower() for tool in agent.tools))
        state: dict[str, object] = {}
        configure_operation(SimpleNamespace(state=state))
        self.assertIn("operating_config", state)
        self.assertEqual(state["model_cost_policy"]["version"], "project-estimate-2026-08-v1")


if __name__ == "__main__":
    unittest.main()
