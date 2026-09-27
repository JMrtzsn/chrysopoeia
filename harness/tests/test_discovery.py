import json
import unittest
from datetime import datetime, timezone

from chrysopoeia.polymarket import (
    PolymarketError,
    _endpoint,
    discover_markets,
    load_market_snapshot,
)
from chrysopoeia.trading import validate_polymarket_event_url

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def record(identifier: int = 1, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": str(identifier),
        "active": True,
        "closed": False,
        "acceptingOrders": True,
        "outcomes": ["Yes", "No"],
        "clobTokenIds": [f"yes-{identifier}", f"no-{identifier}"],
        "question": f"Question {identifier}?",
        "endDate": "2026-09-14T12:00:00Z",
        "eventSlug": f"question-{identifier}",
    }
    value.update(changes)
    return value


class MarketDiscoveryTests(unittest.TestCase):
    def test_paginates_three_exact_gamma_endpoints_and_ranks_scanned_sample(
        self,
    ) -> None:
        calls: list[tuple[str, float, int]] = []
        pages = [
            [record(i, endDate="2026-09-16T00:00:00Z") for i in range(1, 26)],
            [record(i, endDate="2026-09-15T00:00:00Z") for i in range(26, 51)],
            [record(i, endDate="2026-09-14T00:00:00Z") for i in range(51, 76)],
        ]

        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            calls.append((url, timeout, max_bytes))
            return json.dumps(pages[len(calls) - 1]).encode()

        candidates = discover_markets(limit=2, now=NOW, fetch=fetch)

        self.assertEqual([item.market_id for item in candidates], ["51", "52"])
        self.assertEqual(
            calls,
            [
                (
                    "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=25&offset=0",
                    5.0,
                    256 * 1024,
                ),
                (
                    "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=25&offset=25",
                    5.0,
                    256 * 1024,
                ),
                (
                    "https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=25&offset=50",
                    5.0,
                    256 * 1024,
                ),
            ],
        )
        self.assertTrue(all("clob.polymarket.com" not in call[0] for call in calls))

    def test_processes_at_most_25_records_per_page(self) -> None:
        page = [record(i) for i in range(1, 26)] + [
            record(26, endDate="2026-09-14T00:00:00Z")
        ]
        pages = iter((page, []))

        candidates = discover_markets(
            limit=20, now=NOW, fetch=lambda *_: json.dumps(next(pages)).encode()
        )

        self.assertNotIn("26", [candidate.market_id for candidate in candidates])

    def test_short_page_stops_and_eligible_formats_are_normalized(self) -> None:
        calls: list[str] = []
        page = [
            record(
                20,
                outcomes='["Yes", "No"]',
                clobTokenIds='["yes", "no"]',
                endDate="2026-09-14T14:00:00+02:00",
                slug="fallback-slug",
            ),
            record(3, endDate="2026-09-14T12:00:00Z"),
        ]
        page[0].pop("eventSlug")

        def fetch(url: str, *_: object) -> bytes:
            calls.append(url)
            return json.dumps(page).encode()

        candidates = discover_markets(limit=20, now=NOW, fetch=fetch)

        self.assertEqual(len(calls), 1)
        self.assertEqual([item.market_id for item in candidates], ["3", "20"])
        self.assertEqual(candidates[1].end_time, "2026-09-14T12:00:00+00:00")
        self.assertEqual(
            candidates[1].source_url,
            "https://polymarket.com/event/fallback-slug",
        )

    def test_malformed_preferred_fields_fall_back_to_valid_alternates(self) -> None:
        value = record(
            20,
            endDate="2026-09-14",
            endDateIso="2026-09-15T12:00:00Z",
            eventSlug="private_slug",
            slug="fallback-slug",
        )

        candidates = discover_markets(
            now=NOW, fetch=lambda *_: json.dumps([value]).encode()
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].end_time, "2026-09-15T12:00:00+00:00")
        self.assertEqual(
            candidates[0].source_url,
            "https://polymarket.com/event/fallback-slug",
        )

    def test_malformed_or_ineligible_records_are_skipped_individually(self) -> None:
        invalid = [
            record(2, active=1),
            record(3, closed=0),
            record(4, acceptingOrders=1),
            record(5, outcomes=["No", "Yes"]),
            record(6, clobTokenIds=["same", "same"]),
            record(7, id="0"),
            record(8, id="01"),
            record(9, question="bad\nquestion"),
            record(10, question="x" * 501),
            record(11, endDate="2026-09-13T12:00:00Z"),
            record(12, endDate=None, endDateIso="2026-09-14"),
            record(13, eventSlug="../private"),
            record(14, eventSlug="private_slug"),
            record(15, eventSlug="privaté"),
            record(16, id="\u0661"),
            "not an object",
        ]
        body = json.dumps([record(1), *invalid]).encode()

        candidates = discover_markets(limit=20, now=NOW, fetch=lambda *_: body)

        self.assertEqual([item.market_id for item in candidates], ["1"])

    def test_duplicate_identity_is_deduplicated_but_conflict_fails(self) -> None:
        duplicate = record(1)
        exact = json.dumps([duplicate, duplicate]).encode()
        self.assertEqual(
            [
                item.market_id
                for item in discover_markets(now=NOW, fetch=lambda *_: exact)
            ],
            ["1"],
        )

        conflict = json.dumps([duplicate, record(1, question="Different?")]).encode()
        with self.assertRaisesRegex(PolymarketError, "conflicting duplicate"):
            discover_markets(now=NOW, fetch=lambda *_: conflict)

    def test_invalid_boundary_inputs_and_top_level_fail_safely(self) -> None:
        for limit in (True, 0, 21):
            with self.subTest(limit=limit), self.assertRaises(PolymarketError):
                discover_markets(limit=limit, fetch=lambda *_: self.fail("no fetch"))
        with self.assertRaises(PolymarketError):
            discover_markets(now=datetime(2026, 1, 1), fetch=lambda *_: b"[]")
        for body in (b"{}", b"not-json", b"x" * (256 * 1024 + 1)):
            with self.subTest(body=body[:10]), self.assertRaises(PolymarketError):
                discover_markets(now=NOW, fetch=lambda *_args, body=body: body)

    def test_oversized_25_record_page_fails(self) -> None:
        page = [record(i, padding="x" * 11_000) for i in range(1, 26)]

        with self.assertRaisesRegex(PolymarketError, "too large"):
            discover_markets(now=NOW, fetch=lambda *_: json.dumps(page).encode())

    def test_candidates_handoff_to_capture_contract(self) -> None:
        candidate = discover_markets(
            limit=1,
            now=NOW,
            fetch=lambda *_: json.dumps([record(12345)]).encode(),
        )[0]
        endpoint, expected, uses_slug = _endpoint(candidate.market_id)
        validate_polymarket_event_url(candidate.source_url)
        self.assertEqual(
            (endpoint, expected, uses_slug),
            ("https://gamma-api.polymarket.com/markets/12345", "12345", False),
        )

        metadata = record(12345, description="Resolves from the named source.")
        metadata["updatedAt"] = "2026-09-13T11:59:00Z"
        book = {
            "asset_id": "yes-12345",
            "timestamp": "1789300740000",
            "asks": [{"price": "0.40", "size": "10"}],
            "bids": [],
        }
        snapshot = load_market_snapshot(
            candidate.capture,
            1_000,
            0,
            0,
            now=NOW,
            fetch=lambda url, *_: json.dumps(
                book if "clob.polymarket.com" in url else metadata
            ).encode(),
            paper_fee_rate=0.02,
            paper_fee_source="paper-assumption:flat-2pct-v1",
        )
        self.assertEqual(snapshot.market_id, candidate.market_id)


if __name__ == "__main__":
    unittest.main()
