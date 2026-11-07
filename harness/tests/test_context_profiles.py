import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from chrysopoeia.context import ContextIdentity
from chrysopoeia.context_profiles import (
    ContextCatalog,
    ContextLearningSummary,
    ContextProfileDraft,
    ProfileError,
    build_context_profile,
    bundled_profiles,
    context_learning_summary_hash,
    profile_manifest_hash,
)


class ContextProfileTests(unittest.TestCase):
    def test_bundled_btc_profile_has_a_stable_manifest_hash(self) -> None:
        profile = bundled_profiles()[0]

        self.assertEqual(profile.identity.scope_key, "polymarket:series:btc-updown-5m")
        self.assertEqual(profile.identity.profile_version, 1)
        self.assertEqual(len(profile.manifest_hash), 64)
        self.assertEqual(
            profile.manifest_hash,
            profile_manifest_hash(
                profile.scope_key,
                profile.profile_id,
                profile.profile_version,
                profile.learning_summary,
                profile.instructions,
                profile.tool_ids,
                profile.evidence_sources,
            ),
        )

    def test_local_catalog_reloads_immutable_approved_profile_versions(self) -> None:
        base = bundled_profiles()[0]
        draft = ContextProfileDraft(
            learning_summary="Twenty completed trades provide directional but uncertain context.",
            instructions="Compare current BTC window evidence with its recent history.",
            tool_ids=["analyze_crypto_history"],
            evidence_sources=[
                "market_snapshot",
                "financial_analysis",
                "outcome_history",
            ],
            rationale="Recent completed trades suggest focusing on window movement.",
        )
        summary = ContextLearningSummary(
            scope_key=base.scope_key,
            profile_id=base.profile_id,
            profile_version=1,
            as_of="2026-10-22T00:00:00+00:00",
            lookback_days=90,
            profile_version_count=1,
            decision_count=22,
            plan_ready_count=20,
            abstained_count=2,
            rejected_count=0,
            consumer_rejected_count=0,
            filled_count=20,
            completed_trade_count=20,
            winning_trade_count=11,
            realized_pnl_usd=1.25,
            outcome_watermark="2026-10-21T23:00:00+00:00",
        )
        profile = build_context_profile(
            ContextIdentity(
                base.scope_key,
                base.profile_id,
                2,
            ),
            draft,
            created_at="2026-10-22T00:00:00+00:00",
            sample_count=20,
            source_watermark="2026-10-21T23:00:00+00:00",
            source_summary_hash=context_learning_summary_hash(summary),
            source_summary=summary,
            approved_by="context_profile_reviewer",
            approval_reason="The revision stays evidence-focused and within the tool allowlist.",
        )
        with tempfile.TemporaryDirectory() as directory:
            catalog = ContextCatalog(Path(directory) / "profiles.jsonl")
            catalog.record_profile(profile, previous_version=1)

            restored = catalog.latest(profile.scope_key, profile.profile_id)
            self.assertEqual(restored, profile)
            catalog.record_profile(profile, previous_version=1)
            self.assertEqual(len(catalog.profiles()), 1)

    def test_catalog_skips_a_previously_evaluated_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = ContextCatalog(Path(directory) / "profiles.jsonl")
            args = {
                "scope_key": "polymarket:series:btc-updown-5m",
                "profile_id": "crypto.btcusd.5m.updown",
                "profile_version": 1,
                "summary_hash": "b" * 64,
                "outcome_watermark": "2026-10-21T23:00:00+00:00",
                "decision": "rejected",
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }

            catalog.record_iteration(**args)
            catalog.record_iteration(**args)

            self.assertEqual(len(catalog.iterations()), 1)
            self.assertTrue(
                catalog.was_evaluated(
                    args["scope_key"], args["profile_id"], 1, args["summary_hash"]
                )
            )

    def test_profile_draft_cannot_add_tools(self) -> None:
        with self.assertRaises(ValidationError):
            ContextProfileDraft(
                learning_summary="A draft cannot grant execution authority.",
                instructions="Use the provided evidence.",
                tool_ids=["submit_order"],
                evidence_sources=["market_snapshot"],
                rationale="A proposed update.",
            )

    def test_corrupt_local_catalog_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.jsonl"
            path.write_text('{"record_type":"profile_approved"}\n')
            catalog = ContextCatalog(path)

            with self.assertRaises(ProfileError):
                catalog.latest(
                    "polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown"
                )
