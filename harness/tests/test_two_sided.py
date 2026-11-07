import asyncio
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from chrysopoeia import accounting, paper_cycle
from chrysopoeia.cli import load_capture_snapshot, serialize_market_snapshot
from chrysopoeia.configuration import load_harness_config
from chrysopoeia.cycle_runner import run_paper_cycle
from chrysopoeia.trading import (
    BookLevel,
    ExitPlan,
    MarketSnapshot,
    OperatingConfig,
    Proposal,
    Review,
    consume_trade_plan,
    market_snapshot_identity,
    outcome_snapshot,
    quote_exit,
    recheck_trade_plan,
    run_decision_cycle,
)
from tests.test_cycle_runner import FakeLlm

ROOT = Path(__file__).parents[2]


def snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        "snapshot",
        "123",
        0.68,
        1000,
        0,
        0,
        "BTC Up or Down",
        "Chainlink determines the winner",
        "2027-01-01T00:00:00+00:00",
        "2026-10-17T00:00:00+00:00",
        "https://polymarket.com/event/btc-updown-5m-123",
        "up-token",
        (BookLevel(0.68, 100),),
        0.02,
        "paper-assumption:flat-2pct-v1",
        "2026-10-17T00:00:00+00:00",
        (BookLevel(0.67, 100),),
        "down-token",
        (BookLevel(0.34, 100),),
        (BookLevel(0.33, 100),),
        "2026-10-17T00:00:00+00:00",
    )


