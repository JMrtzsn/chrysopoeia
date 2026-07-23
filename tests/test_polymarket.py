import json
import unittest
from datetime import datetime, timezone
from urllib.error import URLError

from chrysopoeia.polymarket import PolymarketError, load_market_snapshot


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def market(**changes: object) -> bytes:
    value = {
        "id": "12345",
        "slug": "will-it-rain",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-token", "no-token"]',
        "bestAsk": "0.42",
        "updatedAt": "2026-07-21T11:58:00Z",
    }
    value.update(changes)
    return json.dumps(value).encode()


class PolymarketAdapterTests(unittest.TestCase):
    def test_active_binary_market_becomes_snapshot(self) -> None:
        calls: list[tuple[str, float, int]] = []

        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            calls.append((url, timeout, max_bytes))
            return market()

        snapshot = load_market_snapshot(
            "https://polymarket.com/event/weather/will-it-rain",
            bankroll=1_000,
            market_exposure=4,
            total_exposure=20,
            snapshot_id="snapshot-1",
            now=NOW,
            fetch=fetch,
        )

        self.assertEqual(snapshot.market_id, "12345")
        self.assertEqual(snapshot.price, 0.42)
        self.assertEqual((snapshot.bankroll, snapshot.market_exposure, snapshot.total_exposure), (1_000, 4, 20))
        self.assertEqual(snapshot.snapshot_id, "snapshot-1")
        self.assertEqual(calls[0][0], "https://gamma-api.polymarket.com/markets/slug/will-it-rain")
        self.assertGreater(calls[0][1], 0)
        self.assertGreater(calls[0][2], 0)

    def test_identifier_resolves_and_generated_snapshot_id_is_stable(self) -> None:
        urls: list[str] = []

        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            urls.append(url)
            return market()

        first = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch)
        second = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch)

        self.assertEqual(urls, ["https://gamma-api.polymarket.com/markets/12345"] * 2)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertTrue(first.snapshot_id.startswith("polymarket-"))

    def test_invalid_inputs_reject_before_io(self) -> None:
        def unexpected_fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            self.fail("fetch must not be called")

        for value in ("", "../markets", "abc?x=1", "https://evil.example/event/x", "https://polymarket.com/", "https://polymarket.com:bad/event/x", "https://user:pass@polymarket.com/event/x"):
            with self.subTest(value=value), self.assertRaises(PolymarketError):
                load_market_snapshot(value, 1_000, 0, 0, now=NOW, fetch=unexpected_fetch)

        with self.assertRaises(PolymarketError):
            load_market_snapshot("12345", 1_000, 0, 0, snapshot_id="", now=NOW, fetch=lambda *_: market())

    def test_invalid_market_responses_are_rejected(self) -> None:
        cases = (
            (market(active=False), "inactive"),
            (market(closed=True), "closed"),
            (market(acceptingOrders=False), "orders"),
            (market(updatedAt="2026-07-21T11:54:59Z"), "stale"),
            (b"not json", "JSON"),
            (json.dumps([]).encode(), "schema"),
            (market(outcomes='["A", "B", "C"]', clobTokenIds='["a", "b", "c"]'), "binary"),
            (market(outcomes='["No", "Yes"]'), "YES"),
            (market(clobTokenIds='["yes-token"]'), "token"),
            (market(bestAsk=None), "price"),
            (market(bestAsk="nan"), "price"),
            (market(bestAsk="1"), "price"),
        )
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(PolymarketError, message):
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=lambda *_: body)

    def test_oversized_and_network_failures_are_safe(self) -> None:
        with self.assertRaisesRegex(PolymarketError, "too large"):
            load_market_snapshot("12345", 1_000, 0, 0, now=NOW, max_response_bytes=20, fetch=lambda *_: market())

        secret = "super-secret-response"
        for failure in (TimeoutError(secret), URLError(secret)):
            def fail(*_: object, failure: BaseException = failure) -> bytes:
                raise failure

            with self.subTest(failure=failure), self.assertRaises(PolymarketError) as raised:
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fail)
            self.assertNotIn(secret, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
