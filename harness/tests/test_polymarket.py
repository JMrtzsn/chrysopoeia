import json
import unittest
from datetime import datetime, timezone
from urllib.error import URLError

from chrysopoeia.paper_cycle import _canonical_evidence
from chrysopoeia.polymarket import (
    PolymarketError,
    load_market_snapshot,
    load_price_history,
    load_resolved_market,
    load_series_history,
)


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
    def test_up_down_market_snapshot_buys_the_up_side(self) -> None:
        snapshot = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW,
            fetch=lambda url, *_: book() if "clob" in url else market(outcomes='["Up", "Down"]'),
            **FEE,
        )
        self.assertEqual(snapshot.yes_token_id, "yes-token")

    def test_book_stamped_just_after_capture_start_is_accepted(self) -> None:
        later = str(int(NOW.timestamp() * 1000) + 1_000)
        snapshot = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW,
            fetch=lambda url, *_: book(timestamp=later) if "clob" in url else market(),
            **FEE,
        )
        self.assertEqual(snapshot.captured_at, snapshot.book_captured_at)

    def test_resolved_market_reports_first_outcome_result(self) -> None:
        def fetch(closed: bool, prices: str):
            body = market(
                id="12345", closed=closed, outcomes='["Up", "Down"]',
                outcomePrices=prices, clobTokenIds='["111", "222"]',
            )
            return lambda *_: body

        resolved = load_resolved_market("12345", fetch=fetch(True, '["0", "1"]'))
        self.assertEqual((resolved.yes_won, resolved.yes_token_id), (False, "111"))
        self.assertIsNone(load_resolved_market("12345", fetch=fetch(False, '["0.5", "0.5"]')).yes_won)
        with self.assertRaises(PolymarketError):
            load_resolved_market("1x")
    def test_series_history_returns_only_past_resolved_up_down_siblings(self) -> None:
        calls: list[str] = []
        start = datetime(2026, 7, 21, 11, 45, tzinfo=timezone.utc)
        sibling_slug = f"btc-updown-5m-{int(start.timestamp())}"
        event = {
            "slug": "btc-updown-5m-1000",
            "series": [{"id": "10684", "slug": "btc-up-or-down-5m"}],
        }
        sibling = {
            "closed": True,
            "seriesSlug": "btc-up-or-down-5m",
            "endDate": "2026-07-21T11:50:00Z",
            "markets": [
                {
                    "id": "12345",
                    "slug": sibling_slug,
                    "question": "BTC Up or Down 5m",
                    "closed": True,
                    "closedTime": "2026-07-21T11:50:01Z",
                    "outcomes": '["Up", "Down"]',
                    "outcomePrices": '["1", "0"]',
                    "clobTokenIds": '["111", "222"]',
                    "resolutionSource": "https://data.chain.link/btc-usd",
                }
            ],
        }

        def fetch(url: str, _timeout: float, _max_bytes: int) -> bytes:
            calls.append(url)
            return json.dumps([event] if "events?slug=" in url else [sibling]).encode()

        history = load_series_history(
            "https://polymarket.com/event/btc-updown-5m-1000",
            limit=5,
            now=NOW,
            fetch=fetch,
        )

        self.assertEqual((history.series_id, history.series_slug), ("10684", "btc-up-or-down-5m"))
        self.assertEqual(len(history.outcomes), 1)
        self.assertEqual(history.outcomes[0].start_time, start)
        self.assertTrue(history.outcomes[0].up_won)
        self.assertEqual(history.outcomes[0].up_token_id, "111")
        self.assertEqual(len(calls), 2)

    def test_clob_history_parses_sparse_points_in_time_order(self) -> None:
        calls: list[str] = []

        def fetch(url: str, _timeout: float, _max_bytes: int) -> bytes:
            calls.append(url)
            return json.dumps(
                {
                    "history": [
                        {"t": 140, "p": 0.9},
                        {"t": 120, "p": 0.6},
                        {"t": 90, "p": 0.1},
                        {"t": 110, "p": 0.4},
                    ]
                }
            ).encode()

        points = load_price_history(
            "123456",
            datetime.fromtimestamp(100, timezone.utc),
            datetime.fromtimestamp(130, timezone.utc),
            fetch=fetch,
        )
        self.assertEqual([(point.timestamp, point.price) for point in points], [(110, 0.4), (120, 0.6)])
        self.assertIn("startTs=100", calls[0])
        self.assertIn("fidelity=1", calls[0])

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
        self.assertEqual([(level.price, level.size) for level in snapshot.bids], [(0.4, 5)])
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

    def test_snapshot_identity_excludes_account_state_but_includes_market_data(self) -> None:
        baseline = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fixture_fetch(), **FEE)
        exposed = load_market_snapshot("12345", 9_000, 10, 20, now=NOW, fetch=fixture_fetch(), **FEE)
        changed_fee = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW, fetch=fixture_fetch(),
            paper_fee_rate=0.03, paper_fee_source="paper-assumption:test-v1",
        )

        self.assertEqual(baseline.snapshot_id, exposed.snapshot_id)
        self.assertNotEqual(baseline.snapshot_id, changed_fee.snapshot_id)

        changed_book = json.loads(book())
        changed_book["asks"][0]["size"] = "21"

        def changed_book_fetch(url: str, *_: object) -> bytes:
            return json.dumps(changed_book).encode() if "clob" in url else market()

        changed_depth = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW, fetch=changed_book_fetch, **FEE
        )
        def changed_metadata_fetch(url: str, *_: object) -> bytes:
            return book() if "clob" in url else market(question="Will it drizzle?")

        changed_metadata = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW, fetch=changed_metadata_fetch, **FEE
        )
        self.assertNotEqual(baseline.snapshot_id, changed_depth.snapshot_id)
        changed_book["asks"][0]["size"] = "20"
        changed_book["bids"][0]["size"] = "6"
        changed_bid_fetch = lambda url, *_: json.dumps(changed_book).encode() if "clob" in url else market()
        changed_bid = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW, fetch=changed_bid_fetch, **FEE
        )
        self.assertNotEqual(baseline.snapshot_id, changed_bid.snapshot_id)
        self.assertNotEqual(baseline.snapshot_id, changed_metadata.snapshot_id)

    def test_identifier_uses_market_slug_when_event_slug_is_absent(self) -> None:
        live_schema = json.loads(market(id="559651", slug="xi-jinping-out-before-2027"))
        live_schema.pop("eventSlug")

        def fetch(url: str, *_: object) -> bytes:
            return book() if "clob.polymarket.com" in url else json.dumps(live_schema).encode()

        snapshot = load_market_snapshot("559651", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)
        url_snapshot = load_market_snapshot(
            "https://polymarket.com/event/xi-jinping-out-before-2027",
            1_000, 0, 0, now=NOW, fetch=fetch, **FEE,
        )

        source_url = "https://polymarket.com/event/xi-jinping-out-before-2027"
        self.assertEqual(snapshot.source_url, source_url)
        self.assertEqual(url_snapshot.source_url, source_url)
        self.assertEqual(_canonical_evidence(snapshot)[0].url, source_url)

    def test_event_slug_takes_precedence_over_market_slug(self) -> None:
        def fetch(url: str, *_: object) -> bytes:
            return book() if "clob.polymarket.com" in url else market(
                eventSlug="event-slug", slug="market-slug"
            )

        snapshot = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

        self.assertEqual(snapshot.source_url, "https://polymarket.com/event/event-slug")

    def test_old_market_metadata_with_fresh_book_becomes_snapshot(self) -> None:
        def fetch(url: str, *_: object) -> bytes:
            return book() if "clob.polymarket.com" in url else market(updatedAt="2026-07-20T12:00:00Z")

        snapshot = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

        self.assertEqual(snapshot.captured_at, "2026-07-21T12:00:00+00:00")

    def test_future_market_metadata_is_rejected(self) -> None:
        snapshot = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW,
            fetch=lambda url, *_: book() if "clob.polymarket.com" in url else market(updatedAt="2026-07-21T12:00:05Z"),
            **FEE,
        )
        self.assertEqual(snapshot.captured_at, "2026-07-21T12:00:00+00:00")

        with self.assertRaisesRegex(PolymarketError, "future"):
            load_market_snapshot(
                "12345", 1_000, 0, 0, now=NOW,
                fetch=lambda *_: market(updatedAt="2026-07-21T12:01:00Z"), **FEE,
            )

    def test_stale_clob_book_is_rejected(self) -> None:
        def fetch(url: str, *_: object) -> bytes:
            return book(timestamp="1784634800000") if "clob.polymarket.com" in url else market()

        with self.assertRaisesRegex(PolymarketError, "book is stale"):
            load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

    def test_end_date_is_preferred_over_date_only_end_date_iso(self) -> None:
        def fetch(url: str, *_: object) -> bytes:
            return book() if "clob.polymarket.com" in url else market(
                endDateIso="2027-01-01", endDate="2027-01-01T04:59:00Z"
            )

        snapshot = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

        self.assertEqual(snapshot.end_time, "2027-01-01T04:59:00+00:00")

    def test_aware_end_date_iso_is_used_only_when_end_date_is_absent(self) -> None:
        aware = json.loads(market(endDateIso="2027-01-01T04:59:00-05:00"))
        aware.pop("endDate")
        date_only = json.loads(market(endDateIso="2027-01-01"))
        date_only.pop("endDate")

        def fetch(url: str, *_: object) -> bytes:
            return book() if "clob.polymarket.com" in url else json.dumps(aware).encode()

        snapshot = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)
        self.assertEqual(snapshot.end_time, "2027-01-01T09:59:00+00:00")

        with self.assertRaisesRegex(PolymarketError, "UTC offset"):
            load_market_snapshot(
                "12345", 1_000, 0, 0, now=NOW,
                fetch=lambda *_: json.dumps(date_only).encode(), **FEE,
            )

        with self.assertRaisesRegex(PolymarketError, "missing or invalid"):
            load_market_snapshot(
                "12345", 1_000, 0, 0, now=NOW,
                fetch=lambda *_: market(
                    endDate=None, endDateIso="2027-01-01T04:59:00Z"
                ), **FEE,
            )

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
            (b"not json", "JSON"),
            (json.dumps([]).encode(), "schema"),
            (market(outcomes='["A", "B", "C"]', clobTokenIds='["a", "b", "c"]'), "binary"),
            (market(outcomes='["No", "Yes"]'), "YES"),
            (market(clobTokenIds='["yes-token"]'), "token"),
            (market(question=""), "question"),
            (market(description=None), "rules"),
            (market(endDate="2026-07-21T11:00:00Z"), "end time"),
            (market(eventSlug="bad/slug"), "event slug"),
            (market(eventSlug=None, slug="bad/slug"), "event slug"),
            (market(eventSlug=None, slug=None), "event slug"),
        )
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(PolymarketError, message):
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=lambda *_: body, **FEE)

    def test_invalid_books_are_rejected_safely(self) -> None:
        cases = (
            (book(asks=[]), "empty"),
            (book(asset_id="other"), "token"),
            (book(asks=[{"price": "nan", "size": "1"}]), "level"),
            (book(asks=[{"price": "0.4", "size": "0"}]), "level"),
            (book(asks=[{"price": 0.4, "size": "1"}]), "level"),
            (book(bids=[{"price": "0.42", "size": "1"}]), "crossed"),
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

    def test_deep_book_retains_cheapest_fifty_valid_asks(self) -> None:
        asks = [
            {"price": f"{price / 100:.2f}", "size": "1"}
            for price in range(70, 9, -1)
        ]

        def fetch(url: str, *_: object) -> bytes:
            return book(asks=asks, bids=[{"price": "0.05", "size": "1"}]) if "clob.polymarket.com" in url else market()

        snapshot = load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)
        asks[0]["size"] = "999"
        same_retained_depth = load_market_snapshot(
            "12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE
        )

        self.assertEqual(len(snapshot.asks), 50)
        self.assertEqual([level.price for level in snapshot.asks], [price / 100 for price in range(10, 60)])
        self.assertEqual(snapshot.price, 0.10)
        self.assertEqual(snapshot.snapshot_id, same_retained_depth.snapshot_id)

    def test_deep_book_rejects_crossed_bid_and_malformed_level(self) -> None:
        asks = [{"price": "0.50", "size": "1"}] * 60
        cases = (
            book(asks=asks, bids=[{"price": "0.10", "size": "1"}] * 50 + [{"price": "0.50", "size": "1"}]),
            book(asks=asks[:50] + [{"price": 0.60, "size": "1"}] + asks[51:]),
        )
        for body, message in zip(cases, ("crossed", "level")):
            def fetch(url: str, *_: object, body: bytes = body) -> bytes:
                return body if "clob.polymarket.com" in url else market()

            with self.subTest(message=message), self.assertRaisesRegex(PolymarketError, message):
                load_market_snapshot("12345", 1_000, 0, 0, now=NOW, fetch=fetch, **FEE)

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