class TwoSidedTests(unittest.TestCase):
    def test_dual_book_capture_round_trips_with_both_token_identities(self):
        snap = snapshot()
        snap = replace(snap, snapshot_id=market_snapshot_identity(snap))
        config = load_harness_config(ROOT / "harness/chrysopoeia.toml")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(serialize_market_snapshot(snap)))
            restored = load_capture_snapshot(path, config, OperatingConfig())
        self.assertEqual(restored.no_asks, snap.no_asks)
        self.assertEqual(restored.no_token_id, "down-token")
        self.assertEqual(restored.snapshot_id, snap.snapshot_id)

    def test_production_workflow_checks_reviews_and_emits_a_no_plan(self):
        snap = snapshot()
        config = load_harness_config(ROOT / "harness/chrysopoeia.toml")
        citation = paper_cycle._canonical_evidence(snap)[0].evidence_id
        plan = {
            "snapshot_id": snap.snapshot_id,
            "market_id": snap.market_id,
            "action": "trade",
            "outcome": "NO",
            "probability": 0.15,
            "amount": 9.0,
            "max_entry_price": 0.35,
            "citations": [citation],
            "rationale": "BTC downward momentum supports Down.",
            "exit_plan": {
                "take_profit_roi": 0.1,
                "stop_loss_roi": None,
                "exit_by": None,
                "hold_to_resolution": True,
            },
        }
        calls = []
        trader = FakeLlm(model=config.models.trader, response=plan, calls=calls)
        reviewer = FakeLlm(
            model=config.models.reviewer,
            response={
                "snapshot_id": snap.snapshot_id,
                "market_id": snap.market_id,
                "approved": True,
                "reason": "supported",
                "citations": [citation],
            },
            calls=calls,
        )
        result = asyncio.run(
            run_paper_cycle(config, snap, OperatingConfig(), trader, reviewer)
        )
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["event"]["outcome"], "NO")
        self.assertEqual(result["outcome_event"]["schema_version"], 4)
        self.assertEqual(
            result["outcome_event"]["context"]["scope_key"],
            "polymarket:series:btc-updown-5m",
        )

    def test_bearish_forecast_buys_actual_down_book_and_emits_v2(self):
        snap = snapshot()
        proposal = Proposal(
            "snapshot",
            "123",
            0.15,
            9,
            0.35,
            ExitPlan(0.1, hold_to_resolution=True),
            ("evidence",),
            "NO",
        )
        report = run_decision_cycle(
            snap, proposal, Review("snapshot", "123", True, "ok", ("evidence",))
        )
        self.assertTrue(report.decision.allowed)
        event = report.event
        self.assertIsNotNone(event)
        self.assertEqual(
            (event.schema_version, event.outcome, event.instrument_id),
            (2, "NO", "down-token"),
        )
        self.assertAlmostEqual(event.probability, 0.85)
        fill = consume_trade_plan(event, snap)
        self.assertAlmostEqual(fill.price, 0.34)
        self.assertNotAlmostEqual(fill.price, 1 - snap.price)
        schema = json.loads(
            (ROOT / "contracts/trade_plan_ready.v2.schema.json").read_text()
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            json.loads(json.dumps(asdict(event)))
        )

    def test_no_book_is_required_and_yes_book_is_not_a_substitute(self):
        snap = replace(
            snapshot(), no_token_id="", no_asks=(), no_bids=(), no_book_captured_at=""
        )
        with self.assertRaisesRegex(ValueError, "unavailable"):
            outcome_snapshot(snap, "NO")

    def test_no_risk_check_uses_no_edge_and_no_executable_depth(self):
        snap = snapshot()
        proposal = Proposal(
            "snapshot",
            "123",
            0.15,
            9,
            0.35,
            ExitPlan(0.1, hold_to_resolution=True),
            ("evidence",),
            "NO",
        )
        review = Review("snapshot", "123", True, "ok", ("evidence",))
        costly = replace(snap, no_asks=(BookLevel(0.84, 100),), no_bids=())
        self.assertFalse(run_decision_cycle(costly, proposal, review).decision.allowed)
        thin = replace(snap, no_asks=(BookLevel(0.34, 1),))
        self.assertFalse(run_decision_cycle(thin, proposal, review).decision.allowed)
        event = run_decision_cycle(snap, proposal, review).event
        fresh = replace(snap, no_token_id="another-no-token")
        with self.assertRaisesRegex(ValueError, "instrument"):
            recheck_trade_plan(
                event,
                fresh,
                OperatingConfig(),
                now=datetime.fromisoformat(snap.captured_at),
            )

    def test_no_exit_uses_no_bids(self):
        selected = outcome_snapshot(snapshot(), "NO")
        quote = quote_exit(selected, 10)
        self.assertAlmostEqual(quote.price, 0.33)
        self.assertAlmostEqual(quote.net_proceeds, 3.3 * 0.98)

    def test_no_position_settles_on_the_no_result_and_replays(self):
        snap = snapshot()
        proposal = Proposal(
            "snapshot",
            "123",
            0.15,
            9,
            0.35,
            ExitPlan(0.1, hold_to_resolution=True),
            ("evidence",),
            "NO",
        )
        event = run_decision_cycle(
            snap, proposal, Review("snapshot", "123", True, "ok", ("evidence",))
        ).event
        fill = consume_trade_plan(event, snap)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            accounting.open_session(path, 1000, 100)
            accounting.admit_turn(
                path, event.event_id, snap.snapshot_id, snap.market_id
            )
            accounting.record_fill(
                path,
                accounting.Position(
                    snap.market_id,
                    snap.snapshot_id,
                    snap.captured_at,
                    fill.price,
                    fill.amount,
                    fill.shares,
                    fill.fee,
                    fill.total_cost,
                    proposal.exit_plan,
                    event,
                ),
                event.event_id,
            )
            accounting.finish_turn(path, event.event_id, "filled")
            accounting.settle(path, accounting.replay(path), "123", "resolved_no")
            self.assertGreater(accounting.replay(path).realized_pnl, 0)

    def test_no_position_loses_when_yes_wins(self):
        snap = snapshot()
        proposal = Proposal(
            "snapshot",
            "123",
            0.15,
            9,
            0.35,
            ExitPlan(0.1, hold_to_resolution=True),
            ("evidence",),
            "NO",
        )
        event = run_decision_cycle(
            snap, proposal, Review("snapshot", "123", True, "ok", ("evidence",))
        ).event
        fill = consume_trade_plan(event, snap)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            accounting.open_session(path, 1000, 100)
            accounting.admit_turn(
                path, event.event_id, snap.snapshot_id, snap.market_id
            )
            accounting.record_fill(
                path,
                accounting.Position(
                    snap.market_id,
                    snap.snapshot_id,
                    snap.captured_at,
                    fill.price,
                    fill.amount,
                    fill.shares,
                    fill.fee,
                    fill.total_cost,
                    proposal.exit_plan,
                    event,
                ),
                event.event_id,
            )
            accounting.finish_turn(path, event.event_id, "filled")
            accounting.settle(path, accounting.replay(path), "123", "resolved_yes")
            self.assertAlmostEqual(
                accounting.replay(path).realized_pnl, -fill.total_cost
            )

    def test_legacy_no_turn_outcome_remains_v2_without_context(self):
        output = paper_cycle.ProposalOutput(
            snapshot_id="snapshot",
            market_id="123",
            action="abstain",
            outcome="NO",
            probability=0.15,
            amount=0,
            citations=[],
            rationale="No sufficient edge",
        )
        outcome = paper_cycle.build_turn_outcome(
            proposal=output,
            review=None,
            policy=None,
            status="abstained",
            reason="trader_abstained",
            created_at="2026-10-17T00:00:00+00:00",
            trade_plan_event_id=None,
            model_cost_usd="0",
        )
        self.assertEqual(outcome["schema_version"], 2)
        self.assertEqual(outcome["proposal"]["probability"], 0.15)
        self.assertEqual(paper_cycle.validate_turn_outcome(outcome), outcome)
        tampered = dict(outcome)
        tampered["reserved_model_cost_usd"] = 0
        with self.assertRaises(ValueError):
            paper_cycle.validate_turn_outcome(tampered)
        schema = json.loads(
            (ROOT / "contracts/turn_outcome.v2.schema.json").read_text()
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(outcome)


if __name__ == "__main__":
    unittest.main()
