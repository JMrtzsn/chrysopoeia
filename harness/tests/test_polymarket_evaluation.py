import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from chrysopoeia.polymarket import HistoricalPrice, PolymarketError, ResolvedMarket
from chrysopoeia.polymarket_evaluation import brier_score, evaluate_journal


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)


def turn(market_id: str, seconds: int, probability: float, action: str, slug: str) -> dict:
    return {
        "market_id": market_id,
        "created_at": at(seconds).isoformat(),
        "evidence": [{"url": f"https://polymarket.com/event/{slug}"}],
        "proposal": {"action": action, "probability": probability},
    }


MARKETS = {
    "1": ResolvedMarket("1", "btc-updown-5m-1000", at(1300), True, "11"),
    "2": ResolvedMarket("2", "fed-holds-rates", at(5000), False, "21"),
    "3": ResolvedMarket("3", "btc-updown-5m-1300", at(1600), None, "31"),
}


def load_market(market_id: str) -> ResolvedMarket:
    if market_id not in MARKETS:
        raise PolymarketError("unknown")
    return MARKETS[market_id]


def load_prices(token_id: str, start: datetime, end: datetime):
    return (HistoricalPrice(int(end.timestamp()) - 10, {"11": 0.6, "21": 0.4}[token_id]),)


class PolymarketEvaluationTests(unittest.TestCase):
    def evaluate(self, turns: dict, **kwargs) -> dict:
        with patch(
            "chrysopoeia.polymarket_evaluation.accounting.replay",
            return_value=SimpleNamespace(turn_outcomes=turns),
        ):
            return evaluate_journal(
                Path("unused"), load_market=load_market, load_prices=load_prices, **kwargs
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

    def test_scores_any_binary_market_including_abstentions(self) -> None:
        result = self.evaluate(
            {
                "a": turn("1", 1100, 0.8, "trade", "btc-updown-5m-1000"),
                "b": turn("2", 1200, 0.2, "abstain", "fed-holds-rates"),
                "c": turn("3", 1400, 0.5, "trade", "btc-updown-5m-1300"),
            }
        )
        self.assertEqual(result["scored_markets"], 2)
        self.assertEqual(result["pending_markets"], 1)
        self.assertAlmostEqual(result["agent"]["brier_score"], 0.04)
        self.assertEqual(result["agent"]["trades"], 1)
        self.assertEqual(result["agent"]["trade_coverage"], 0.5)
        self.assertAlmostEqual(result["market_baseline"]["market_brier"], 0.16)
        self.assertAlmostEqual(result["market_baseline"]["agent_improvement"], 0.12)

    def test_series_filter_first_forecast_and_late_forecasts(self) -> None:
        result = self.evaluate(
            {
                "a": turn("1", 1100, 0.8, "trade", "btc-updown-5m-1000"),
                "a2": turn("1", 1150, 0.1, "trade", "btc-updown-5m-1000"),
                "b": turn("2", 6000, 0.2, "trade", "fed-holds-rates"),
            },
            series_url="https://polymarket.com/event/btc-updown-5m-1792212300",
        )
        self.assertEqual(result["series_filter"], "btc-updown-5m-")
        self.assertEqual(result["scored_markets"], 1)
        self.assertEqual(result["repeated_forecasts_ignored"], 1)
        self.assertAlmostEqual(result["agent"]["brier_score"], 0.04)

        late = self.evaluate({"b": turn("2", 6000, 0.2, "trade", "fed-holds-rates")})
        self.assertEqual(late["scored_markets"], 0)
        self.assertEqual(late["late_forecasts_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
