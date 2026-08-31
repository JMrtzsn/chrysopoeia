import copy
import unittest
from dataclasses import asdict
import math
from types import SimpleNamespace

from pydantic import ValidationError

from chrysopoeia.agent import (
    PAPER_CYCLE_DECISION_KEY,
    PAPER_CYCLE_FILL_KEY,
    PAPER_CYCLE_REPORT_KEY,
    PROPOSAL_KEY,
    REVIEW_KEY,
    ProposalOutput,
    ReviewOutput,
    PaperCycleRequest,
    complete_paper_cycle,
    finalize_paper_cycle,
    paper_cycle_workflow,
    prepare_reviewer_input,
    prepare_trader_input,
    reviewer_agent,
    root_agent,
    trader_agent,
)
from chrysopoeia.cost import after_model_cost, before_model_cost, on_model_cost_error
from chrysopoeia.trading import MarketSnapshot, OperatingConfig


def cycle_state(*, approved: bool = True) -> dict[str, object]:
    return {
        "operating_config": asdict(OperatingConfig()),
        "market_snapshot": asdict(MarketSnapshot("snapshot-1", "market-1", 0.4, 1_000, 0, 0)),
        PROPOSAL_KEY: {
            "snapshot_id": "snapshot-1",
            "market_id": "market-1",
            "probability": 0.46,
            "amount": 10,
        },
        REVIEW_KEY: {
            "snapshot_id": "snapshot-1",
            "market_id": "market-1",
            "approved": approved,
            "reason": "supported" if approved else "weak evidence",
        },
    }


