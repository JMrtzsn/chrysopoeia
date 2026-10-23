import asyncio
import json
import os
import tempfile
import unittest
from collections.abc import AsyncGenerator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from google.adk.models import BaseLlm, Gemini, LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import Field, SkipValidation

from chrysopoeia.configuration import load_harness_config
from chrysopoeia.context_learning import build_history_evidence
from chrysopoeia.context_profiles import bundled_profiles
from chrysopoeia.cost import LEDGER_KEY, settle_model_call
from chrysopoeia.cycle_runner import (
    GROUNDING_QUERY_PRICE_USD,
    MAX_RESEARCH_QUERIES,
    MissingTraderOutputError,
    normalize_grounding_metadata,
    reserved_ceiling,
    run_paper_cycle,
    run_paper_cycle_state,
    summarize_cycle,
)
from chrysopoeia.models import resolve_context_model, resolve_model
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
    checked: bool = False

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=True)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.calls.append(self.model)
        self.requests.append(llm_request)
        if self.response.get("action") == "trade" and not self.checked:
            self.checked = True
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(
                        id="plan-check",
                        name="check_trade_plan",
                        args={"plan": self.response},
                    ))],
                ),
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=11, candidates_token_count=7
                ),
            )
            return
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


class FailingLlm(FakeLlm):
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del llm_request, stream
        raise RuntimeError("search unavailable")
        yield


class GroundedLlm(FakeLlm):
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        del stream
        self.requests.append(llm_request)
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="Grounded.")]),
            grounding_metadata=types.GroundingMetadata(
                grounding_chunks=[
                    types.GroundingChunk(
                        web={"uri": "https://example.com/report", "title": "Report"}
                    )
                ],
                grounding_supports=[
                    types.GroundingSupport(
                        grounding_chunk_indices=[0],
                        segment=types.Segment(text="Relevant evidence."),
                    )
                ],
                web_search_queries=["market evidence"],
            ),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=11, candidates_token_count=7
            ),
        )


