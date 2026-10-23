import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from google.adk.sessions import InMemorySessionService

from chrysopoeia.configuration import (
    ContextLearningConfig,
    HistoryConfig,
    load_harness_config,
)
from chrysopoeia.context_learning import _profile_agent, resolve_context_profile
from chrysopoeia.context_profiles import (
    ContextCatalog,
    ContextProfileDraft,
    ContextProfileReview,
    local_catalog_path,
)
from chrysopoeia.trading import BookLevel, MarketSnapshot
from tests.test_cycle_runner import FakeLlm

ROOT = Path(__file__).parents[1]


def snapshot(source_url: str) -> MarketSnapshot:
    return MarketSnapshot(
        "snapshot-1", "market-1", 0.4, 1000, 0, 0,
        question="Will Arsenal beat Chelsea?",
        resolution_rules="The match winner resolves YES.",
        end_time="2027-01-01T00:00:00+00:00",
        captured_at="2026-10-22T00:00:00+00:00",
        source_url=source_url,
        yes_token_id="yes-token",
        asks=(BookLevel(0.4, 100),),
        fee_rate=0.02,
        fee_source="paper-assumption:flat-2pct-v1",
        book_captured_at="2026-10-22T00:00:00+00:00",
    )


def draft(
    instructions: str = "Use match form and verified team news as evidence.",
    learning_summary: str = "No finalized same-context outcomes yet; treat evidence as uncertain.",
) -> ContextProfileDraft:
    return ContextProfileDraft(
        learning_summary=learning_summary,
        instructions=instructions,
        tool_ids=["analyze_polymarket_history"],
        evidence_sources=["market_snapshot", "public_web", "series_history", "outcome_history"],
        rationale="Use same-context completed outcomes as descriptive evidence.",
    )


class ContextLearningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = load_harness_config(ROOT / "chrysopoeia.toml")
        self.sessions = SimpleNamespace()
        self.args = {
            "context_model": "context-model",
            "reviewer_model": "reviewer-model",
            "sessions": self.sessions,
            "app_name": "test",
            "user_id": "operator",
            "session_id": "cycle",
        }

    def test_profile_agents_disable_thinking_within_the_output_ceiling(self) -> None:
        for output_key, schema in (
            ("context_profile_draft", ContextProfileDraft),
            ("context_profile_review", ContextProfileReview),
        ):
            agent = _profile_agent(
                name=f"agent_{output_key}",
                model="model",
                instruction="instruction",
                output_schema=schema,
                output_key=output_key,
                cost_policy=self.config.cost_policy,
            )
            budget = agent.generate_content_config.thinking_config.thinking_budget
            self.assertEqual(budget, 0)

    async def test_unknown_market_gets_local_profile_only_after_agent_approval(self) -> None:
        config = replace(
            self.config,
            context_learning=ContextLearningConfig(enabled=True),
        )
        approved = ContextProfileReview(approved=True, reason="The tools and guidance are bounded.")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"CHRYSOPOEIA_CONTEXT_CATALOG": str(Path(directory) / "profiles.jsonl")}
        ), patch(
            "chrysopoeia.context_learning._draft_and_review",
            new=AsyncMock(return_value=(draft(), approved)),
        ) as agents:
            result = await resolve_context_profile(
                config, snapshot("https://polymarket.com/event/arsenal-vs-chelsea"), **self.args
            )
            saved = ContextCatalog(local_catalog_path()).latest(
                "polymarket:event:arsenal-vs-chelsea", "polymarket.event"
            )

        self.assertIsNotNone(result.profile)
        self.assertIsNotNone(saved)
        assert result.profile is not None and saved is not None
        self.assertEqual(result.profile, saved)
        self.assertEqual(saved.profile_version, 2)
        agents.assert_awaited_once()

    async def test_real_curator_and_reviewer_agents_write_profile_with_cost_records(self) -> None:
        config = replace(
            self.config,
            context_learning=ContextLearningConfig(enabled=True),
        )
        calls: list[str] = []
        curator = FakeLlm(
            model=config.models.context,
            calls=calls,
            response={
                "learning_summary": "No finalized outcomes for this event; uncertainty is high.",
                "instructions": "Use match-specific public evidence and market rules.",
                "tool_ids": [],
                "evidence_sources": ["market_snapshot", "public_web"],
                "rationale": "Start with the event's canonical rules and public evidence.",
            },
        )
        reviewer = FakeLlm(
            model=config.models.reviewer,
            calls=calls,
            response={"approved": True, "reason": "The profile is bounded and evidence-focused."},
        )
        sessions = InMemorySessionService()
        await sessions.create_session(
            app_name="test",
            user_id="operator",
            session_id="cycle",
            state={
                "cycle_id": "test-cycle",
                "operating_config": asdict(config.operating),
                "model_cost_policy": config.cost_policy,
            },
        )
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"CHRYSOPOEIA_CONTEXT_CATALOG": str(Path(directory) / "profiles.jsonl")}
        ):
            result = await resolve_context_profile(
                config,
                snapshot("https://polymarket.com/event/arsenal-vs-chelsea"),
                context_model=curator,
                reviewer_model=reviewer,
                sessions=sessions,
                app_name="test",
                user_id="operator",
                session_id="cycle",
            )
            session = await sessions.get_session(
                app_name="test", user_id="operator", session_id="cycle"
            )

        self.assertIsNotNone(result.profile)
        self.assertEqual(calls, [config.models.context, config.models.reviewer])
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(len(session.state["model_cost_ledger"]), 2)

    async def test_profile_revision_waits_for_twenty_finalized_trades(self) -> None:
        config = replace(
            self.config,
            context_learning=ContextLearningConfig(enabled=True),
            history=HistoryConfig(enabled=True),
        )
        history = {
            "scope_key": "polymarket:series:btc-updown-5m",
            "profile_id": "crypto.btcusd.5m.updown",
            "profile_version": 1,
            "as_of": "2026-10-22T00:00:00+00:00",
            "lookback_days": 90,
            "profile_version_count": 1,
            "decision_count": 25,
            "plan_ready_count": 25,
            "abstained_count": 0,
            "rejected_count": 0,
            "consumer_rejected_count": 0,
            "filled_count": 22,
            "completed_trade_count": 19,
            "winning_trade_count": 11,
            "realized_pnl_usd": 2.5,
            "outcome_watermark": "2026-10-21T23:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "CHRYSOPOEIA_CONTEXT_CATALOG": str(Path(directory) / "profiles.jsonl"),
                "CHRYSOPOEIA_HISTORY_TABLE": "project.dataset.raw_events",
            },
        ), patch(
            "chrysopoeia.context_learning.query_context_history", return_value=history
        ), patch("chrysopoeia.context_learning._draft_and_review", new=AsyncMock()) as agents:
            result = await resolve_context_profile(
                config,
                snapshot("https://polymarket.com/event/btc-updown-5m-1792600000"),
                **self.args,
            )

        self.assertEqual(result.profile.profile_version, 1)
        agents.assert_not_awaited()

    async def test_approved_revision_activates_only_the_next_profile_version(self) -> None:
        config = replace(
            self.config,
            context_learning=ContextLearningConfig(enabled=True),
            history=HistoryConfig(enabled=True),
        )
        history = {
            "scope_key": "polymarket:series:btc-updown-5m",
            "profile_id": "crypto.btcusd.5m.updown",
            "profile_version": 1,
            "as_of": "2026-10-22T00:00:00+00:00",
            "lookback_days": 90,
            "profile_version_count": 1,
            "decision_count": 25,
            "plan_ready_count": 25,
            "abstained_count": 0,
            "rejected_count": 0,
            "consumer_rejected_count": 0,
            "filled_count": 22,
            "completed_trade_count": 20,
            "winning_trade_count": 11,
            "realized_pnl_usd": 2.5,
            "outcome_watermark": "2026-10-21T23:00:00+00:00",
        }
        approved = ContextProfileReview(approved=True, reason="The revision is evidence-bounded.")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "CHRYSOPOEIA_CONTEXT_CATALOG": str(Path(directory) / "profiles.jsonl"),
                "CHRYSOPOEIA_HISTORY_TABLE": "project.dataset.raw_events",
            },
        ), patch(
            "chrysopoeia.context_learning.query_context_history", return_value=history
        ), patch(
            "chrysopoeia.context_learning._draft_and_review",
            new=AsyncMock(return_value=(draft("Emphasize window-specific momentum and cite its history."), approved)),
        ) as agents:
            result = await resolve_context_profile(
                config,
                snapshot("https://polymarket.com/event/btc-updown-5m-1792600000"),
                **self.args,
            )
            saved = ContextCatalog(local_catalog_path()).latest(
                "polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown"
            )

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(result.profile, saved)
        self.assertEqual(saved.profile_version, 2)
        self.assertEqual(saved.sample_count, 20)
        self.assertIsNotNone(result.history_evidence)
        agents.assert_awaited_once()

    async def test_rejected_revision_is_not_retried_for_the_same_outcome_watermark(self) -> None:
        config = replace(
            self.config,
            context_learning=ContextLearningConfig(enabled=True),
            history=HistoryConfig(enabled=True),
        )
        history = {
            "scope_key": "polymarket:series:btc-updown-5m",
            "profile_id": "crypto.btcusd.5m.updown",
            "profile_version": 1,
            "as_of": "2026-10-22T00:00:00+00:00",
            "lookback_days": 90,
            "profile_version_count": 1,
            "decision_count": 25,
            "plan_ready_count": 25,
            "abstained_count": 0,
            "rejected_count": 0,
            "consumer_rejected_count": 0,
            "filled_count": 22,
            "completed_trade_count": 20,
            "winning_trade_count": 11,
            "realized_pnl_usd": 2.5,
            "outcome_watermark": "2026-10-21T23:00:00+00:00",
        }
        rejected = ContextProfileReview(approved=False, reason="The evidence is not strong enough.")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "CHRYSOPOEIA_CONTEXT_CATALOG": str(Path(directory) / "profiles.jsonl"),
                "CHRYSOPOEIA_HISTORY_TABLE": "project.dataset.raw_events",
            },
        ), patch(
            "chrysopoeia.context_learning.query_context_history", return_value=history
        ), patch(
            "chrysopoeia.context_learning._draft_and_review",
            new=AsyncMock(return_value=(draft(), rejected)),
        ) as agents:
            first = await resolve_context_profile(
                config,
                snapshot("https://polymarket.com/event/btc-updown-5m-1792600000"),
                **self.args,
            )
            second = await resolve_context_profile(
                config,
                snapshot("https://polymarket.com/event/btc-updown-5m-1792600000"),
                **self.args,
            )

        self.assertEqual(first.profile.profile_version, 1)
        self.assertEqual(second.profile.profile_version, 1)
        agents.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
