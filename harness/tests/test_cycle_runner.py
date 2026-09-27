import asyncio
import json
import unittest
from collections.abc import AsyncGenerator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import Field, SkipValidation

from chrysopoeia.configuration import load_harness_config
from chrysopoeia.cost import LEDGER_KEY, settle_model_call
from chrysopoeia.cycle_runner import run_paper_cycle, run_paper_cycle_state
from chrysopoeia.paper_cycle import (
    PAPER_CYCLE_FILL_KEY,
    ProposalOutput,
    ReviewOutput,
    _canonical_evidence,
    external_evidence,
)
from chrysopoeia.trading import BookLevel, MarketSnapshot, OperatingConfig

ROOT = Path(__file__).parents[1]


class FakeLlm(BaseLlm):
    response: dict[str, object]
    calls: SkipValidation[list[str]]
    requests: SkipValidation[list[LlmRequest]] = Field(default_factory=list)
    raw_response: str | None = None

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.calls.append(self.model)
        self.requests.append(llm_request)
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=self.raw_response
                        if self.raw_response is not None
                        else json.dumps(self.response)
                    )
                ],
            ),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=11, candidates_token_count=7
            ),
        )


class CycleRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_harness_config(ROOT / "chrysopoeia.toml")
        self.snapshot = MarketSnapshot(
            "snapshot",
            "market",
            0.4,
            1_000,
            0,
            0,
            question="Will it rain?",
            resolution_rules="Resolves Yes if rain is measured.",
            end_time="2027-01-01T00:00:00+00:00",
            captured_at="2026-09-01T00:00:00+00:00",
            source_url="https://polymarket.com/event/will-it-rain",
            yes_token_id="yes-token",
            asks=(BookLevel(0.4, 100),),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )

    def models(self, action: str = "trade", approved: bool = True):
        calls: list[str] = []
        requests: list[LlmRequest] = []
        trader = FakeLlm(
            model=self.config.models.trader,
            calls=calls,
            requests=requests,
            response={
                "snapshot_id": "snapshot",
                "market_id": "market",
                "action": action,
                "probability": 0.46 if action == "trade" else 0.4,
                "amount": 9 if action == "trade" else 0,
                "citations": ["market_snapshot:snapshot"] if action == "trade" else [],
            },
        )
        reviewer = FakeLlm(
            model=self.config.models.reviewer,
            calls=calls,
            requests=requests,
            response={
                "snapshot_id": "snapshot",
                "market_id": "market",
                "approved": approved,
                "reason": "supported",
                "citations": ["market_snapshot:snapshot"] if approved else [],
            },
        )
        return trader, reviewer, calls

    def test_cycle_requests_disable_thinking_and_keep_cost_output_ceiling(self) -> None:
        trader, reviewer, _ = self.models()

        asyncio.run(
            run_paper_cycle(
                self.config, self.snapshot, OperatingConfig(), trader, reviewer
            )
        )

        self.assertEqual(len(trader.requests), 2)
        for request, schema in zip(
            trader.requests, (ProposalOutput, ReviewOutput), strict=True
        ):
            self.assertEqual(request.config.thinking_config.thinking_budget, 0)
            self.assertEqual(request.config.max_output_tokens, 1024)
            self.assertIs(request.config.response_schema, schema)

    def test_largest_bounded_proposal_is_compact_relative_to_output_ceiling(
        self,
    ) -> None:
        proposal = ProposalOutput(
            snapshot_id="s" * 200,
            market_id="m" * 200,
            action="trade",
            probability=1.0,
            amount=1.0,
            citations=[str(index) * 128 for index in range(10)],
        )

        properties = ProposalOutput.model_json_schema()["properties"]
        self.assertEqual(properties["snapshot_id"]["maxLength"], 200)
        self.assertEqual(properties["market_id"]["maxLength"], 200)
        self.assertLess(len(proposal.model_dump_json()), 4 * 1024)

    def test_truncated_model_json_fails_without_fill_and_settles_reservation(
        self,
    ) -> None:
        trader, reviewer, _ = self.models()
        trader.response = {}
        sessions = InMemorySessionService()

        async def run_and_read_state() -> dict[str, object]:
            trader.raw_response = '{"snapshot_id":"snapshot"'
            with (
                patch(
                    "chrysopoeia.cost.settle_model_call", wraps=settle_model_call
                ) as settle,
                self.assertRaises(ValueError),
            ):
                await run_paper_cycle_state(
                    self.config,
                    self.snapshot,
                    OperatingConfig(),
                    trader,
                    reviewer,
                    session_service=sessions,
                )
            settle.assert_called_once()
            session = await sessions.get_session(
                app_name="chrysopoeia_cycle",
                user_id="operator",
                session_id="paper-cycle",
            )
            self.assertIsNotNone(session)
            return dict(session.state)

        state = asyncio.run(run_and_read_state())

        self.assertNotIn(PAPER_CYCLE_FILL_KEY, state)
        self.assertNotIn("paper_cycle_report", state)
        ledger = state.get(LEDGER_KEY, [])
        self.assertIsInstance(ledger, list)
        assert isinstance(ledger, list)
        self.assertNotIn("reserved", {record["status"] for record in ledger})

    def test_actual_runner_uses_one_or_two_calls_and_returns_sanitized_summary(
        self,
    ) -> None:
        for action, count, status in (
            ("abstain", 1, "abstained"),
            ("trade", 2, "filled"),
        ):
            trader, reviewer, calls = self.models(action)
            summary = asyncio.run(
                run_paper_cycle(
                    self.config, self.snapshot, OperatingConfig(), trader, reviewer
                )
            )

            with self.subTest(action=action):
                self.assertEqual(len(calls), count)
                self.assertEqual(summary["status"], status)
                self.assertEqual(summary["reviewer_called"], count == 2)
                self.assertEqual(summary["maximum_reserved_cost_usd"], "0.022528")
                self.assertLessEqual(
                    Decimal(summary["actual_estimated_cost_usd"]), Decimal("0.022528")
                )
                self.assertEqual(
                    set(summary),
                    {
                        "schema_version",
                        "record_type",
                        "snapshot_id",
                        "market_id",
                        "status",
                        "reason",
                        "trader_called",
                        "reviewer_called",
                        "fill",
                        "ledger_statuses",
                        "actual_estimated_cost_usd",
                        "maximum_reserved_cost_usd",
                    },
                )
                self.assertNotIn("probability", json.dumps(summary))

    def test_one_call_budget_allows_abstention_but_not_a_second_call(self) -> None:
        budget = Decimal("0.011264")
        for action, succeeds in (("abstain", True), ("trade", False)):
            trader, reviewer, _ = self.models(action)
            operating = replace(
                OperatingConfig(), daily_cloud_cost_budget=float(budget)
            )
            if succeeds:
                asyncio.run(
                    run_paper_cycle(
                        self.config, self.snapshot, operating, trader, reviewer
                    )
                )
            else:
                with self.assertRaises(ValueError):
                    asyncio.run(
                        run_paper_cycle(
                            self.config, self.snapshot, operating, trader, reviewer
                        )
                    )

    def test_operating_exposure_limits_control_deterministic_policy(self) -> None:
        trader, reviewer, _ = self.models()
        operating = replace(OperatingConfig(), maximum_market_exposure=0.005)

        summary = asyncio.run(
            run_paper_cycle(self.config, self.snapshot, operating, trader, reviewer)
        )

        self.assertEqual(summary["status"], "rejected")
        self.assertEqual(summary["reason"], "per-market exposure limit exceeded")

    def test_external_evidence_is_identical_for_trader_and_reviewer(self) -> None:
        external = [
            external_evidence(
                self.snapshot,
                "https://example.com/report",
                "Weather report",
                "2026-09-02T00:00:00Z",
            )
        ]
        evidence = [*_canonical_evidence(self.snapshot), *external]
        trader, reviewer, calls = self.models()
        citation = external[0].evidence_id
        trader.response["citations"] = [citation]
        reviewer.response["citations"] = [citation]

        state, function_calls, available_tools = asyncio.run(
            run_paper_cycle_state(
                self.config,
                self.snapshot,
                OperatingConfig(),
                trader,
                reviewer,
                evidence=evidence,
            )
        )

        self.assertEqual(
            calls, [self.config.models.trader, self.config.models.reviewer]
        )
        prompts = [request.contents[-1].parts[0].text for request in trader.requests]
        self.assertTrue(all(citation in prompt for prompt in prompts))
        self.assertEqual(
            state["paper_cycle_evidence"],
            [record.model_dump() for record in evidence],
        )
        self.assertEqual(state["paper_cycle_report"]["status"], "filled")
        self.assertEqual((function_calls, available_tools), ([], []))
        self.assertTrue(all(not request.config.tools for request in trader.requests))

    def test_cycle_rejects_unvalidated_external_evidence_before_model_calls(
        self,
    ) -> None:
        trader, reviewer, calls = self.models()
        with self.assertRaises(ValueError):
            asyncio.run(
                run_paper_cycle(
                    self.config,
                    self.snapshot,
                    OperatingConfig(),
                    trader,
                    reviewer,
                    evidence=[],
                )
            )
        self.assertEqual(calls, [])

    def test_model_resolution_routes_gemini_and_litellm_prefixes(self) -> None:
        from chrysopoeia.cycle_runner import resolve_model

        resolved = resolve_model("adk-registry", "gemini-flash-latest")
        self.assertEqual(type(resolved).__name__, "Gemini")
        try:
            luz = resolve_model("adk-registry", "ollama/llama3.1:8b")
        except ValueError as raised:
            # litellm is an optional google-adk[extensions] provider extra
            self.assertIn("litellm", str(raised))
        else:
            self.assertEqual(type(luz).__name__, "LiteLlm")


if __name__ == "__main__":
    unittest.main()
