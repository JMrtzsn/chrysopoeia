import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call

from jsonschema import Draft202012Validator, FormatChecker

from chrysopoeia.accounting import (
    admit_turn,
    append_record,
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
            evidence=[],
            research={
                "status": "unavailable",
                "reason": "no grounding",
                "query_count": 0,
            },
        )

    def test_context_attributed_outcome_with_reservation_uses_the_v4_contract(
        self,
    ) -> None:
        outcome = build_turn_outcome(
            **self._context_outcome_arguments(),
            reserved_model_cost_usd="0.75",
        )
        schema = json.loads(
            Path(__file__)
            .parents[2]
            .joinpath("contracts", "turn_outcome.v4.schema.json")
            .read_text()
        )

        Draft202012Validator(schema, format_checker=FormatChecker()).validate(outcome)
        self.assertEqual(outcome["schema_version"], 4)
        self.assertEqual(outcome["reserved_model_cost_usd"], 0.75)
        self.assertEqual(validate_turn_outcome(outcome), outcome)

    def test_context_attributed_outcome_without_reservation_remains_v3(self) -> None:
        outcome = build_turn_outcome(**self._context_outcome_arguments())

        self.assertEqual(outcome["schema_version"], 3)
        self.assertNotIn("reserved_model_cost_usd", outcome)
        self.assertEqual(validate_turn_outcome(outcome), outcome)
        v4 = build_turn_outcome(
            **self._context_outcome_arguments(), reserved_model_cost_usd="0.10"
        )
        self.assertEqual(v4["event_id"], outcome["event_id"])
        self.assertEqual(v4["turn_id"], outcome["turn_id"])
        self.assertEqual(
            (v4["model_cost_usd"], v4["reserved_model_cost_usd"]), (0.25, 0.1)
        )

    def test_reservation_requires_context_and_is_strictly_validated(self) -> None:
        for invalid in ("bad", "-0.01", "NaN", "Infinity"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_turn_outcome(
                    **self._context_outcome_arguments(),
                    reserved_model_cost_usd=invalid,
                )
            tampered = build_turn_outcome(
                **self._context_outcome_arguments(), reserved_model_cost_usd="0.75"
            )
            tampered["reserved_model_cost_usd"] = invalid
            with self.subTest(serialized=invalid), self.assertRaises(ValueError):
                validate_turn_outcome(tampered)

        context_free = self._context_outcome_arguments()
        context_free["context"] = None
        with self.assertRaises(ValueError):
            build_turn_outcome(**context_free, reserved_model_cost_usd="0.75")

        outcome = build_turn_outcome(
            **self._context_outcome_arguments(), reserved_model_cost_usd="0.75"
        )
        outcome["schema_version"] = 3
        with self.assertRaises(ValueError):
            validate_turn_outcome(outcome)

        missing = build_turn_outcome(
            **self._context_outcome_arguments(), reserved_model_cost_usd="0.75"
        )
        missing.pop("reserved_model_cost_usd")
        with self.assertRaises(ValueError):
            validate_turn_outcome(missing)

    def _context_outcome_arguments(self) -> dict[str, object]:
        return {
            "proposal": {
                "snapshot_id": "snapshot-context",
                "market_id": "123",
                "action": "abstain",
                "probability": 0.4,
                "amount": 0.0,
                "max_entry_price": None,
                "exit_plan": None,
                "citations": [],
                "rationale": "No reliable edge.",
            },
            "review": None,
            "policy": None,
            "status": "abstained",
            "reason": "trader_abstained",
            "created_at": "2026-10-09T00:00:00+00:00",
            "trade_plan_event_id": None,
            "model_cost_usd": "0.25",
            "context": {
                "scope_key": "polymarket:series:btc-updown-5m",
                "profile_id": "crypto.btcusd.5m.updown",
                "profile_version": 1,
                "manifest_hash": "a" * 64,
            },
        }

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
                    evidence=[
                        {
                            "evidence_id": "evidence",
                            "url": "https://example.com/report",
                            "title": "Report",
                            "source_kind": "external",
                            "excerpt": "Supporting text",
                        }
                    ],
                    research={"status": "ok", "reason": None, "query_count": 1},
                    plan_checks=(
                        [
                            {
                                "passed": False,
                                "reasons": ["minimum edge not met"],
                                "plan": selected,
                            }
                        ]
                        if status == "plan_check_rejected"
                        else []
                    ),
                )
                validator.validate(outcome)
                self.assertEqual(
                    len(outcome["plan_checks"]),
                    1 if status == "plan_check_rejected" else 0,
                )
                self.assertEqual(
                    outcome["proposal"]["rationale"], selected["rationale"]
                )
                self.assertEqual(
                    outcome["review"]["reason"] if outcome["review"] else None,
                    case_review["reason"] if case_review else None,
                )
                self.assertEqual(outcome["research"]["query_count"], 1)
                self.assertEqual(outcome["evidence"][0]["evidence_id"], "evidence")

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
                evidence=[],
                research={
                    "status": "unavailable",
                    "reason": "no grounding",
                    "query_count": 0,
                },
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

    def test_v4_outcome_uses_canonical_journal_and_outbox_paths(self) -> None:
        directory = Path(tempfile.mkdtemp())
        outcome = build_turn_outcome(
            **self._context_outcome_arguments(), reserved_model_cost_usd="0.75"
        )
        open_session(directory, 1_000, 100)
        admit_turn(directory, str(outcome["turn_id"]), "snapshot-context", "123")

        record_turn_outcome(directory, outcome)
        enqueue_event(directory, outcome)

        self.assertEqual(replay(directory).turn_outcomes[outcome["turn_id"]], outcome)
        self.assertEqual(pending_events(directory), [outcome])

    def test_validation_accepts_pre_plan_checks_v1_as_empty_history(self) -> None:
        legacy = self.outcome()
        legacy.pop("plan_checks")
        legacy.pop("evidence")
        legacy.pop("research")

        validated = validate_turn_outcome(legacy)

        self.assertEqual(validated["plan_checks"], [])
        self.assertEqual(validated["evidence"], [])
        self.assertEqual(
            validated["research"],
            {"status": "unavailable", "reason": "legacy outcome", "query_count": 0},
        )

    def test_replay_accepts_recorded_pre_plan_checks_v1(self) -> None:
        directory = Path(tempfile.mkdtemp())
        legacy = self.outcome()
        legacy.pop("plan_checks")
        open_session(directory, 1_000, 100)
        admit_turn(directory, str(legacy["turn_id"]), "snapshot-1", "123")
        append_record(directory, "turn_outcome_recorded", {"outcome_event": legacy})

        replayed = replay(directory).turn_outcomes[legacy["turn_id"]]

        self.assertEqual(replayed["plan_checks"], [])

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