class PaperCycleTests(unittest.TestCase):
    def test_approved_state_cycle_fills_and_records_outputs(self) -> None:
        state = cycle_state()
        state["model_cost_policy"] = {"version": "test"}
        state["model_cost_ledger"] = [{"status": "completed"}]
        preserved = copy.deepcopy({key: state[key] for key in (
            "operating_config", "market_snapshot", "model_cost_policy", "model_cost_ledger",
        )})

        report = finalize_paper_cycle(state)

        self.assertEqual(report["status"], "filled")
        self.assertEqual(state[PAPER_CYCLE_FILL_KEY]["price"], 0.4)
        self.assertEqual(state[PAPER_CYCLE_FILL_KEY]["amount"], 10)
        self.assertTrue(state[PAPER_CYCLE_DECISION_KEY]["allowed"])
        self.assertEqual(state[PAPER_CYCLE_REPORT_KEY], report)
        self.assertEqual({key: state[key] for key in preserved}, preserved)

    def test_offline_compiled_workflow_path_reaches_finalizer_in_order(self) -> None:
        state = cycle_state()
        del state[PROPOSAL_KEY]
        del state[REVIEW_KEY]
        ctx = SimpleNamespace(state=state)
        expected_order = [
            "__START__", "prepare_trader_input", trader_agent.name, "prepare_reviewer_input",
            reviewer_agent.name, "complete_paper_cycle",
        ]

        order = ["__START__"]
        while order[-1] != expected_order[-1]:
            order.extend(paper_cycle_workflow.graph.get_next_pending_nodes(order[-1], None))
        trader_input = prepare_trader_input(ctx, PaperCycleRequest())
        self.assertEqual(trader_input, state["market_snapshot"])
        proposal = ProposalOutput(snapshot_id="snapshot-1", market_id="market-1", probability=0.46, amount=10)
        state[PROPOSAL_KEY] = proposal.model_dump()
        reviewer_input = prepare_reviewer_input(ctx, proposal)
        self.assertEqual(reviewer_input.market_snapshot, state["market_snapshot"])
        review = ReviewOutput(snapshot_id="snapshot-1", market_id="market-1", approved=True, reason="supported")
        report = complete_paper_cycle(ctx, review)

        self.assertEqual(order, expected_order)
        self.assertEqual(report.status, "filled")
        self.assertEqual(state[PAPER_CYCLE_FILL_KEY]["amount"], 10)
        self.assertEqual(state[REVIEW_KEY], review.model_dump())

    def test_reviewer_rejection_records_no_fill_and_explicit_reason(self) -> None:
        state = cycle_state(approved=False)

        report = finalize_paper_cycle(state)

        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["reason"], "review_rejected")
        self.assertIsNone(state[PAPER_CYCLE_FILL_KEY])
        self.assertFalse(state[PAPER_CYCLE_DECISION_KEY]["allowed"])

    def test_existing_risk_rejections_record_no_fill(self) -> None:
        cases = (
            ({"probability": 0.44}, {}, "minimum net edge of 0.05 not met"),
            ({}, {"market_exposure": 1, "total_exposure": 5}, "per-market exposure limit exceeded"),
            ({}, {"market_exposure": 0, "total_exposure": 95}, "total exposure limit exceeded"),
        )
        for proposal_changes, snapshot_changes, reason in cases:
            state = cycle_state()
            state[PROPOSAL_KEY] = {**state[PROPOSAL_KEY], **proposal_changes}
            state["market_snapshot"] = {**state["market_snapshot"], **snapshot_changes}
            with self.subTest(reason=reason):
                report = finalize_paper_cycle(state)
                self.assertEqual(report, {"status": "rejected", "reason": reason, "summary": state[PAPER_CYCLE_REPORT_KEY]["summary"]})
                self.assertIsNone(state[PAPER_CYCLE_FILL_KEY])

    def test_invalid_or_inconsistent_state_rejects_before_fill(self) -> None:
        invalid_states = []
        for missing in ("operating_config", "market_snapshot", PROPOSAL_KEY, REVIEW_KEY):
            state = cycle_state()
            del state[missing]
            invalid_states.append(state)
        for key, changes in (
            ("market_snapshot", {"price": math.nan}),
            ("market_snapshot", {"price": True}),
            (PROPOSAL_KEY, {"probability": math.inf}),
            (PROPOSAL_KEY, {"probability": True}),
            (PROPOSAL_KEY, {"amount": 0}),
            (PROPOSAL_KEY, {"amount": True}),
            (REVIEW_KEY, {"approved": 1}),
            (REVIEW_KEY, {"reason": "x" * 501}),
            ("operating_config", {"bankroll": "invalid"}),
        ):
            state = cycle_state()
            state[key] = {**state[key], **changes}
            invalid_states.append(state)
        for state in invalid_states:
            with self.subTest(state=state), self.assertRaises(ValueError):
                finalize_paper_cycle(state)
            self.assertNotIn(PAPER_CYCLE_FILL_KEY, state)

        for key in (PROPOSAL_KEY, REVIEW_KEY):
            state = cycle_state()
            state[key] = {**state[key], "market_id": "other"}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity"):
                finalize_paper_cycle(state)
            self.assertNotIn(PAPER_CYCLE_FILL_KEY, state)

    def test_structured_wiring_and_tool_boundaries(self) -> None:
        self.assertIs(trader_agent.output_schema, ProposalOutput)
        self.assertEqual(trader_agent.output_key, PROPOSAL_KEY)
        self.assertIs(reviewer_agent.output_schema, ReviewOutput)
        self.assertEqual(reviewer_agent.output_key, REVIEW_KEY)
        self.assertEqual((trader_agent.mode, reviewer_agent.mode), ("single_turn", "single_turn"))
        self.assertEqual((trader_agent.include_contents, reviewer_agent.include_contents), ("none", "none"))
        self.assertNotEqual(trader_agent.name, reviewer_agent.name)
        self.assertNotEqual(trader_agent.output_key, reviewer_agent.output_key)
        node_names = {node.name for node in paper_cycle_workflow.graph.nodes}
        self.assertIn(trader_agent.name, node_names)
        self.assertIn(reviewer_agent.name, node_names)
        self.assertTrue(any(getattr(tool, "name", None) == paper_cycle_workflow.name for tool in root_agent.tools))
        for schema, forbidden in (
            (ProposalOutput, {"approved", "reason", "execute"}),
            (ReviewOutput, {"probability", "amount", "execute"}),
        ):
            self.assertTrue(forbidden.isdisjoint(schema.model_fields))
            with self.assertRaises(ValidationError):
                schema.model_validate({
                    "snapshot_id": "snapshot-1", "market_id": "market-1", "probability": 0.5, "amount": 1,
                    "approved": True, "reason": "ok", "execute": True,
                })
        for agent in (trader_agent, reviewer_agent, root_agent):
            tools = " ".join(str(tool).lower() for tool in agent.tools)
            for forbidden in ("paper_execute", "run_decision_cycle", "check_risk", "finalize_paper_cycle"):
                self.assertNotIn(forbidden, tools)
        for agent in (trader_agent, reviewer_agent, root_agent):
            self.assertIs(agent.before_model_callback, before_model_cost)
            self.assertIs(agent.after_model_callback, after_model_cost)
            self.assertIs(agent.on_model_error_callback, on_model_cost_error)
        from chrysopoeia.agent import context_agent
        self.assertIs(context_agent.before_model_callback, before_model_cost)
        self.assertIs(context_agent.after_model_callback, after_model_cost)
        self.assertIs(context_agent.on_model_error_callback, on_model_cost_error)
        self.assertFalse(hasattr(paper_cycle_workflow, "before_model_callback"))

    def test_review_reason_is_bounded_actionable_output(self) -> None:
        self.assertEqual(ReviewOutput.model_fields["reason"].metadata[1].max_length, 500)
        with self.assertRaises(ValidationError):
            ReviewOutput(
                snapshot_id="snapshot-1", market_id="market-1", approved=False, reason="x" * 501,
            )


if __name__ == "__main__":
    unittest.main()
