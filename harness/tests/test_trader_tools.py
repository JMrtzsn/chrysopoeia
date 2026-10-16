import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import patch

from chrysopoeia import paper_cycle
from chrysopoeia.agent import (
    analyze_crypto_history,
    analyze_stock_history,
    build_agents,
    build_trader_tools,
)
from chrysopoeia.configuration import load_harness_config
from chrysopoeia.financial_analysis import Candle
from chrysopoeia.paper_cycle import LAST_SUCCESSFUL_PLAN_KEY, PLAN_CHECKS_KEY
from chrysopoeia.polymarket import MarketCandidate
from chrysopoeia.trading import BookLevel, MarketSnapshot, OperatingConfig


class TraderToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_harness_config(__import__("pathlib").Path(__file__).parents[1] / "chrysopoeia.toml")
        self.snapshot = MarketSnapshot(
            "snapshot", "123", 0.4, 1_000, 0, 0,
            question="Will it rain?", resolution_rules="Rain is measured.",
            end_time="2027-01-01T00:00:00+00:00",
            captured_at="2026-09-01T00:00:00+00:00",
            source_url="https://polymarket.com/event/rain", yes_token_id="yes",
            asks=(BookLevel(0.4, 100),), fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )
        self.state = {"operating_config": asdict(OperatingConfig())}
        self.context = SimpleNamespace(state=self.state)
        self.discovery_calls = 0
        self.load_calls = 0

        def discover(**_kwargs):
            self.discovery_calls += 1
            return (
                MarketCandidate("123", "Will it rain?", self.snapshot.end_time, self.snapshot.source_url, "123"),
                MarketCandidate("456", "Will it snow?", self.snapshot.end_time, "https://polymarket.com/event/snow", "456"),
            )

        def load(market, _bankroll, market_exposure, total_exposure, **_kwargs):
            self.load_calls += 1
            if market != "123":
                raise ValueError("secret upstream detail")
            return replace(
                self.snapshot,
                market_exposure=market_exposure,
                total_exposure=total_exposure,
            )

        self.find, self.get, self.check = build_trader_tools(self.config, discover=discover, load=load)

    def plan(self, **changes):
        value = {
            "snapshot_id": "snapshot", "market_id": "123", "action": "trade",
            "probability": 0.46, "amount": 9.0,
            "citations": ["market_snapshot:snapshot"], "max_entry_price": 0.41,
            "rationale": "Evidence supports a modest edge.",
            "exit_plan": {"take_profit_roi": 0.1, "stop_loss_roi": -0.2,
                          "exit_by": "2026-10-01T00:00:00+00:00", "hold_to_resolution": False},
        }
        value.update(changes)
        return value

    def test_discovery_is_filtered_small_and_single_call(self) -> None:
        result = self.find("snow", self.context)
        self.assertEqual([item["market_id"] for item in result["candidates"]], ["456"])
        self.assertEqual(self.discovery_calls, 1)
        self.assertEqual(self.find("rain", self.context), {"ok": False, "reason": "market discovery limit reached"})
        self.assertEqual(self.discovery_calls, 1)
        self.assertEqual(self.find("x" * 201, SimpleNamespace(state={})), {"ok": False, "reason": "invalid market query"})

    def test_context_agent_limits_searches_in_its_instruction(self) -> None:
        instruction = build_agents(self.config).context_agent.instruction

        self.assertIn("at most 3 focused searches", instruction)

    def test_non_empty_discovery_returns_only_matches_including_zero_results(self) -> None:
        self.assertEqual(self.find("hail", self.context)["candidates"], [])

        self.state.clear()
        result = self.find("will RAIN", self.context)
        self.assertEqual([item["market_id"] for item in result["candidates"]], ["123"])

    def test_get_stores_canonical_snapshot_and_caps_lookups(self) -> None:
        result = self.get("123", self.context)
        self.assertTrue(result["ok"])
        self.assertEqual(self.state["market_snapshot"], asdict(self.snapshot))
        for _ in range(4):
            self.get("bad", self.context)
        self.assertEqual(self.get("123", self.context), {"ok": False, "reason": "market snapshot lookup limit reached"})
        self.assertEqual(self.load_calls, 1)
        self.assertEqual(self.state["market_snapshot_lookups"], 5)

    def test_get_returns_copyable_plan_inputs(self) -> None:
        plan_inputs = self.get("123", self.context)["plan_inputs"]

        self.assertEqual(plan_inputs["snapshot_id"], "snapshot")
        self.assertEqual(plan_inputs["market_id"], "123")
        self.assertEqual(plan_inputs["valid_citation_ids"], ["market_snapshot:snapshot"])
        self.assertEqual(plan_inputs["captured_at"], self.snapshot.captured_at)
        self.assertEqual(plan_inputs["end_time"], self.snapshot.end_time)
        self.assertEqual(plan_inputs["exit_by_window"]["exclusive_start"], self.snapshot.captured_at)
        self.assertEqual(plan_inputs["exit_by_window"]["exclusive_end"], self.snapshot.end_time)
        self.assertEqual(plan_inputs["current_executable_yes_ask"], 0.4)
        self.assertEqual(plan_inputs["best_ask"], 0.4)
        self.assertAlmostEqual(plan_inputs["maximum_amount"], 10 / 1.02)
        self.assertEqual(plan_inputs["max_entry_price_for_maximum_amount"], 0.4)
        self.assertEqual(plan_inputs["minimum_net_edge"], 0.05)
        self.assertEqual(plan_inputs["fee_rate"], 0.02)
        self.assertEqual(
            plan_inputs["template"]["amount"], plan_inputs["maximum_amount"]
        )

    def test_plan_at_maximum_amount_and_required_entry_price_passes_across_ask_levels(self) -> None:
        self.snapshot = replace(
            self.snapshot,
            asks=(BookLevel(0.4, 10), BookLevel(0.5, 100)),
        )
        self.state.clear()
        self.state["operating_config"] = asdict(OperatingConfig())
        self.find, self.get, self.check = build_trader_tools(
            self.config,
            discover=lambda **_kwargs: (),
            load=lambda _market, _bankroll, market_exposure, total_exposure, **_kwargs: replace(
                self.snapshot,
                market_exposure=market_exposure,
                total_exposure=total_exposure,
            ),
        )
        plan_inputs = self.get("123", self.context)["plan_inputs"]
        plan = deepcopy(plan_inputs["template"])
        plan.update(
            probability=plan_inputs["current_executable_yes_ask"] + plan_inputs["minimum_net_edge"] + 0.01,
            amount=plan_inputs["maximum_amount"],
            max_entry_price=plan_inputs["max_entry_price_for_maximum_amount"],
            rationale="Canonical evidence supports sufficient YES edge.",
        )

        self.assertTrue(self.check(plan, self.context)["passed"])

        rejected = self.check(
            {**plan, "amount": plan_inputs["maximum_amount"] + 0.01},
            self.context,
        )
        self.assertEqual(rejected["reasons"], ["per-market exposure limit exceeded"])

    def test_get_preserves_authoritative_exposure(self) -> None:
        self.state["market_snapshot"] = asdict(
            MarketSnapshot("old", "123", 0.5, 1_000, 7, 90)
        )
        captured = self.get("123", self.context)["market_snapshot"]

        self.assertEqual((captured["market_exposure"], captured["total_exposure"]), (7, 90))
        self.assertFalse(self.check(self.plan(), self.context)["passed"])

    def test_get_uses_authoritative_exposure_without_an_active_snapshot(self) -> None:
        self.state["portfolio_exposure"] = {
            "market_id": "123", "market_exposure": 7, "total_exposure": 90,
        }

        captured = self.get("123", self.context)["market_snapshot"]

        self.assertEqual((captured["market_exposure"], captured["total_exposure"]), (7, 90))

    def test_check_fails_then_passes_and_exactly_five_attempts_are_allowed(self) -> None:
        self.get("123", self.context)
        failed = self.check(self.plan(probability=0.44), self.context)
        passed = self.check(self.plan(), self.context)
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["reasons"], ["minimum net edge of 0.05 not met"])
        self.assertTrue(passed["passed"])
        self.assertEqual(passed["quote"]["fee"], 0.18)
        self.assertEqual(self.state[LAST_SUCCESSFUL_PLAN_KEY], self.plan())
        self.assertEqual(
            self.state[PLAN_CHECKS_KEY],
            [
                {
                    "passed": False,
                    "reasons": ["minimum net edge of 0.05 not met"],
                    "plan": self.plan(probability=0.44),
                },
                {"passed": True, "reasons": [], "plan": self.plan()},
            ],
        )
        for _ in range(3):
            self.check(self.plan(probability=0.44), self.context)
        self.assertEqual(self.check(self.plan(), self.context), {"passed": False, "reasons": ["trade plan check limit reached"]})

    def test_malformed_plan_is_safe_and_counted(self) -> None:
        self.get("123", self.context)
        result = self.check(self.plan(amount="nine"), self.context)
        self.assertEqual(
            result,
            {
                "passed": False,
                "reasons": [
                    "plan schema error: amount: Input should be a valid number"
                ],
            },
        )
        self.assertEqual(self.state["trade_plan_check_attempts"], 1)
        self.assertEqual(
            self.state[PLAN_CHECKS_KEY],
            [
                {
                    "passed": False,
                    "reasons": [
                        "plan schema error: amount: Input should be a valid number"
                    ],
                    "plan": None,
                }
            ],
        )

    def test_missing_fields_direct_the_trader_to_the_complete_template(self) -> None:
        self.get("123", self.context)

        reasons = self.check({"snapshot_id": "snapshot", "market_id": "123"}, self.context)["reasons"]

        self.assertIn(
            "plan schema error: start from plan_inputs.template and submit all fields",
            reasons,
        )

    def test_schema_errors_are_specific_bounded_and_do_not_echo_input(self) -> None:
        self.get("123", self.context)
        plan = self.plan(
            snapshot_id="x" * 500,
            action="buy",
            probability="certain",
            citations=["x" * 500] * 11,
            rationale="",
        )

        reasons = self.check(plan, self.context)["reasons"]

        self.assertLessEqual(len(reasons), 5)
        self.assertTrue(all(len(reason) <= 200 for reason in reasons))
        self.assertTrue(any("snapshot_id: String should have at most 200 characters" in reason for reason in reasons))
        self.assertTrue(any("action: Input should be 'trade' or 'abstain'" in reason for reason in reasons))
        self.assertTrue(any("probability: Input should be a valid number" in reason for reason in reasons))
        self.assertNotIn("x" * 50, " ".join(reasons))

    def test_check_reports_missing_snapshot_without_internal_details(self) -> None:
        result = self.check(self.plan(), self.context)

        self.assertEqual(result, {"passed": False, "reasons": ["capture a market snapshot before checking a plan"]})

    def test_canonical_agent_exposes_only_read_only_trader_tools(self) -> None:
        agents = build_agents(self.config)
        self.assertEqual(
            [getattr(tool, "name", tool.__name__) for tool in agents.trader_agent.tools],
            [
                "find_markets",
                "get_market",
                "check_trade_plan",
                "analyze_stock_history",
                "analyze_crypto_history",
            ],
        )
        self.assertEqual(agents.reviewer_agent.tools, [])

    def test_financial_analysis_tool_schemas_are_bounded_and_symbol_based(self) -> None:
        from google.adk.tools import FunctionTool

        stock_schema = FunctionTool(analyze_stock_history)._get_declaration().parameters_json_schema
        crypto_schema = FunctionTool(analyze_crypto_history)._get_declaration().parameters_json_schema
        self.assertEqual(set(stock_schema["properties"]), {"symbol", "limit"})
        self.assertEqual(
            set(crypto_schema["properties"]),
            {"exchange_id", "symbol", "interval", "limit"},
        )

    def test_financial_tool_adds_snapshot_bound_citable_analysis(self) -> None:
        candles = [
            Candle(1_760_000_000 + i * 86_400, 100 + i, 102 + i, 99 + i, 101 + i, 10 + i)
            for i in range(20)
        ]
        self.state["market_snapshot"] = asdict(self.snapshot)
        self.state[paper_cycle.EVIDENCE_KEY] = [
            item.model_dump() for item in paper_cycle._canonical_evidence(self.snapshot)
        ]
        with patch(
            "chrysopoeia.agent.stock_history",
            return_value={
                "symbol": "AAPL",
                "currency": "USD",
                "interval": "1d",
                "source": "test source",
                "source_url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
                "candles": candles,
            },
        ):
            result = analyze_stock_history("AAPL", self.context)

        self.assertTrue(result["ok"])
        evidence_id = result["evidence_id"]
        evidence = paper_cycle._evidence(self.state, self.snapshot)
        self.assertEqual(evidence[-1].evidence_id, evidence_id)
        self.assertEqual(
            self.state[paper_cycle.VALIDATED_EXTERNAL_EVIDENCE_KEY][0]["evidence_id"],
            evidence_id,
        )
        self.assertEqual(self.state["financial_analysis_calls"], 1)

    def test_financial_tools_are_bounded_per_cycle(self) -> None:
        self.state["market_snapshot"] = asdict(self.snapshot)
        self.state[paper_cycle.EVIDENCE_KEY] = [
            item.model_dump() for item in paper_cycle._canonical_evidence(self.snapshot)
        ]
        self.state["financial_analysis_calls"] = 2
        self.assertEqual(
            analyze_stock_history("AAPL", self.context),
            {"ok": False, "reason": "financial-analysis call limit reached"},
        )

    def test_trader_instruction_requires_returning_the_exact_passed_plan(self) -> None:
        instruction = build_agents(self.config).trader_agent.instruction.lower()

        self.assertIn("exact plan you intend", instruction)
        self.assertIn("read the reasons, revise, and re-check", instruction)
        self.assertIn("last passed plan unchanged", instruction)
        self.assertIn("including rationale", instruction)
        self.assertIn("abstain if no plan check passes", instruction)

    def test_trader_instruction_uses_plan_inputs_constraints(self) -> None:
        instruction = build_agents(self.config).trader_agent.instruction.lower()

        self.assertIn("build the plan from plan_inputs", instruction)
        self.assertIn("complete template", instruction)
        self.assertIn("amount ≤ maximum_amount", instruction)
        self.assertIn("never infer amount from bankroll", instruction)
        self.assertIn("required price for that amount", instruction)
        self.assertIn("max_entry_price", instruction)
        self.assertIn("executable yes ask", instruction)
        self.assertIn("exit_by inside", instruction)
        self.assertIn("never equal to either endpoint", instruction)
        self.assertIn("hold_to_resolution", instruction)
        self.assertIn("cite only the listed", instruction)
    def test_plan_check_tool_publishes_structured_plan_schema(self) -> None:
        from google.adk.tools import FunctionTool

        schema = FunctionTool(self.check)._get_declaration().parameters_json_schema
        plan = schema["$defs"][schema["properties"]["plan"]["$ref"].split("/")[-1]]

        self.assertEqual(plan["properties"]["citations"]["type"], "array")
        self.assertEqual(
            plan["properties"]["citations"]["items"]["type"], "string"
        )


if __name__ == "__main__":
    unittest.main()
