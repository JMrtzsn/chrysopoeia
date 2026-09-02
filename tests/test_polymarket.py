import json
import unittest
from datetime import datetime, timezone
from urllib.error import URLError

from chrysopoeia.polymarket import PolymarketError, load_market_snapshot


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
FEE = {"paper_fee_rate": 0.02, "paper_fee_source": "paper-assumption:flat-2pct-v1"}


def market(**changes: object) -> bytes:
    value = {
        "id": "12345",
        "slug": "will-it-rain",
        "eventSlug": "will-it-rain",
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["yes-token", "no-token"]',
        "question": "Will it rain?",
        "description": "Resolves Yes if measurable rain is recorded by the named station.",
        "endDate": "2026-07-22T12:00:00Z",
        "updatedAt": "2026-07-21T11:58:00Z",
    }
    value.update(changes)
    return json.dumps(value).encode()


def book(**changes: object) -> bytes:
    value = {
        "asset_id": "yes-token",
        "timestamp": "1784635080000",
        "asks": [
            {"price": "0.44", "size": "10"},
            {"price": "0.42", "size": "20"},
        ],
        "bids": [{"price": "0.40", "size": "5"}],
    }
    value.update(changes)
    return json.dumps(value).encode()


def fixture_fetch(calls: list[tuple[str, float, int]] | None = None):
    def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
        if calls is not None:
            calls.append((url, timeout, max_bytes))
        return book() if url.startswith("https://clob.polymarket.com/book?") else market()
    return fetch


class PolymarketAdapterTests(unittest.TestCase):
    def test_active_binary_market_becomes_snapshot(self) -> None:
        calls: list[tuple[str, float, int]] = []

        snapshot = load_market_snapshot(
            "https://polymarket.com/event/weather/will-it-rain",
            bankroll=1_000,
            market_exposure=4,
            total_exposure=20,
            snapshot_id="snapshot-1",
            now=NOW,
            fetch=fixture_fetch(calls),
            **FEE,
        )

        self.assertEqual(snapshot.market_id, "12345")
        self.assertEqual(snapshot.price, 0.42)
        self.assertEqual((snapshot.bankroll, snapshot.market_exposure, snapshot.total_exposure), (1_000, 4, 20))
        self.assertEqual(snapshot.snapshot_id, "snapshot-1")
        self.assertEqual([call[0] for call in calls], [
            "https://gamma-api.polymarket.com/markets/slug/will-it-rain",
            "https://clob.polymarket.com/book?token_id=yes-token",
        ])
        self.assertGreater(calls[0][1], 0)
        self.assertGreater(calls[0][2], 0)
        self.assertEqual(snapshot.question, "Will it rain?")
        self.assertIn("measurable rain", snapshot.resolution_rules)
        self.assertEqual(snapshot.end_time, "2026-07-22T12:00:00+00:00")
        self.assertEqual(snapshot.captured_at, "2026-07-21T12:00:00+00:00")
        self.assertEqual(snapshot.source_url, "https://polymarket.com/event/will-it-rain")
        self.assertEqual(snapshot.yes_token_id, "yes-token")
        self.assertEqual([(level.price, level.size) for level in snapshot.asks], [(0.42, 20), (0.44, 10)])
        self.assertGreater(snapshot.fee_rate, 0)
        self.assertEqual(snapshot.fee_source, "paper-assumption:flat-2pct-v1")

    def test_identifier_resolves_and_generated_snapshot_id_is_stable(self) -> None:
        urls: list[str] = []

        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            urls.append(url)
            return book() if "clob.polymarket.com" in url else market()

        first = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)
        second = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

        self.assertEqual(urls, [
            "https://gamma-api.polymarket.com/markets/12345",
            "https://clob.polymarket.com/book?token_id=yes-token",
        ] * 2)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertTrue(first.snapshot_id.startswith("polymarket-"))

    def test_configured_fee_is_recorded_and_invalid_fee_rejects_before_io(self) -> None:
        snapshot = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW, fetch=fixture_fetch(),
            paper_fee_rate=0.03, paper_fee_source="paper-assumption:test-v1",
        )
        self.assertEqual((snapshot.fee_rate, snapshot.fee_source), (0.03, "paper-assumption:test-v1"))

        for fee, source in ((True, "source"), (float("nan"), "source"), (1, "source"), (0.1, "paper-assumption:no-fee-v1"), (0.1, "x" * 201)):
            with self.subTest(fee=fee, source=source), self.assertRaises(PolymarketError):
                load_market_snapshot(
                    "12345", 1_000, 0, 0, now=NOW,
                    fetch=lambda *_: self.fail("fetch must not be called"),
                    paper_fee_rate=fee, paper_fee_source=source,
                )

    def test_invalid_inputs_reject_before_io(self) -> None:
        def unexpected_fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            self.fail("fetch must not be called")

        for value in ("", "../markets", "abc?x=1", "https://evil.example/event/x", "https://polymarket.com/", "https://polymarket.com:bad/event/x", "https://user:pass@polymarket.com/event/x"):
            with self.subTest(value=value), self.assertRaises(PolymarketError):
                load_market_snapshot(value, 1_000, 0, 0, now=NOW, fetch=unexpected_fetch, **FEE)

        with self.assertRaises(PolymarketError):
            load_market_snapshot("12345", 1_000, 0, 0, snapshot_id="", now=NOW, fetch=fixture_fetch(), **FEE)

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
            (market(question=""), "question"),
            (market(description=None), "rules"),
            (market(endDate="2026-07-21T11:00:00Z"), "end time"),
            (market(eventSlug="bad/slug"), "event slug"),
        )
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(PolymarketError, message):
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=lambda *_: body, **FEE)

    def test_invalid_books_are_rejected_safely(self) -> None:
        cases = (
            (book(asks=[]), "empty"),
            (book(asset_id="other"), "token"),
            (book(timestamp="1784634800000"), "stale"),
            (book(asks=[{"price": "nan", "size": "1"}]), "level"),
            (book(asks=[{"price": "0.4", "size": "0"}]), "level"),
            (book(asks=[{"price": 0.4, "size": "1"}]), "level"),
            (book(bids=[{"price": "0.42", "size": "1"}]), "crossed"),
            (book(asks=[{"price": "0.4", "size": "1"}] * 51), "levels"),
        )
        for body, message in cases:
            def fetch(url: str, *_: object, body: bytes = body) -> bytes:
                return body if "clob.polymarket.com" in url else market()
            with self.subTest(message=message), self.assertRaisesRegex(PolymarketError, message):
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

        with self.assertRaisesRegex(PolymarketError, "too large"):
            def oversized(url: str, *_: object) -> bytes:
                return b"x" * 101 if "clob.polymarket.com" in url else market()
            load_market_snapshot("12345", 1_000, 0, 0, now=NOW, max_response_bytes=100, fetch=oversized, **FEE)

    def test_oversized_and_network_failures_are_safe(self) -> None:
        with self.assertRaisesRegex(PolymarketError, "too large"):
            load_market_snapshot("12345", 1_000, 0, 0, now=NOW, max_response_bytes=20, fetch=fixture_fetch(), **FEE)

        secret = "super-secret-response"
        for failure in (TimeoutError(secret), URLError(secret)):
            def fail(*_: object, failure: BaseException = failure) -> bytes:
                raise failure

            with self.subTest(failure=failure), self.assertRaises(PolymarketError) as raised:
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fail, **FEE)
            self.assertNotIn(secret, str(raised.exception))
            self.assertIsNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
