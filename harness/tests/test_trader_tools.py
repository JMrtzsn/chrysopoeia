import unittest
from dataclasses import asdict, replace
from types import SimpleNamespace

from chrysopoeia.agent import build_agents, build_trader_tools
from chrysopoeia.configuration import load_harness_config
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
        self.assertEqual(result, {"passed": False, "reasons": ["plan schema error: amount is invalid"]})
        self.assertEqual(self.state["trade_plan_check_attempts"], 1)
        self.assertEqual(
            self.state[PLAN_CHECKS_KEY],
            [{"passed": False, "reasons": ["plan schema error: amount is invalid"], "plan": None}],
        )

    def test_check_reports_missing_snapshot_without_internal_details(self) -> None:
        result = self.check(self.plan(), self.context)

        self.assertEqual(result, {"passed": False, "reasons": ["capture a market snapshot before checking a plan"]})

    def test_canonical_agent_exposes_only_read_only_trader_tools(self) -> None:
        agents = build_agents(self.config)
        self.assertEqual(
            [getattr(tool, "name", tool.__name__) for tool in agents.trader_agent.tools],
            ["find_markets", "get_market", "check_trade_plan"],
        )
        self.assertEqual(agents.reviewer_agent.tools, [])

    def test_trader_instruction_requires_returning_the_exact_passed_plan(self) -> None:
        instruction = build_agents(self.config).trader_agent.instruction.lower()

        self.assertIn("exact plan you intend", instruction)
        self.assertIn("read the reasons, revise, and re-check", instruction)
        self.assertIn("last passed plan unchanged", instruction)
        self.assertIn("including rationale", instruction)
        self.assertIn("abstain if no plan check passes", instruction)


if __name__ == "__main__":
    unittest.main()
