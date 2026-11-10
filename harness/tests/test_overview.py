import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import cast

from chrysopoeia.accounting import (
    admit_turn,
    cycle_turn_id,
    finish_turn,
    open_session,
    record_turn_outcome,
)
from chrysopoeia.overview import render_human, summarize_journals
from chrysopoeia.paper_cycle import build_turn_outcome


def _abstained_outcome(market_id: str, probability: float) -> dict[str, object]:
    return build_turn_outcome(
        proposal={
            "snapshot_id": f"snapshot-{market_id}",
            "market_id": market_id,
            "action": "abstain",
            "probability": probability,
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
        created_at="2026-11-08T10:00:00+00:00",
        trade_plan_event_id=None,
        model_cost_usd="0.25",
        evidence=[],
        research={
            "status": "unavailable",
            "reason": "no grounding",
            "query_count": 0,
        },
    )


class OverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary)

    def location(self, name: str) -> Path:
        directory = self.temporary / name
        directory.mkdir()
        return directory

    def test_failed_and_decided_turns_are_summarized(self) -> None:
        stem = self.location("failed")
        open_session(
            stem,
            1000.0,
            100.0,
            target_win_rate=0.5,
            window_end=datetime.fromisoformat("2026-11-07T21:14:42+00:00"),
        )
        admit_turn(stem, "t-failed", "snap-1", "111")
        finish_turn(stem, "t-failed", "failed", model_cost_usd="1.43376")
        scored = self.location("scored")
        open_session(
            scored,
            500.0,
            50.0,
            target_win_rate=0.5,
            window_end=datetime.fromisoformat("2099-01-01T00:00:00+00:00"),
        )
        admit_turn(scored, cycle_turn_id("snapshot-222", "222"), "snapshot-222", "222")
        record_turn_outcome(scored, _abstained_outcome("222", 0.4))
        finish_turn(
            scored,
            cycle_turn_id("snapshot-222", "222"),
            "abstained",
            model_cost_usd="0.25",
        )

        report = summarize_journals(
            [stem, scored], now=datetime.fromisoformat("2026-11-08T10:00:00+00:00")
        )

        self.assertEqual(report["totals"]["journals"], 2)
        self.assertEqual(report["totals"]["forecast_samples"], 1)
        self.assertEqual(report["totals"]["failed_turns"], 1)
        self.assertEqual(report["totals"]["open_turns"], 0)
        self.assertEqual(report["totals"]["booked_model_cost_usd"], "1.68376")
        per_journal = cast("list[dict[str, object]]", report["journals"])
        failed, forecast = per_journal[0], per_journal[1]
        self.assertTrue(failed["expired"])
        self.assertEqual(failed["turns"]["failed"], 1)
        self.assertFalse(forecast["expired"])
        self.assertEqual(forecast["scored_forecasts"], 1)
        forecast_entry = forecast["forecasts"][0]
        self.assertEqual(forecast_entry["status"], "abstained")
        self.assertEqual(forecast_entry["probability"], 0.4)

        rendered = render_human(report)
        self.assertIn("failed 1", rendered)
        self.assertIn("forecast samples 1", rendered)
        self.assertIn("market 222", rendered)

    def test_empty_journal_renders_without_changes(self) -> None:
        empty = self.location("empty")
        report = summarize_journals([empty])
        self.assertEqual(report["totals"]["booked_model_cost_usd"], "0")
        self.assertEqual(report["journals"][0]["session_status"], "empty")
        self.assertEqual(
            render_human(report), render_human(json.loads(json.dumps(report)))
        )


if __name__ == "__main__":
    unittest.main()
