import json
import unittest
from dataclasses import asdict
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from chrysopoeia.trading import (
    ExitPlan,
    MarketSnapshot,
    Proposal,
    Review,
    run_decision_cycle,
)


class TradePlanSchemaTests(unittest.TestCase):
    def test_produced_event_conforms_to_shared_v1_schema(self) -> None:
        root = Path(__file__).parents[2]
        schema = json.loads(
            root.joinpath("contracts", "trade_plan_ready.v1.schema.json").read_text()
        )
        snapshot = MarketSnapshot(
            "snapshot",
            "123",
            0.4,
            1000,
            0,
            0,
            "Question?",
            "Rules",
            "2026-10-10T00:00:00+00:00",
            "2026-10-09T00:00:00+00:00",
            "https://polymarket.com/event/question",
            "yes-token",
            ({"price": 0.4, "size": 100},),
            book_captured_at="2026-10-09T00:00:00+00:00",
        )
        proposal = Proposal(
            "snapshot",
            "123",
            0.6,
            5,
            0.5,
            ExitPlan(0.1, -0.2, "2026-10-09T12:00:00+00:00"),
            ("evidence",),
        )
        event = run_decision_cycle(
            snapshot,
            proposal,
            Review("snapshot", "123", True, "approved", ("evidence",)),
        ).event

        serialized = json.loads(json.dumps(asdict(event)))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            serialized
        )


if __name__ == "__main__":
    unittest.main()
