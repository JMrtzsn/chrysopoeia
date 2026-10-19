import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from chrysopoeia.trading import BookLevel, MarketSnapshot
from chrysopoeia.window_baseline import (
    baseline_evidence,
    estimate_up_probability,
    window_metrics,
)

END = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
START = END - timedelta(minutes=5)


CLOSES = [100 + index * 0.1 for index in range(20)]


def candles(closes: list[float], first: datetime = START - timedelta(minutes=15)):
    return [
        SimpleNamespace(
            timestamp=(first + timedelta(minutes=index)).timestamp(),
            open=close - 0.05,
            close=close,
        )
        for index, close in enumerate(closes)
    ]


def snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        "snap",
        "5866061",
        0.5,
        1000,
        0,
        0,
        end_time=END.isoformat(),
        captured_at=(START + timedelta(minutes=2)).isoformat(),
        source_url="https://polymarket.com/event/btc-updown-5m-1",
        yes_token_id="yes",
        asks=(BookLevel(0.5, 100),),
        fee_rate=0.02,
        fee_source="paper-assumption:flat-2pct-v1",
        question="Bitcoin Up or Down?",
        resolution_rules="Resolves from the published window outcome.",
        book_captured_at=(START + timedelta(minutes=2)).isoformat(),
    )


class WindowBaselineTests(unittest.TestCase):
    def test_probability_is_neutral_at_the_open_and_monotonic_in_price(self) -> None:
        self.assertEqual(estimate_up_probability(100, 100, 120, 0.001), 0.5)
        up = estimate_up_probability(100, 100.05, 120, 0.01)
        more_up = estimate_up_probability(100, 100.1, 120, 0.01)
        down = estimate_up_probability(100, 99.95, 120, 0.01)
        self.assertGreater(up, 0.5)
        self.assertGreater(more_up, up)
        self.assertLess(down, 0.5)
        self.assertLessEqual(estimate_up_probability(100, 200, 120, 0.001), 0.99)
        self.assertGreaterEqual(estimate_up_probability(100, 1, 120, 0.001), 0.01)

    def test_probability_is_less_extreme_with_more_time_remaining(self) -> None:
        early = estimate_up_probability(100, 100.05, 240, 0.01)
        late = estimate_up_probability(100, 100.05, 30, 0.01)
        self.assertGreater(late, early)

    def test_metrics_use_the_window_open_and_remaining_time(self) -> None:
        metrics = window_metrics(
            candles(CLOSES),
            START,
            START + timedelta(minutes=2),
            END,
            latest=CLOSES[17] + 0.3,
        )

        self.assertAlmostEqual(float(metrics["open"]), CLOSES[15] - 0.05)
        self.assertAlmostEqual(float(metrics["last"]), CLOSES[17] + 0.3)
        self.assertAlmostEqual(float(metrics["seconds_remaining"]), 180)
        self.assertGreater(float(metrics["delta_bps"]), 0)
        self.assertGreater(float(metrics["minute_vol"]), 0)
        self.assertGreater(float(metrics["model_p_up"]), 0.5)

    def test_insufficient_history_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            window_metrics(candles([100, 101]), START, START + timedelta(minutes=1), END)

    def test_baseline_evidence_is_snapshot_bound_and_citable(self) -> None:
        def history(*_: object, **__: object) -> dict[str, object]:
            return {
                "candles": candles(CLOSES),
                "source_url": "https://www.bitstamp.net/api/?market=BTC/USD",
            }

        evidence = baseline_evidence(
            snapshot(), now=START, history=history, ticker=lambda: 100.9
        )

        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence.snapshot_id, "snap")
        self.assertEqual(evidence.source_kind, "external")
        self.assertIn("baseline_p_up=", evidence.excerpt or "")

    def test_baseline_evidence_is_optional_when_history_is_unavailable(self) -> None:
        def failing(*_: object, **__: object) -> dict[str, object]:
            raise OSError("exchange unavailable")

        self.assertIsNone(
            baseline_evidence(
                snapshot(), now=START, history=failing, ticker=lambda: 100.0
            )
        )

    def test_baseline_evidence_is_optional_when_the_ticker_is_unavailable(self) -> None:
        def history(*_: object, **__: object) -> dict[str, object]:
            return {
                "candles": candles(CLOSES),
                "source_url": "https://www.bitstamp.net/api/?market=BTC/USD",
            }

        def failing() -> float:
            raise ValueError("ticker unavailable")

        self.assertIsNone(
            baseline_evidence(snapshot(), now=START, history=history, ticker=failing)
        )


if __name__ == "__main__":
    unittest.main()
