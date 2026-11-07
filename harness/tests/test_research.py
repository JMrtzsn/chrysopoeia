import unittest
from datetime import datetime, timezone

from chrysopoeia.research import MAX_RESEARCH_RECORDS, openrouter_web_research
from chrysopoeia.trading import BookLevel, MarketSnapshot


def snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        "polymarket-abc",
        "12345",
        0.4,
        1_000,
        0,
        0,
        question="Will it rain?",
        resolution_rules="Resolves Yes if rain is measured.",
        end_time="2027-01-01T00:00:00+00:00",
        captured_at="2026-10-15T00:00:00+00:00",
        source_url="https://polymarket.com/event/will-it-rain",
        yes_token_id="yes-token",
        asks=(BookLevel(0.4, 20),),
        fee_rate=0.02,
        fee_source="paper-assumption:flat-2pct-v1",
        book_captured_at="2026-10-15T00:00:00+00:00",
    )


def response(
    annotations: list[object], *, prompt_tokens: int = 100, completion_tokens: int = 20
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "answer",
                    "annotations": annotations,
                }
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


class OpenRouterResearchTests(unittest.TestCase):
    def run_research(self, payload: object) -> tuple[list[object], int, int, int]:
        captured: dict[str, object] = {}

        def post(url, body, headers, timeout, max_bytes):
            captured.update({"url": url, "body": body, "headers": headers})
            return payload

        records, count, in_tokens, out_tokens = openrouter_web_research(
            snapshot(),
            model="openrouter/openai/gpt-4.1-mini",
            api_key="secret-key",
            post=post,
            now=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            captured["url"], "https://openrouter.ai/api/v1/chat/completions"
        )
        body = captured["body"]
        assert isinstance(body, dict)
        self.assertEqual(body["model"], "openai/gpt-4.1-mini")
        self.assertEqual(body["plugins"], [{"id": "web", "max_results": 5}])
        headers = captured["headers"]
        assert isinstance(headers, dict)
        self.assertEqual(headers["Authorization"], "Bearer secret-key")
        return records, count, in_tokens, out_tokens

    def test_extracts_citations_usage_and_strips_provider_prefix(self) -> None:
        payload = response(
            [
                {
                    "type": "url_citation",
                    "url_citation": {
                        "url": "https://example.com/report",
                        "title": "Report",
                        "content": "Relevant excerpt.",
                    },
                }
            ]
        )
        records, count, in_tokens, out_tokens = self.run_research(payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, "https://example.com/report")
        self.assertEqual(records[0].excerpt, "Relevant excerpt.")
        self.assertEqual((count, in_tokens, out_tokens), (1, 100, 20))

    def test_skips_non_https_duplicates_and_non_citations(self) -> None:
        payload = response(
            [
                {"type": "file_citation", "url_citation": {"url": "https://x.test/a"}},
                {
                    "type": "url_citation",
                    "url_citation": {"url": "http://insecure.test", "title": "bad"},
                },
                {"type": "url_citation", "url_citation": {"url": "https://ok.test/a"}},
                {"type": "url_citation", "url_citation": {"url": "https://ok.test/a"}},
            ]
        )
        records, count, _, _ = self.run_research(payload)
        self.assertEqual([record.url for record in records], ["https://ok.test/a"])
        self.assertEqual(count, 3)

    def test_caps_records_and_defaults_missing_title(self) -> None:
        payload = response(
            [
                {
                    "type": "url_citation",
                    "url_citation": {"url": f"https://example.com/{index}"},
                }
                for index in range(MAX_RESEARCH_RECORDS + 4)
            ]
        )
        records, count, _, _ = self.run_research(payload)
        self.assertEqual(len(records), MAX_RESEARCH_RECORDS)
        self.assertEqual(records[0].title, "Web source")
        self.assertEqual(count, 5)

    def test_rejects_missing_credential(self) -> None:
        with self.assertRaises(ValueError):
            openrouter_web_research(snapshot(), model="openrouter/m", api_key="  ")

    def test_rejects_malformed_envelope(self) -> None:
        for payload in (None, {}, {"choices": []}, {"choices": [{"message": []}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                openrouter_web_research(
                    snapshot(),
                    model="openrouter/m",
                    api_key="k",
                    post=lambda *args, response=payload: response,
                )

    def test_missing_annotations_yields_no_evidence(self) -> None:
        for payload in (
            {"choices": [{"message": {}}]},
            {"choices": [{"message": {"annotations": "x"}}]},
        ):
            with self.subTest(payload=payload):
                records, count, in_tokens, out_tokens = self.run_research(payload)
                self.assertEqual((records, count, in_tokens, out_tokens), ([], 0, 0, 0))

    def test_rejects_oversized_response(self) -> None:
        def post(url, body, headers, timeout, max_bytes):
            del url, body, headers, timeout, max_bytes
            raise ValueError("research response is too large")

        with self.assertRaises(ValueError):
            openrouter_web_research(
                snapshot(), model="openrouter/m", api_key="k", post=post
            )


if __name__ == "__main__":
    unittest.main()
