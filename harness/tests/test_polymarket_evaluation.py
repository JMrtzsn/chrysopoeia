import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from chrysopoeia.polymarket import (
    HistoricalPrice,
    PolymarketSeriesHistory,
    SeriesOutcome,
)
from chrysopoeia.polymarket_evaluation import brier_score, evaluate_journal


class PolymarketEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.anchor = "https://polymarket.com/event/btc-updown-5m-1000"
        self.first_start = datetime.fromtimestamp(1000, timezone.utc)
        self.second_start = datetime.fromtimestamp(1300, timezone.utc)
        self.history = PolymarketSeriesHistory(
            "10684",
            "btc-up-or-down-5m",
            "https://gamma-api.polymarket.com/events?series_id=10684",
            (
                SeriesOutcome(
                    "1", "btc-updown-5m-1000", "BTC Up or Down",
                    self.first_start, datetime.fromtimestamp(1300, timezone.utc),
                    datetime.fromtimestamp(1301, timezone.utc), True, "11", "12",
                    "https://data.chain.link/btc",
                ),
                SeriesOutcome(
                    "2", "btc-updown-5m-1300", "BTC Up or Down",
                    self.second_start, datetime.fromtimestamp(1600, timezone.utc),
                    datetime.fromtimestamp(1601, timezone.utc), False, "21", "22",
                    "https://data.chain.link/btc",
                ),
            ),
        )

    def test_brier_score_rewards_probabilities_close_to_outcomes(self) -> None:
        score = brier_score([0.8, 0.2], [True, False])
        if score is None:
            self.fail("score missing")
        self.assertAlmostEqual(score, 0.04)
        self.assertEqual(brier_score([0.5, 0.5], [True, False]), 0.25)
        self.assertIsNone(brier_score([], []))
        with self.assertRaises(ValueError):
            brier_score([0.2], [True, False])

    def test_evaluation_compares_agent_and_clob_at_each_forecast_time(self) -> None:
        turns = {
            "t1": {
                "market_id": "1",
                "created_at": datetime.fromtimestamp(1100, timezone.utc).isoformat(),
                "status": "plan_ready",
                "evidence": [{"url": self.anchor}],
                "proposal": {"action": "trade", "probability": 0.8},
            },
            "t2": {
                "market_id": "2",
                "created_at": datetime.fromtimestamp(1400, timezone.utc).isoformat(),
                "status": "plan_ready",
                "evidence": [{"url": "https://polymarket.com/event/btc-updown-5m-1300"}],
                "proposal": {"action": "trade", "probability": 0.2},
            },
        }
        calls: list[tuple[str, datetime, datetime]] = []

        def load_prices(token_id: str, start: datetime, end: datetime):
            calls.append((token_id, start, end))
            p = {"11": 0.6, "21": 0.4}[token_id]
            return (HistoricalPrice(int(end.timestamp()) - 10, p),)

        with (
            patch("chrysopoeia.polymarket_evaluation.accounting.replay", return_value=SimpleNamespace(turn_outcomes=turns)),
            patch("chrysopoeia.polymarket_evaluation.load_series_history", return_value=self.history),
        ):
            result = evaluate_journal(
                Path("unused"),
                self.anchor,
                limit=2,
                load_prices=load_prices,
            )

        self.assertEqual(result["metric"], "brier_score")
        self.assertEqual(result["agent"]["samples"], 2)
        self.assertAlmostEqual(result["agent"]["brier_score"], 0.04)
        self.assertAlmostEqual(result["market_baseline"]["brier_score"], 0.16)
        self.assertAlmostEqual(result["market_baseline"]["agent_improvement"], 0.12)
        self.assertEqual([call[0] for call in calls], ["11", "21"])

    def test_evaluation_scores_abstentions_and_excludes_out_of_window(self) -> None:
        turns = {
            "abstain": {
                "market_id": "1",
                "created_at": datetime.fromtimestamp(1100, timezone.utc).isoformat(),
                "evidence": [{"url": self.anchor}],
                "proposal": {"action": "abstain", "probability": 0.7},
            },
            "late": {
                "market_id": "1",
                "created_at": datetime.fromtimestamp(1500, timezone.utc).isoformat(),
                "evidence": [{"url": self.anchor}],
                "proposal": {"action": "trade", "probability": 0.7},
            },
        }
        with (
            patch("chrysopoeia.polymarket_evaluation.accounting.replay", return_value=SimpleNamespace(turn_outcomes=turns)),
            patch("chrysopoeia.polymarket_evaluation.load_series_history", return_value=self.history),
            patch("chrysopoeia.polymarket_evaluation.load_price_history", return_value=()),
        ):
            result = evaluate_journal(Path("unused"), self.anchor, limit=2)

        self.assertEqual(result["agent"]["samples"], 1)
        self.assertAlmostEqual(result["agent"]["brier_score"], 0.09)
        self.assertEqual(result["agent"]["trades"], 0)
        self.assertEqual(result["agent"]["trade_coverage"], 0.0)
        self.assertEqual(result["agent"]["abstentions_in_loaded_windows"], 1)
        self.assertEqual(result["agent"]["out_of_window_forecasts"], 1)


if __name__ == "__main__":
    unittest.main()
