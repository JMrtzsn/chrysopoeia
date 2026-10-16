import json
import unittest
from datetime import datetime, timezone

from chrysopoeia.financial_analysis import (
    Candle,
    analyze_history,
    crypto_history,
    stock_history,
)


def candles(count: int = 60) -> list[Candle]:
    start = 1_760_000_000
    return [
        Candle(start + index * 86_400, 100 + index, 102 + index, 99 + index, 101 + index, 10 + index)
        for index in range(count)
    ]


class FakeExchange:
    def __init__(self, rows):
        self.has = {"fetchOHLCV": True}
        self.timeframes = {"1d": "1d"}
        self.urls = {"www": "https://exchange.example"}
        self.rows = rows
        self.request = None
        self.closed = False

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.request = (symbol, timeframe, since, limit)
        return self.rows

    def close(self):
        self.closed = True


class FinancialAnalysisTests(unittest.TestCase):
    def test_indicators_are_deterministic_for_a_rising_series(self) -> None:
        result = analyze_history(
            {
                "symbol": "AAPL",
                "currency": "USD",
                "interval": "1d",
                "source": "fixture",
                "source_url": "https://example.com/data",
                "candles": candles(),
            }
        )
        self.assertEqual(result["bar_count"], 60)
        self.assertEqual(result["period_return_pct"], round((160 / 101 - 1) * 100, 6))
        self.assertEqual(result["sma_10"], 155.5)
        self.assertEqual(result["rsi_14_simple"], 100.0)
        stochastic = result["stochastic_14_k"]
        self.assertTrue(isinstance(stochastic, float) and stochastic > 0.0)
        self.assertEqual(len(result["recent_candles"]), 5)
        self.assertIn("not a forecast", result["interpretation"])

    def test_stock_provider_parses_bounded_yahoo_chart_response(self) -> None:
        series = candles(20)
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL", "currency": "USD"},
                        "timestamp": [c.timestamp for c in series],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [c.open for c in series],
                                    "high": [c.high for c in series],
                                    "low": [c.low for c in series],
                                    "close": [c.close for c in series],
                                    "volume": [c.volume for c in series],
                                }
                            ]
                        },
                    }
                ]
            }
        }
        requests = []

        def fetch(url, timeout, max_bytes):
            requests.append((url, timeout, max_bytes))
            return json.dumps(payload).encode()

        result = stock_history("AAPL", limit=20, fetch=fetch)
        self.assertEqual(len(result["candles"]), 20)
        self.assertEqual(result["symbol"], "AAPL")
        self.assertIn("query1.finance.yahoo.com", requests[0][0])
        self.assertLessEqual(requests[0][2], 1_000_000)

    def test_crypto_provider_uses_ccxt_public_ohlcv_without_credentials(self) -> None:
        source = candles(20)
        rows = [
            [c.timestamp * 1000, c.open, c.high, c.low, c.close, c.volume]
            for c in reversed(source)
        ]
        exchange = FakeExchange(rows)
        config = []

        def factory(exchange_id, values):
            config.append((exchange_id, values))
            return exchange

        history = crypto_history(
            "coinbase",
            "BTC/USD",
            interval="1d",
            limit=20,
            exchange_factory=factory,
            now=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(history["symbol"], "BTC/USD")
        self.assertEqual(len(history["candles"]), 20)
        self.assertEqual(history["candles"][0].timestamp, source[0].timestamp)
        self.assertEqual(exchange.request[0:2], ("BTC/USD", "1d"))
        self.assertEqual(exchange.request[3], 20)
        self.assertTrue(config[0][1]["enableRateLimit"])
        self.assertNotIn("apiKey", config[0][1])
        self.assertTrue(exchange.closed)

    def test_rejects_bad_symbols_limits_and_timeframes_before_fetch(self) -> None:
        called = False

        def fetch(*_args):
            nonlocal called
            called = True
            return b""

        def exchange_factory(_exchange_id, _config):
            nonlocal called
            called = True
            return FakeExchange([])

        with self.assertRaises(ValueError):
            stock_history("../AAPL", fetch=fetch)
        with self.assertRaises(ValueError):
            stock_history("AAPL", limit=201, fetch=fetch)
        with self.assertRaises(ValueError):
            crypto_history(
                "coinbase", "BTC/USD", interval="3m", exchange_factory=exchange_factory
            )
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
