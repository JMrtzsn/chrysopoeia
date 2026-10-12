import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from jsonschema import Draft202012Validator, FormatChecker

from chrysopoeia.accounting import (
    admit_turn,
    cycle_turn_id,
    enqueue_event,
    open_session,
    pending_events,
    record_turn_outcome,
    replay,
)
from chrysopoeia.events import drain
from chrysopoeia.paper_cycle import build_turn_outcome, validate_turn_outcome


class TurnOutcomeTests(unittest.TestCase):
    def outcome(self) -> dict[str, object]:
        return build_turn_outcome(
            proposal={
                "snapshot_id": "snapshot-1",
                "market_id": "123",
                "action": "abstain",
                "probability": 0.4,
                "amount": 0.0,
                "max_entry_price": None,
                "exit_plan": None,
                "citations": [],
                "rationale": "No reliable edge.",
            },
            review=None,
            policy=None,
            status="abstained",
            reason="trader_abstained",
            created_at="2026-10-09T00:00:00+00:00",
            trade_plan_event_id=None,
            model_cost_usd="0.25",
        )

    def test_every_decided_status_conforms_to_shared_schema(self) -> None:
        schema = json.loads(
            Path(__file__)
            .parents[2]
            .joinpath("contracts", "turn_outcome.v1.schema.json")
            .read_text()
        )
        proposal = {
            "snapshot_id": "snapshot-1",
            "market_id": "123",
            "action": "trade",
            "probability": 0.6,
            "amount": 5.0,
            "max_entry_price": 0.5,
            "exit_plan": {
                "take_profit_roi": 0.1,
                "stop_loss_roi": -0.2,
                "exit_by": "2026-10-09T12:00:00+00:00",
                "hold_to_resolution": False,
            },
            "citations": ["evidence"],
            "rationale": "Evidence supports a six-in-ten probability.",
        }
        review = {
            "snapshot_id": "snapshot-1",
            "market_id": "123",
            "approved": True,
            "reason": "The evidence and limits support the plan.",
            "citations": ["evidence"],
        }
        cases = {
            "abstained": (None, None, None),
            "plan_check_rejected": (None, None, None),
            "reviewer_rejected": (
                {
                    **review,
                    "approved": False,
                    "reason": "Evidence is weak.",
                    "citations": [],
                },
                {"allowed": False, "reason": "review rejected: Evidence is weak."},
                None,
            ),
            "policy_rejected": (
                review,
                {"allowed": False, "reason": "minimum net edge of 0.05 not met"},
                None,
            ),
            "plan_ready": (
                review,
                {
                    "allowed": True,
                    "reason": "approved by review and deterministic risk policy",
                },
                cycle_turn_id("snapshot-1", "123"),
            ),
        }
        validator = Draft202012Validator(schema, format_checker=FormatChecker())

        for status, (case_review, policy, trade_event_id) in cases.items():
            with self.subTest(status=status):
                selected = proposal
                if status == "abstained":
                    selected = {
                        **proposal,
                        "action": "abstain",
                        "amount": 0.0,
                        "max_entry_price": None,
                        "exit_plan": None,
                        "citations": [],
                    }
                outcome = build_turn_outcome(
                    proposal=selected,
                    review=case_review,
                    policy=policy,
                    status=status,
                    reason=status,
                    created_at="2026-10-09T00:00:00+00:00",
                    trade_plan_event_id=trade_event_id,
                    model_cost_usd="0.25",
                )
                validator.validate(outcome)
                self.assertEqual(
                    outcome["proposal"]["rationale"], selected["rationale"]
                )
                self.assertEqual(
                    outcome["review"]["reason"] if outcome["review"] else None,
                    case_review["reason"] if case_review else None,
                )

    def test_outcome_integrity_rejects_tampering_and_inconsistent_status(self) -> None:
        outcome = self.outcome()
        outcome["event_id"] = "outcome-tampered"

        with self.assertRaises(ValueError):
            validate_turn_outcome(outcome)
        with self.assertRaises(ValueError):
            build_turn_outcome(
                proposal={
                    "snapshot_id": "snapshot-1",
                    "market_id": "123",
                    "action": "trade",
                    "probability": 0.6,
                    "amount": 5.0,
                    "max_entry_price": 0.5,
                    "exit_plan": {
                        "take_profit_roi": 0.1,
                        "stop_loss_roi": -0.2,
                        "exit_by": "2026-10-09T12:00:00+00:00",
                        "hold_to_resolution": False,
                    },
                    "citations": ["evidence"],
                    "rationale": "Evidence supports the trade.",
                },
                review=None,
                policy={"allowed": True, "reason": "approved"},
                status="plan_ready",
                reason="plan_ready",
                created_at="2026-10-09T00:00:00+00:00",
                trade_plan_event_id=cycle_turn_id("snapshot-1", "123"),
                model_cost_usd="0.25",
            )

    def test_journal_records_outcome_without_sink_and_replay_is_idempotent(
        self,
    ) -> None:
        directory = Path(tempfile.mkdtemp())
        outcome = self.outcome()
        open_session(directory, 1_000, 100)
        admit_turn(directory, str(outcome["turn_id"]), "snapshot-1", "123")

        record_turn_outcome(directory, outcome)
        record_turn_outcome(directory, outcome)

        self.assertEqual(replay(directory).turn_outcomes[outcome["turn_id"]], outcome)

    def test_single_sink_drains_all_event_types_in_journal_order(self) -> None:
        outcome = self.outcome()
        trade_plan = {
            "schema_version": 1,
            "record_type": "trade_plan_ready",
            "event_id": cycle_turn_id("snapshot-2", "456"),
            "created_at": "2026-10-09T00:00:00+00:00",
            "market_id": "456",
            "snapshot_id": "snapshot-2",
            "instrument_id": "yes-token",
            "outcome": "YES",
            "probability": 0.6,
            "stake": 4.0,
            "max_entry_price": 0.5,
            "exit_plan": {
                "take_profit_roi": 0.1,
                "stop_loss_roi": -0.2,
                "exit_by": "2026-10-09T12:00:00+00:00",
                "hold_to_resolution": False,
            },
            "reviewer_approved": True,
            "reviewer_citations": ["evidence"],
            "policy_references": ["hard-policy-v1"],
            "evidence_references": ["evidence"],
            "expires_at": "2026-10-10T00:00:00+00:00",
            "market_end": "2026-10-10T00:00:00+00:00",
        }
        sink = "pubsub:projects/p/topics/events"

        directory = Path(tempfile.mkdtemp())
        enqueue_event(directory, trade_plan)
        enqueue_event(directory, outcome)
        sender = Mock()

        drain(directory, sink, sender=sender)

        self.assertEqual(
            sender.call_args_list,
            [call(sink, trade_plan), call(sink, outcome)],
        )
        self.assertEqual(pending_events(directory), [])


if __name__ == "__main__":
    unittest.main()
