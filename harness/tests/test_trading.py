import math
import unittest
from unittest.mock import patch

from chrysopoeia.agent import context_agent, reviewer_agent, root_agent, trader_agent
from chrysopoeia.context import discover_context
from chrysopoeia.trading import (
    BookLevel,
    ExitPlan,
    MarketSnapshot,
    OperatingConfig,
    Proposal,
    Review,
    consume_trade_plan,
    quote_exit,
    run_decision_cycle,
)


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

    def test_approved_proposal_without_complete_event_terms_produces_no_fill(self) -> None:
        report = run_decision_cycle(self.snapshot, self.proposal, self.review)

        self.assertTrue(report.decision.allowed)
        self.assertIsNone(report.fill)
        self.assertIsNone(report.event)
        self.assertIn("snapshot-1", report.summary)
        self.assertIn("market-1", report.summary)

    def test_consumer_preserves_depth_and_fee_quote(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 10), BookLevel(0.5, 20)),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
        )

        proposal = Proposal(
            "snapshot-1",
            "market-1",
            0.56,
            9,
            0.5,
            ExitPlan(0.1, -0.2, "2026-09-01T12:00:00+00:00"),
        )
        review = Review("snapshot-1", "market-1", True, "supported", ("evidence-1",))
        report = run_decision_cycle(snapshot, proposal, review)
        fill = consume_trade_plan(report.event, snapshot)

        self.assertTrue(report.decision.allowed)
        self.assertIsNone(report.fill)
        self.assertAlmostEqual(fill.shares, 20)
        self.assertAlmostEqual(fill.price, 0.45)
        self.assertEqual(fill.amount, 9)
        self.assertEqual(fill.fee, 0.18)
        self.assertEqual(fill.total_cost, 9.18)
        self.assertEqual(fill.levels_consumed, 2)

    def test_accepted_review_emits_stable_strict_trade_plan_without_filling(self) -> None:
        snapshot = self.rich_snapshot(asks=(BookLevel(0.4, 100),))
        proposal = Proposal(
            "snapshot-1", "market-1", 0.56, 9, 0.41,
            ExitPlan(0.1, -0.2, "2026-09-01T12:00:00+00:00"),
        )
        review = Review("snapshot-1", "market-1", True, "supported", ("evidence-1",))

        with patch("chrysopoeia.trading.consume_trade_plan") as consume:
            first = run_decision_cycle(snapshot, proposal, review)
            second = run_decision_cycle(snapshot, proposal, review)
        consume.assert_not_called()

        event = first.event
        self.assertIsNotNone(event)
        self.assertEqual(event, second.event)
        self.assertIsNone(first.fill)
        self.assertIsNone(second.fill)
        self.assertEqual(event.schema_version, 1)
        self.assertEqual(event.record_type, "trade_plan_ready")
        self.assertEqual(event.created_at, "2026-09-01T00:00:00+00:00")
        self.assertEqual((event.market_id, event.snapshot_id), ("market-1", "snapshot-1"))
        self.assertEqual((event.outcome, event.instrument_id), ("YES", "yes-token"))
        self.assertEqual((event.probability, event.stake, event.max_entry_price), (0.56, 9, 0.41))
        self.assertEqual(event.exit_plan, proposal.exit_plan)
        self.assertTrue(event.reviewer_approved)
        self.assertEqual(event.reviewer_citations, ("evidence-1",))
        self.assertEqual(event.evidence_references, ("evidence-1",))
        self.assertEqual(event.expires_at, snapshot.end_time)
        self.assertFalse(hasattr(event, "review_reason"))

        self.assertEqual(consume_trade_plan(event, snapshot).amount, 9)

    def test_trade_plan_consumer_rejects_wrong_identity_and_unsupported_terms(self) -> None:
        snapshot = self.rich_snapshot(asks=(BookLevel(0.4, 100),))
        proposal = Proposal(
            "snapshot-1", "market-1", 0.56, 9, 0.41,
            ExitPlan(0.1, -0.2, "2026-09-01T12:00:00+00:00"),
        )
        review = Review(
            "snapshot-1", "market-1", True, "supported", ("evidence-1",)
        )
        event = run_decision_cycle(snapshot, proposal, review).event
        self.assertIsNotNone(event)

        from dataclasses import replace

        for changed, reason in (
            (replace(event, event_id="turn-wrong"), "event identity"),
            (replace(event, snapshot_id="other"), "identity"),
            (replace(event, outcome="NO"), "YES"),
            (replace(event, max_entry_price=0.39), "maximum entry"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                consume_trade_plan(changed, snapshot)

    def test_insufficient_depth_rejects_without_partial_fill(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 10),),
        )

        report = run_decision_cycle(snapshot, self.proposal, self.review)

        self.assertFalse(report.decision.allowed)
        self.assertIsNone(report.fill)
        self.assertIn("insufficient executable YES depth", report.decision.reason)

    def test_exit_quote_walks_bid_depth_and_subtracts_fees(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 10),),
            bids=(BookLevel(0.3, 4), BookLevel(0.2, 10)),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
        )

        quote = quote_exit(snapshot, 10)

        self.assertAlmostEqual(quote.price, 0.24)
        self.assertAlmostEqual(quote.gross_proceeds, 2.4)
        self.assertAlmostEqual(quote.fee, 0.048)
        self.assertAlmostEqual(quote.net_proceeds, 2.352)
        self.assertEqual(quote.levels_consumed, 2)
        with self.assertRaisesRegex(ValueError, "insufficient executable YES bid depth"):
            quote_exit(snapshot, 15)

    def test_maximum_entry_price_rejects_an_over_limit_vwap(self) -> None:
        proposal = Proposal("snapshot-1", "market-1", 0.46, 10, max_entry_price=0.39)

        report = run_decision_cycle(self.snapshot, proposal, self.review)

        self.assertFalse(report.decision.allowed)
        self.assertIn("maximum entry price", report.decision.reason)

    def test_maximum_entry_price_rejects_any_consumed_ask_above_limit(self) -> None:
        snapshot = self.rich_snapshot(
            asks=(BookLevel(0.4, 10), BookLevel(0.5, 20)),
        )
        proposal = Proposal("snapshot-1", "market-1", 0.56, 9, max_entry_price=0.45)

        report = run_decision_cycle(snapshot, proposal, self.review)

        self.assertFalse(report.decision.allowed)
        self.assertIn("maximum entry price", report.decision.reason)

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
                self.assertIsNone(report.event)
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
            lambda: self.rich_snapshot(asks=(BookLevel(0.4, 1),), source_url="https://www.polymarket.com/event/will-it-rain"),
            lambda: self.rich_snapshot(asks=(BookLevel(0.4, 1),), source_url="https://polymarket.com/event/weather/will-it-rain"),
            lambda: self.rich_snapshot(asks=(BookLevel(0.4, 1),), source_url="https://polymarket.com/event/will_it_rain"),
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

    def test_trader_abstains_when_only_no_has_edge(self) -> None:
        instruction = trader_agent.instruction.lower()

        self.assertIn("only yes positions can be taken", instruction)
        self.assertIn("probability is below the yes price", instruction)
        self.assertIn("no yes edge exists", instruction)
        self.assertIn("abstain and explain in rationale", instruction)
        self.assertIn(
            "cite only evidence_id values returned by get_market or the financial-analysis tools",
            instruction,
        )

    def test_orchestrator_owns_validated_operating_configuration(self) -> None:
        configuration = OperatingConfig(bankroll=1_000, trader_agents=3)

        self.assertEqual(configuration.bankroll, 1_000)
        self.assertEqual(configuration.trader_agents, 3)
        self.assertTrue(any("configure_operation" in str(tool) for tool in root_agent.tools))
        with self.assertRaises(ValueError):
            OperatingConfig(bankroll=1_000, trader_agents=0)

    def test_root_agent_does_not_ask_human_to_pick_markets(self) -> None:
        self.assertIn("harness selects", root_agent.instruction)
        self.assertIn("not market picks", root_agent.instruction)

    def test_trader_exposes_bounded_market_and_financial_tools(self) -> None:
        interfaces = discover_context("Check current evidence for this market")

        self.assertEqual(interfaces[0]["interface_id"], "public_web")
        self.assertEqual(context_agent.name, "call_context")
        self.assertEqual(
            [tool.__name__ for tool in trader_agent.tools],
            [
                "find_markets",
                "get_market",
                "check_trade_plan",
                "analyze_stock_history",
                "analyze_crypto_history",
            ],
        )
        with self.assertRaises(ValueError):
            discover_context("")


if __name__ == "__main__":
    unittest.main()
