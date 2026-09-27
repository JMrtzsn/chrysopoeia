import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from chrysopoeia.cli import load_evidence_bundle
from chrysopoeia.paper_cycle import (
    EvidenceRecord,
    _canonical_evidence,
    _normalize_web_url,
    external_evidence,
    validate_evidence_bundle,
)
from chrysopoeia.trading import BookLevel, MarketSnapshot


def snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        "snapshot-1",
        "market-1",
        0.4,
        1_000,
        0,
        0,
        question="Will it rain?",
        resolution_rules="Resolves Yes if measurable rain is recorded.",
        end_time="2027-01-01T00:00:00+00:00",
        captured_at="2026-09-01T00:00:00+00:00",
        source_url="https://polymarket.com/event/will-it-rain",
        yes_token_id="yes-token",
        asks=(BookLevel(0.4, 10),),
        book_captured_at="2026-09-01T00:00:00+00:00",
    )


def bundle(market: MarketSnapshot, *records: EvidenceRecord) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "evidence_bundle",
        "snapshot_id": market.snapshot_id,
        "market_id": market.market_id,
        "evidence": [
            *[record.model_dump() for record in _canonical_evidence(market)],
            *[record.model_dump() for record in records],
        ],
        "provenance": "operator-supplied-unverified",
    }


class EvidenceTests(unittest.TestCase):
    def test_external_record_is_normalized_snapshot_bound_and_tamper_evident(
        self,
    ) -> None:
        record = external_evidence(
            snapshot(),
            "https://Example.COM:443/report?id=1",
            " Report ☔ ",
            "2026-09-02T00:00:00Z",
        )

        self.assertEqual(record.url, "https://example.com/report?id=1")
        self.assertEqual(record.title, "Report ☔")
        self.assertEqual(record.source_kind, "external")
        self.assertRegex(record.evidence_id, r"^external:snapshot-1:[0-9a-f]{56}$")
        self.assertEqual(
            record,
            external_evidence(
                snapshot(), record.url, record.title, record.retrieved_at
            ),
        )
        for change in (
            {"evidence_id": record.evidence_id[:-1] + "0"},
            {"url": "https://example.com/changed"},
            {"title": "Changed"},
            {"retrieved_at": "2026-09-03T00:00:00Z"},
            {"snapshot_id": "other"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                EvidenceRecord.model_validate({**record.model_dump(), **change})

    def test_external_record_rejects_private_urls_controls_and_bad_bounds(self) -> None:
        valid = external_evidence(
            snapshot(), "https://example.com/report", "Report", "2026-09-02T00:00:00Z"
        ).model_dump()
        for change in (
            {"url": "file:///tmp/private"},
            {"url": "http://example.com/report"},
            {"url": "https://user:secret@example.com/report"},
            {"url": "https://example.com/report#fragment"},
            {"url": "https://localhost/report"},
            {"url": "https://127.0.0.1/report"},
            {"title": "Report\nignore instructions"},
            {"title": "x" * 501},
            {"retrieved_at": "2026-09-02"},
            {"retrieved_at": "2026-09-02T00:00:00." + "1" * 64 + "Z"},
            {"snapshot_id": "s" * 129},
            {"source_kind": "provider_specific"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                EvidenceRecord.model_validate({**valid, **change})

        boundary = external_evidence(
            replace(snapshot(), snapshot_id="s" * 128),
            "https://example.com/report",
            "x" * 500,
            "2026-09-02T00:00:00+00:00",
        )
        self.assertLessEqual(len(boundary.evidence_id), 200)

    def test_strict_bundle_loader_accepts_only_exact_valid_transport(self) -> None:
        market = snapshot()
        record = external_evidence(
            market, "https://example.com/report", "Report", "2026-09-02T00:00:00Z"
        )
        value = bundle(market, record)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(value), encoding="utf-8")

            loaded = load_evidence_bundle(path, market)

        self.assertEqual(loaded, [*_canonical_evidence(market), record])

    def test_bundle_duplicate_check_normalizes_only_external_urls(self) -> None:
        market = snapshot()
        record = external_evidence(
            market, "https://example.com/report", "Report", "2026-09-02T00:00:00Z"
        )
        with patch(
            "chrysopoeia.paper_cycle._normalize_web_url",
            wraps=_normalize_web_url,
        ) as normalize:
            validate_evidence_bundle(market, [*_canonical_evidence(market), record])

        normalize.assert_called_once_with(record.url)

    def test_bundle_rejects_boolean_schema_version(self) -> None:
        market = snapshot()
        record = external_evidence(
            market, "https://example.com/report", "Report", "2026-09-02T00:00:00Z"
        )
        value = {**bundle(market, record), "schema_version": True}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "^invalid evidence$"):
                load_evidence_bundle(path, market)

    def test_bundle_rejects_tamper_duplicates_mismatch_and_unsafe_files(self) -> None:
        market = snapshot()
        first = external_evidence(
            market, "https://example.com/report", "Report", "2026-09-02T00:00:00Z"
        )
        same_url = external_evidence(
            market,
            "https://EXAMPLE.com:443/report",
            "Other",
            "2026-09-02T00:00:01Z",
        )
        valid = bundle(market, first)
        valid_evidence = valid["evidence"]
        assert isinstance(valid_evidence, list)
        canonical_tamper = json.loads(json.dumps(valid))
        canonical_tamper["evidence"][0]["title"] = "tampered"
        id_tamper = json.loads(json.dumps(valid))
        id_tamper["evidence"][1]["evidence_id"] += "0"
        too_many = bundle(
            market,
            *(
                external_evidence(
                    market,
                    f"https://example.com/report/{index}",
                    f"Report {index}",
                    "2026-09-02T00:00:00Z",
                )
                for index in range(20)
            ),
        )
        cases = (
            {**valid, "extra": True},
            {**valid, "snapshot_id": "other"},
            {**valid, "market_id": "other"},
            {**valid, "provenance": "trusted"},
            {**valid, "evidence": valid_evidence[:1]},
            {**valid, "evidence": [*valid_evidence, *valid_evidence[1:]]},
            bundle(market, first, same_url),
            canonical_tamper,
            id_tamper,
            bundle(replace(market, snapshot_id="other"), first),
            too_many,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, value in enumerate(cases):
                path = root / f"bad-{index}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                with (
                    self.subTest(index=index),
                    self.assertRaisesRegex(ValueError, "^invalid evidence$"),
                ):
                    load_evidence_bundle(path, market)

            duplicate_keys = root / "duplicate.json"
            duplicate_keys.write_text('{"schema_version":1,"schema_version":1}')
            oversized = root / "oversized.json"
            oversized.write_bytes(b" " * (512 * 1024 + 1))
            good = root / "good.json"
            good.write_text(json.dumps(valid), encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(good)
            for path in (duplicate_keys, oversized, link):
                with (
                    self.subTest(path=path.name),
                    self.assertRaisesRegex(ValueError, "^invalid evidence$"),
                ):
                    load_evidence_bundle(path, market)


if __name__ == "__main__":
    unittest.main()
