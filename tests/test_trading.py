import math
import unittest

from chrysopoeia.agent import context_agent, reviewer_agent, root_agent, trader_agent
from chrysopoeia.context import discover_context
from chrysopoeia.trading import BookLevel, MarketSnapshot, OperatingConfig, Proposal, Review, run_decision_cycle


class DecisionCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = MarketSnapshot("snapshot-1", "market-1", 0.40, 1_000, 0, 0)
        self.proposal = Proposal("snapshot-1", "market-1", 0.46, 10)
        self.review = Review("snapshot-1", "market-1", True, "Thesis is supported.")

    def rich_snapshot(self, **changes: object) -> MarketSnapshot:
        values = {
            "question": "Will it rain?",
            "resolution_rules": "Resolves Yes if rain is measured.",
            "end_time": "2026-09-02T00:00:00+00:00",
            "captured_at": "2026-09-01T00:00:00+00:00",
            "source_url": "https://polymarket.com/event/will-it-rain",
            "yes_token_id": "yes-token",
            "book_captured_at": "2026-09-01T00:00:00+00:00",
        }
        values.update(changes)
        return MarketSnapshot("snapshot-1", "market-1", 0.4, 1_000, 0, 0, **values)

    def test_approved_proposal_produces_fill_and_report(self) -> None:
        report = run_decision_cycle(self.snapshot, self.proposal, self.review)

        self.assertTrue(report.decision.allowed)
        self.assertEqual(report.fill.amount, 10)
        self.assertEqual(report.fill.price, 0.40)
        self.assertIn("snapshot-1", report.summary)
        self.assertIn("market-1", report.summary)

    def test_depth_and_fee_produce_exact_vwap_shares_and_total_cost(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 10), BookLevel(0.5, 20)),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
        )

        report = run_decision_cycle(snapshot, Proposal("snapshot-1", "market-1", 0.56, 9), self.review)

        self.assertTrue(report.decision.allowed)
        self.assertAlmostEqual(report.fill.shares, 20)
        self.assertAlmostEqual(report.fill.price, 0.45)
        self.assertEqual(report.fill.amount, 9)
        self.assertEqual(report.fill.fee, 0.18)
        self.assertEqual(report.fill.total_cost, 9.18)
        self.assertEqual(report.fill.levels_consumed, 2)
        for value in ("VWAP 0.45", "gross 9", "fee 0.18", "total 9.18", "shares 20"):
            self.assertIn(value, report.summary)

    def test_insufficient_depth_rejects_without_partial_fill(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 10),),
        )

        report = run_decision_cycle(snapshot, self.proposal, self.review)

        self.assertFalse(report.decision.allowed)
        self.assertIsNone(report.fill)
        self.assertIn("insufficient executable YES depth", report.decision.reason)

    def test_risk_limits_include_fee_at_the_boundary(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 100),),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
        )

        report = run_decision_cycle(snapshot, self.proposal, self.review)

        self.assertFalse(report.decision.allowed)
        self.assertIn("per-market exposure", report.decision.reason)

    def test_policy_rejections_produce_no_fill_and_reason(self) -> None:
        cases = (
            (self.snapshot, self.proposal, Review("snapshot-1", "market-1", False, "Weak evidence."), "review rejected"),
            (self.snapshot, Proposal("snapshot-1", "market-1", 0.44, 10), self.review, "minimum net edge"),
            (MarketSnapshot("snapshot-1", "market-1", 0.40, 1_000, 1, 5), self.proposal, self.review, "per-market exposure"),
            (MarketSnapshot("snapshot-1", "market-1", 0.40, 1_000, 0, 95), self.proposal, self.review, "total exposure"),
        )
        for snapshot, proposal, review, reason in cases:
            with self.subTest(reason=reason):
                report = run_decision_cycle(snapshot, proposal, review)
                self.assertFalse(report.decision.allowed)
                self.assertIsNone(report.fill)
                self.assertIn(reason, report.decision.reason)

    def test_invalid_boundary_values_are_rejected(self) -> None:
        invalid_calls = (
            lambda: MarketSnapshot("s", "m", math.nan, 1_000, 0, 0),
            lambda: MarketSnapshot("s", "m", 1.01, 1_000, 0, 0),
            lambda: MarketSnapshot("s", "m", 0.4, 0, 0, 0),
            lambda: MarketSnapshot("s", "m", 0.4, 1_000, -1, 0),
            lambda: MarketSnapshot("s", "m", 0.4, 1_000, 2, 1),
            lambda: Proposal("s", "m", math.inf, 10),
            lambda: Proposal("s", "m", 0.5, 0),
            lambda: self.rich_snapshot(asks=(BookLevel(0.4, 1),), fee_rate=0.01),
            lambda: self.rich_snapshot(asks=(BookLevel(0.4, 1),), source_url="https://user:pass@polymarket.com/event/x"),
        )
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()

    def test_inconsistent_snapshot_or_market_ids_are_rejected(self) -> None:
        for proposal, review in (
            (Proposal("other", "market-1", 0.46, 10), self.review),
            (self.proposal, Review("snapshot-1", "other", True, "ok")),
        ):
            with self.subTest(proposal=proposal, review=review), self.assertRaisesRegex(ValueError, "identit"):
                run_decision_cycle(self.snapshot, proposal, review)

    def test_agents_have_separate_non_execution_roles(self) -> None:
        self.assertNotEqual(trader_agent.name, reviewer_agent.name)
        self.assertIn("propose", trader_agent.instruction.lower())
        self.assertIn("review", reviewer_agent.instruction.lower())
        for agent in (trader_agent, reviewer_agent):
            self.assertFalse(any("execute" in str(tool).lower() for tool in agent.tools))

    def test_orchestrator_owns_validated_operating_configuration(self) -> None:
        configuration = OperatingConfig(bankroll=1_000, trader_agents=3)

        self.assertEqual(configuration.bankroll, 1_000)
        self.assertEqual(configuration.trader_agents, 3)
        self.assertTrue(any("configure_operation" in str(tool) for tool in root_agent.tools))
        with self.assertRaises(ValueError):
            OperatingConfig(bankroll=1_000, trader_agents=0)

    def test_trader_discovers_and_calls_context_on_demand(self) -> None:
        interfaces = discover_context("Check current evidence for this market")

        self.assertEqual(interfaces[0]["interface_id"], "public_web")
        self.assertEqual(context_agent.name, "call_context")
        self.assertTrue(any("discover_context" in str(tool) for tool in trader_agent.tools))
        self.assertTrue(any(getattr(tool, "name", None) == "call_context" for tool in trader_agent.tools))
        with self.assertRaises(ValueError):
            discover_context("")


if __name__ == "__main__":
    unittest.main()