class OverCeilingGroundedLlm(GroundedLlm):
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        async for response in super().generate_content_async(llm_request, stream):
            assert response.grounding_metadata is not None
            response.grounding_metadata.web_search_queries = [
                str(index) for index in range(100)
            ]
            yield response


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
                "rationale": "Evidence supports this choice.",
                "max_entry_price": 0.41 if action == "trade" else None,
                "exit_plan": {
                    "take_profit_roi": 0.1,
                    "stop_loss_roi": -0.2,
                    "exit_by": "2026-10-01T00:00:00+00:00",
                    "hold_to_resolution": False,
                } if action == "trade" else None,
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

    def test_window_baseline_is_attached_as_citable_evidence_when_enabled(self) -> None:
        from dataclasses import replace as dc_replace

        from chrysopoeia.configuration import VenueConfig
        from chrysopoeia.paper_cycle import external_evidence

        trader, reviewer, _ = self.models("abstain")
        record = external_evidence(
            self.snapshot,
            "https://www.bitstamp.net/api/?market=BTC/USD",
            "BTC 5m deterministic window baseline",
            self.snapshot.captured_at,
            excerpt="baseline_p_up=0.620",
        )
        config = replace(
            self.config,
            venue=VenueConfig(
                "polymarket", 0.02, "paper-assumption:flat-2pct-v1",
                "btc-updown-5m", 120.0, True,
            ),
            research=dc_replace(self.config.research, enabled=False),
        )

        with patch(
            "chrysopoeia.window_baseline.baseline_evidence", return_value=record
        ):
            state, _, _ = asyncio.run(
                run_paper_cycle_state(
                    config,
                    self.snapshot,
                    OperatingConfig(),
                    trader,
                    reviewer,
                    FakeLlm(model=config.models.context, calls=[], response={}),
                )
            )

        self.assertEqual(
            state["validated_external_evidence"][0]["evidence_id"], record.evidence_id
        )

    def test_bigquery_history_becomes_bounded_context_evidence(self) -> None:
        snapshot = replace(self.snapshot, source_url="https://polymarket.com/event/btc-updown-5m-1792600000")
        profile = bundled_profiles()[0]
        history = {
            "scope_key": "polymarket:series:btc-updown-5m",
            "profile_id": "crypto.btcusd.5m.updown",
            "profile_version": 1,
            "as_of": snapshot.captured_at,
            "lookback_days": 90,
            "profile_version_count": 1,
            "decision_count": 12,
            "plan_ready_count": 4,
            "abstained_count": 5,
            "rejected_count": 3,
            "consumer_rejected_count": 1,
            "filled_count": 3,
            "completed_trade_count": 2,
            "winning_trade_count": 1,
            "realized_pnl_usd": -0.25,
            "outcome_watermark": "2026-10-20T00:00:00+00:00",
        }

        evidence = build_history_evidence(snapshot, profile, history, "p.d.raw_events")

        self.assertEqual(evidence.source_kind, "external")
        self.assertIn('"profile_version":1', evidence.excerpt or "")
        self.assertIn('"decision_count":12', evidence.excerpt or "")
        self.assertIn("bigquery", evidence.url)

    def test_disabled_research_skips_grounding_and_its_cost_reservation(self) -> None:
        from chrysopoeia.configuration import ResearchConfig

        trader, reviewer, _ = self.models("abstain")
        active = replace(
            self.config,
            research=ResearchConfig(enabled=False),
        )
        state, _, _ = asyncio.run(
            run_paper_cycle_state(
                active,
                self.snapshot,
                OperatingConfig(),
                trader,
                reviewer,
                FakeLlm(model=active.models.context, calls=[], response={}),
            )
        )
        summary = summarize_cycle(active, self.snapshot, state)

        self.assertEqual(state["research"]["reason"], "research disabled")
        self.assertEqual(state["research"]["query_count"], 0)
        self.assertGreater(
            reserved_ceiling(self.config) - reserved_ceiling(active),
            Decimal("0.4"),
        )
        self.assertEqual(summary["status"], "abstained")

    def test_missing_proposal_records_cost_denial_and_call_count_in_failed_turn(self) -> None:
        from chrysopoeia.accounting import open_session, replay
        from chrysopoeia.operations import run_journal_turn

        trader, reviewer, _ = self.models()
        config = replace(self.config, cost=replace(self.config.cost, maximum_model_calls_per_cycle=1))

        async def run(config, snapshot, operating, **kwargs):
            return await run_paper_cycle(config, snapshot, operating, trader, reviewer, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory)
            open_session(journal, 1000, 100)
            with self.assertRaises(RuntimeError):
                asyncio.run(run_journal_turn(journal, config, self.snapshot, OperatingConfig(), run=run))
            records = [json.loads(line) for line in (journal / "chrysopoeia.jsonl").read_text().splitlines()]
            finished = records[-1]
            self.assertEqual(finished["record_type"], "turn_finished")
            self.assertEqual(finished["outcome"], "failed")
            self.assertEqual(finished["failure"], {
                "error_code": "MODEL_COST_POLICY_DENIED",
                "message": "cycle model-call ceiling is exhausted",
                "model_calls": 1,
            })
            self.assertEqual(list(replay(journal).finished_turns.values()), ["failed"])

    def test_missing_proposal_diagnostics_do_not_persist_provider_text(self) -> None:
        from chrysopoeia.cycle_runner import _trader_failure

        failure = _trader_failure("provider secret", "credential=secret private rationale", [])
        self.assertEqual(failure, {
            "error_code": "TRADER_OUTPUT_MISSING",
            "message": "trader ended without a structured proposal; cause unavailable",
            "model_calls": 0,
        })
        denied = _trader_failure("MODEL_COST_POLICY_DENIED", "private provider body", [])
        self.assertEqual(denied["message"], "model call denied by cost policy; detail unavailable")

    def test_empty_trader_output_reports_unknown_cause_without_inventing_a_denial(self) -> None:
        trader, reviewer, _ = self.models("abstain")
        trader.raw_response = ""

        with self.assertRaises(MissingTraderOutputError) as raised:
            asyncio.run(run_paper_cycle(self.config, self.snapshot, OperatingConfig(), trader, reviewer))

        self.assertEqual(raised.exception.failure["error_code"], "TRADER_OUTPUT_MISSING")
        self.assertEqual(raised.exception.failure["model_calls"], 1)

    def test_cycle_requests_disable_thinking_and_keep_cost_output_ceiling(self) -> None:
        trader, reviewer, _ = self.models()

        asyncio.run(
            run_paper_cycle(
                self.config, self.snapshot, OperatingConfig(), trader, reviewer
            )
        )

        self.assertEqual(len(trader.requests), 3)
        for request, schema in zip(
            trader.requests, (ProposalOutput, ProposalOutput, ReviewOutput), strict=True
        ):
            self.assertEqual(request.config.thinking_config.thinking_budget, 0)
            self.assertEqual(request.config.max_output_tokens, 3072)
            self.assertIs(request.config.response_schema, schema)

    def test_reserved_ceiling_uses_configured_model_call_cap(self) -> None:
        self.assertEqual(
            reserved_ceiling(self.config),
            Decimal("0.5271552") + 30 * GROUNDING_QUERY_PRICE_USD,
        )

    def test_cycle_cost_includes_grounding_queries(self) -> None:
        trader, reviewer, _ = self.models("abstain")
        state, _, _ = asyncio.run(
            run_paper_cycle_state(
                self.config, self.snapshot, OperatingConfig(), trader, reviewer
            )
        )
        base = Decimal(summarize_cycle(self.config, self.snapshot, state)["actual_estimated_cost_usd"])
        state["research"] = {"status": "ok", "reason": None, "query_count": 2}

        charged = Decimal(
            summarize_cycle(self.config, self.snapshot, state)["actual_estimated_cost_usd"]
        )

        self.assertEqual(charged - base, 2 * GROUNDING_QUERY_PRICE_USD)

    def test_grounding_metadata_becomes_bounded_deduplicated_evidence(self) -> None:
        metadata = types.GroundingMetadata(
            grounding_chunks=[
                types.GroundingChunk(web={"uri": "https://EXAMPLE.com:443/a", "title": " A\nreport "}),
                types.GroundingChunk(web={"uri": "https://example.com/a", "title": "duplicate"}),
                types.GroundingChunk(web={"uri": "http://example.com/b", "title": "bad"}),
                *(types.GroundingChunk(web={"uri": f"https://example.com/{index}", "title": str(index)}) for index in range(10)),
            ],
            grounding_supports=[
                types.GroundingSupport(
                    grounding_chunk_indices=[0],
                    segment=types.Segment(text=" useful\u0000 " + "x" * 600),
                )
            ],
            web_search_queries=["one", "two"],
        )

        evidence, query_count = normalize_grounding_metadata(self.snapshot, [metadata])

        self.assertEqual(query_count, 2)
        self.assertEqual(len(evidence), 8)
        self.assertEqual(evidence[0].url, "https://example.com/a")
        self.assertEqual(evidence[0].title, "A report")
        self.assertEqual(len(evidence[0].excerpt or ""), 500)

    def test_grounding_metadata_records_every_billed_query(self) -> None:
        metadata = types.GroundingMetadata(
            web_search_queries=[str(index) for index in range(31)]
        )

        _, query_count = normalize_grounding_metadata(self.snapshot, [metadata])

        self.assertEqual(query_count, 31)

    def test_temporary_five_call_verification_cap(self) -> None:
        self.assertEqual(
            reserved_ceiling(self.config, 5),
            Decimal("0.219648") + 30 * GROUNDING_QUERY_PRICE_USD,
        )

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
            rationale="r" * 500,
            max_entry_price=0.5,
            exit_plan={
                "take_profit_roi": 0.1,
                "stop_loss_roi": -0.2,
                "exit_by": "2026-10-01T00:00:00+00:00",
                "hold_to_resolution": False,
            },
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
            ("trade", 3, "approved"),
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
                self.assertEqual(summary["reviewer_called"], action == "trade")
                self.assertEqual(summary["maximum_reserved_cost_usd"], "0.9471552")
                self.assertLessEqual(
                    Decimal(summary["actual_estimated_cost_usd"]), Decimal("0.9471552")
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
                        "event",
                        "outcome_event",
                        "ledger_statuses",
                        "actual_estimated_cost_usd",
                        "maximum_reserved_cost_usd",
                    },
                )
                if action == "abstain":
                    self.assertEqual(summary["outcome_event"]["proposal"]["probability"], 0.4)
                if action == "trade":
                    self.assertEqual(summary["event"]["record_type"], "trade_plan_ready")
                    self.assertEqual(summary["event"]["event_id"], "turn-acf2dcd35e81b75dc8316170")
                    self.assertIsNone(summary["fill"])
                else:
                    self.assertIsNone(summary["event"])

    def test_each_terminal_node_records_exactly_one_outcome_status(self) -> None:
        for action, approved, checked, expected in (
            ("abstain", True, False, "abstained"),
            ("trade", True, True, "plan_check_rejected"),
            ("trade", False, False, "reviewer_rejected"),
            ("trade", True, False, "plan_ready"),
        ):
            trader, reviewer, _ = self.models(action, approved)
            trader.checked = checked
            state, _, _ = asyncio.run(
                run_paper_cycle_state(self.config, self.snapshot, OperatingConfig(), trader, reviewer)
            )

            with self.subTest(expected=expected):
                self.assertEqual(state["paper_cycle_outcome_status"], expected)
                summary = summarize_cycle(self.config, self.snapshot, state)
                self.assertEqual(summary["outcome_event"]["status"], expected)
                del state["paper_cycle_outcome_status"]
                with self.assertRaisesRegex(ValueError, "terminal outcome"):
                    summarize_cycle(self.config, self.snapshot, state)

    def test_one_call_budget_allows_abstention_but_not_a_second_call(self) -> None:
        budget = Decimal("0.0439296")
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
                with self.assertRaises(MissingTraderOutputError) as raised:
                    asyncio.run(
                        run_paper_cycle(
                            self.config, self.snapshot, operating, trader, reviewer
                        )
                    )
                self.assertEqual(raised.exception.failure["error_code"], "MODEL_COST_POLICY_DENIED")

    def test_operating_exposure_limits_control_deterministic_policy(self) -> None:
        trader, reviewer, _ = self.models()
        operating = replace(OperatingConfig(), maximum_market_exposure=0.005)

        summary = asyncio.run(
            run_paper_cycle(self.config, self.snapshot, operating, trader, reviewer)
        )

        self.assertEqual(summary["status"], "rejected")
        self.assertEqual(summary["reason"], "no plan check passed")
        self.assertFalse(summary["reviewer_called"])

    def test_trade_requires_explicit_check_tool_call_before_reviewer(self) -> None:
        trader, reviewer, calls = self.models()
        trader.checked = True

        summary = asyncio.run(
            run_paper_cycle(
                self.config, self.snapshot, OperatingConfig(), trader, reviewer
            )
        )

        self.assertEqual(calls, [self.config.models.trader])
        self.assertEqual(summary["status"], "rejected")
        self.assertEqual(
            summary["reason"],
            "no plan check was run",
        )
        self.assertFalse(summary["reviewer_called"])
        self.assertIsNone(summary["event"])
        self.assertEqual(summary["outcome_event"]["plan_checks"], [])

    def test_summary_uses_tool_selected_snapshot_and_rejects_target_switch(self) -> None:
        trader, reviewer, _ = self.models("abstain")
        state, _, _ = asyncio.run(
            run_paper_cycle_state(
                self.config, self.snapshot, OperatingConfig(), trader, reviewer
            )
        )
        state["market_snapshot"] = {
            **state["market_snapshot"],
            "snapshot_id": "switched",
            "market_id": "other",
        }

        with self.assertRaisesRegex(ValueError, "snapshot identity"):
            summarize_cycle(self.config, self.snapshot, state)

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

        self.assertEqual(calls, [self.config.models.trader] * 3)
        prompts = [
            request.contents[-1].parts[0].text
            for request in trader.requests
            if request.contents[-1].parts[0].text is not None
        ]
        self.assertTrue(all(citation in prompt for prompt in prompts))
        self.assertEqual(
            state["paper_cycle_evidence"],
            [record.model_dump() for record in evidence],
        )
        self.assertEqual(state["paper_cycle_report"]["status"], "approved")
        self.assertEqual(function_calls, ["check_trade_plan"])
        self.assertEqual(
            available_tools,
            ["find_markets", "get_market", "check_trade_plan"],
        )
        self.assertTrue(trader.requests[0].config.tools)
        self.assertTrue(trader.requests[1].config.tools)
        self.assertFalse(trader.requests[2].config.tools)

    def test_research_failure_keeps_canonical_cycle_available(self) -> None:
        trader, reviewer, _ = self.models("abstain")
        context = FailingLlm(model=self.config.models.context, calls=[], response={})

        summary = asyncio.run(
            run_paper_cycle(
                self.config,
                self.snapshot,
                OperatingConfig(),
                trader,
                reviewer,
                context,
            )
        )

        self.assertEqual(summary["status"], "abstained")
        self.assertEqual(
            summary["outcome_event"]["research"],
            {"status": "unavailable", "reason": "research failed", "query_count": 0},
        )
        self.assertEqual(
            [item["source_kind"] for item in summary["outcome_event"]["evidence"]],
            ["market_snapshot"],
        )

    def test_research_disables_thinking_and_keeps_event_grounding_metadata(self) -> None:
        trader, reviewer, _ = self.models("abstain")
        context = GroundedLlm(
            model=self.config.models.context, calls=[], requests=[], response={}
        )

        summary = asyncio.run(
            run_paper_cycle(
                self.config,
                self.snapshot,
                OperatingConfig(),
                trader,
                reviewer,
                context,
            )
        )

        self.assertEqual(context.requests[0].config.thinking_config.thinking_budget, 0)
        self.assertEqual(
            summary["outcome_event"]["research"],
            {"status": "ok", "reason": None, "query_count": 1},
        )
        self.assertEqual(
            summary["outcome_event"]["evidence"][1]["url"],
            "https://example.com/report",
        )

    def test_research_query_ceiling_discards_evidence_before_trader(self) -> None:
        trader, reviewer, calls = self.models("abstain")
        context = OverCeilingGroundedLlm(
            model=self.config.models.context, calls=[], requests=[], response={}
        )

        summary = asyncio.run(
            run_paper_cycle(
                self.config,
                self.snapshot,
                OperatingConfig(),
                trader,
                reviewer,
                context,
            )
        )

        self.assertEqual(calls, [self.config.models.trader])
        self.assertEqual(
            summary["outcome_event"]["research"],
            {
                "status": "unavailable",
                "reason": "query ceiling exceeded",
                "query_count": 100,
            },
        )
        self.assertEqual(
            [item["source_kind"] for item in summary["outcome_event"]["evidence"]],
            ["market_snapshot"],
        )
        self.assertGreater(
            Decimal(summary["actual_estimated_cost_usd"]),
            Decimal(summary["maximum_reserved_cost_usd"]),
        )

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
        resolved = resolve_model(self.config.models, "gemini-3.5-flash")
        self.assertIsInstance(resolved, Gemini)
        self.assertEqual(
            resolved.client_kwargs,
            {"vertexai": True, "location": "us"},
        )

        resolved = resolve_model(
            replace(self.config.models, adapter="adk-registry"),
            "gemini-flash-latest",
        )
        self.assertEqual(type(resolved).__name__, "Gemini")
        try:
            luz = resolve_model(
                replace(self.config.models, adapter="adk-registry"),
                "ollama/llama3.1:8b",
            )
        except ValueError as raised:
            # litellm is an optional google-adk[extensions] provider extra
            self.assertIn("litellm", str(raised))
        else:
            self.assertEqual(type(luz).__name__, "LiteLlm")

    def test_context_model_uses_the_selected_adapter(self) -> None:
        from chrysopoeia.models import resolve_context_model, supports_grounding

        vertex = resolve_context_model(self.config.models)
        self.assertIsInstance(vertex, Gemini)
        self.assertTrue(supports_grounding(vertex))
        self.assertEqual(vertex.client_kwargs, {"vertexai": True, "location": "us"})

        registry = resolve_context_model(
            replace(self.config.models, adapter="adk-registry"),
        )
        self.assertEqual(registry.model, self.config.models.context)

        try:
            other = resolve_context_model(
                replace(
                    self.config.models,
                    adapter="adk-registry",
                    context="openrouter/openai/gpt-4.1-mini",
                )
            )
        except ValueError as raised:
            # litellm is an optional google-adk[extensions] provider extra
            self.assertIn("litellm", str(raised))
        else:
            self.assertFalse(supports_grounding(other))


    def test_research_provider_and_allowance_follow_the_context_model(self) -> None:
        from chrysopoeia.cycle_runner import research_allowance
        from chrysopoeia.models import resolve_research_provider

        self.assertEqual(resolve_research_provider(self.config.models), "google-search")
        openrouter = replace(self.config.models, context="openrouter/openai/gpt-4.1-mini")
        self.assertEqual(resolve_research_provider(openrouter), "openrouter-web")
        self.assertEqual(
            resolve_research_provider(replace(self.config.models, context="ollama/llama3.1:8b")),
            "none",
        )
        self.assertEqual(
            research_allowance(self.config),
            Decimal(MAX_RESEARCH_QUERIES) * GROUNDING_QUERY_PRICE_USD,
        )
        self.assertEqual(
            research_allowance(replace(self.config, models=openrouter)),
            Decimal("0.02"),
        )

    def test_cycle_uses_openrouter_web_research_when_configured(self) -> None:
        config = load_harness_config(ROOT / "configs" / "openrouter.toml")
        cited = external_evidence(
            self.snapshot,
            "https://example.com/report",
            "Report",
            self.snapshot.captured_at,
            excerpt="Relevant excerpt.",
        )
        calls: list[str] = []
        requests: list[LlmRequest] = []
        trader = FakeLlm(
            model=config.models.trader,
            calls=calls,
            requests=requests,
            response={
                "snapshot_id": "snapshot",
                "market_id": "market",
                "action": "abstain",
                "probability": 0.4,
                "amount": 0,
                "citations": [],
                "rationale": "No edge.",
                "max_entry_price": None,
                "exit_plan": None,
            },
        )
        reviewer = FakeLlm(
            model=config.models.reviewer, calls=calls, requests=requests, response={}
        )
        with (
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
            patch(
                "chrysopoeia.cycle_runner.openrouter_web_research",
                return_value=([cited], 1, 100, 20),
            ) as researched,
        ):
            summary = asyncio.run(
                run_paper_cycle(
                    config,
                    self.snapshot,
                    OperatingConfig(),
                    trader,
                    reviewer,
                    resolve_context_model(config.models),
                )
            )

        researched.assert_called_once()
        self.assertEqual(summary["outcome_event"]["research"]["status"], "ok")
        self.assertEqual(
            [item["url"] for item in summary["outcome_event"]["evidence"]],
            [
                "https://polymarket.com/event/will-it-rain",
                "https://example.com/report",
            ],
        )


if __name__ == "__main__":
    unittest.main()
