import asyncio
import copy
import json
import math
import unittest
from collections.abc import AsyncGenerator
from dataclasses import asdict
from types import SimpleNamespace

from google.adk.models import BaseLlm
from google.adk.models._capabilities import LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.state import State
from google.adk.workflow import Workflow
from google.genai import types
from google.genai._transformers import process_schema
from pydantic import SkipValidation, ValidationError

from chrysopoeia.agent import (
    DEFAULT_HARNESS_CONFIG,
    bound_review_reason,
    bound_trader_rationale,
    complete_abstention,
    complete_paper_cycle,
    paper_cycle_workflow,
    prepare_reviewer_input,
    prepare_trader_input,
    reviewer_agent,
    root_agent,
    route_proposal,
    trader_agent,
)
from chrysopoeia.cost import after_model_cost, before_model_cost, on_model_cost_error
from chrysopoeia.paper_cycle import (
    EVIDENCE_KEY,
    LAST_SUCCESSFUL_PLAN_KEY,
    LAST_SUCCESSFUL_SNAPSHOT_KEY,
    PAPER_CYCLE_DECISION_KEY,
    PAPER_CYCLE_FILL_KEY,
    PAPER_CYCLE_REPORT_KEY,
    PROPOSAL_KEY,
    REVIEW_KEY,
    TRADE_PLAN_READY_KEY,
    EvidenceRecord,
    ExitPlanOutput,
    PaperCycleRequest,
    ProposalOutput,
    ReviewerInput,
    ReviewOutput,
    finalize_paper_cycle,
)
from chrysopoeia.trading import BookLevel, MarketSnapshot, OperatingConfig

EVIDENCE_ID = "market_snapshot:snapshot-1"
EXIT_PLAN = {
    "take_profit_roi": 0.1,
    "stop_loss_roi": -0.2,
    "exit_by": "2026-09-01T12:00:00+00:00",
    "hold_to_resolution": False,
}


def rich_snapshot(snapshot_id: str = "snapshot-1") -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id, "market-1", 0.4, 1_000, 0, 0,
        question="Will it rain?",
        resolution_rules="Resolves Yes if rain is measured.",
        end_time="2026-09-02T00:00:00+00:00",
        captured_at="2026-09-01T00:00:00+00:00",
        source_url="https://polymarket.com/event/will-it-rain",
        yes_token_id="yes-token",
        asks=(BookLevel(0.4, 100),),
        book_captured_at="2026-09-01T00:00:00+00:00",
    )


def cycle_state(*, approved: bool = True) -> dict[str, object]:
    state = {
        "operating_config": asdict(OperatingConfig()),
        "market_snapshot": asdict(rich_snapshot()),
        EVIDENCE_KEY: [{
            "evidence_id": EVIDENCE_ID,
            "url": "https://polymarket.com/event/will-it-rain",
            "title": "Will it rain?",
            "retrieved_at": "2026-09-01T00:00:00+00:00",
            "source_kind": "market_snapshot",
            "snapshot_id": "snapshot-1",
        }],
        PROPOSAL_KEY: {
            "snapshot_id": "snapshot-1",
            "market_id": "market-1",
            "action": "trade",
            "probability": 0.46,
            "amount": 10,
            "max_entry_price": 0.41,
            "exit_plan": EXIT_PLAN,
            "citations": [EVIDENCE_ID],
            "rationale": "Evidence supports a modest edge.",
        },
        REVIEW_KEY: {
            "snapshot_id": "snapshot-1",
            "market_id": "market-1",
            "approved": approved,
            "reason": "supported" if approved else "weak evidence",
            "citations": [EVIDENCE_ID] if approved else [],
        },
    }
    state[LAST_SUCCESSFUL_PLAN_KEY] = copy.deepcopy(state[PROPOSAL_KEY])
    state[LAST_SUCCESSFUL_SNAPSHOT_KEY] = copy.deepcopy(state["market_snapshot"])
    return state


class StructuredFakeLlm(BaseLlm):
    calls: SkipValidation[list[str]]
    response: dict[str, object]
    agent_name: str
    checked: bool = False

    @property
    def capabilities(self) -> LlmCapabilities:
        # Declare explicitly: the deprecated name-based fallback reads
        # GOOGLE_GENAI_USE_VERTEXAI from os.environ, which litellm's import-time
        # load_dotenv() can flip mid-suite when .env sets it.
        return LlmCapabilities(output_schema_and_tools=False)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        if stream or (self.agent_name in self.calls and self.agent_name != trader_agent.name):
            raise AssertionError(f"unexpected {self.agent_name} model request")
        self.calls.append(self.agent_name)
        if self.agent_name == trader_agent.name:
            if self.response.get("action") == "trade" and not self.checked:
                self.checked = True
                parts = [types.Part(function_call=types.FunctionCall(
                    id="plan-check",
                    name="check_trade_plan",
                    args={"plan": self.response},
                ))]
                yield LlmResponse(
                    content=types.Content(role="model", parts=parts),
                    usage_metadata=types.GenerateContentResponseUsageMetadata(
                        prompt_token_count=11, candidates_token_count=7,
                    ),
                )
                return
            if llm_request.config.response_schema is not None or "set_model_response" not in llm_request.tools_dict:
                raise AssertionError("trader request did not use set_model_response")
            parts = [types.Part(function_call=types.FunctionCall(
                id="trader-response",
                name="set_model_response",
                args=self.response,
            ))]
        else:
            if llm_request.config.response_schema is None or llm_request.tools_dict:
                raise AssertionError("reviewer request did not use native structured output")
            parts = [types.Part(text=json.dumps(self.response))]
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=11,
                candidates_token_count=7,
            ),
        )


class PaperCycleTests(unittest.TestCase):
    def test_finalizer_accepts_real_adk_state(self) -> None:
        values = cycle_state()
        state = State(values, {})

        report = finalize_paper_cycle(state, ReviewOutput.model_validate(values[REVIEW_KEY]))

        self.assertEqual(report["status"], "approved")
        self.assertEqual(state[PAPER_CYCLE_REPORT_KEY], report)

    def test_finalizer_rejects_malformed_partial_state_shape(self) -> None:
        class BadGetter:
            def get(self) -> object:
                return cycle_state()

            def __setitem__(self, key: str, value: object) -> None:
                del key, value

        class BadSetter:
            def __init__(self) -> None:
                self.values = cycle_state()

            def get(self, key: str, default: object = None) -> object:
                return self.values.get(key, default)

            def __setitem__(self, key: str) -> None:
                del key

        review = ReviewOutput.model_validate(cycle_state()[REVIEW_KEY])
        for state in (BadGetter(), BadSetter()):
            with self.subTest(state=type(state).__name__), self.assertRaisesRegex(ValueError, "^session state is invalid$"):
                finalize_paper_cycle(state, review)

    def test_model_output_schemas_are_vertex_compatible_and_validate_actions(self) -> None:
        for output_schema in (ProposalOutput, ExitPlanOutput, ReviewOutput, EvidenceRecord, ReviewerInput):
            schema = output_schema.model_json_schema()
            process_schema(schema, None)
            with self.subTest(schema=output_schema.__name__):
                types.Schema.model_validate(schema)
        self.assertEqual(ProposalOutput(snapshot_id="snapshot-1", market_id="market-1", action="abstain", probability=0.4, amount=0, citations=[], rationale="No edge.", max_entry_price=None, exit_plan=None).action, "abstain")
        valid_trade = {
            "snapshot_id": "snapshot-1", "market_id": "market-1", "action": "trade",
            "probability": 0.55, "amount": 10, "citations": [EVIDENCE_ID],
            "rationale": "Evidence supports a trade.",
            "max_entry_price": 0.41, "exit_plan": EXIT_PLAN,
        }
        self.assertEqual(ProposalOutput.model_validate(valid_trade).exit_plan.take_profit_roi, 0.1)
        for changes in (
            {"max_entry_price": 1.0},
            {"exit_plan": {**EXIT_PLAN, "take_profit_roi": 0}},
            {"exit_plan": {**EXIT_PLAN, "stop_loss_roi": -1.1}},
            {"exit_plan": {**EXIT_PLAN, "stop_loss_roi": None, "hold_to_resolution": False}},
            {"exit_plan": {**EXIT_PLAN, "exit_by": "2026-09-01"}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                ProposalOutput.model_validate({**valid_trade, **changes})
        for action, amount in (("trade", 0), ("abstain", 1), ("invalid", 0), ("trade", math.nan), ("trade", math.inf), ("trade", True), ("trade", "1")):
            with self.subTest(action=action, amount=amount), self.assertRaises(ValidationError):
                ProposalOutput(snapshot_id="snapshot-1", market_id="market-1", action=action, probability=0.5, amount=amount, citations=[EVIDENCE_ID] if action == "trade" else [], rationale="Reason.")

    def test_cycle_request_bounds_untrusted_context_and_draft(self) -> None:
        request = PaperCycleRequest(context="weather only", draft={"action": "abstain"})
        self.assertEqual(request.context, "weather only")
        with self.assertRaises(ValidationError):
            PaperCycleRequest(context="x" * 2001)
        for draft in ({"credentials": "secret"}, {"exit_plan": {"token": "secret"}}):
            with self.subTest(draft=draft), self.assertRaises(ValidationError):
                PaperCycleRequest(draft=draft)
        with self.assertRaises(ValidationError):
            PaperCycleRequest(draft={"citations": ["x" * 200] * 101})

    def test_trader_input_allows_discovery_without_initial_snapshot(self) -> None:
        state = {"operating_config": asdict(OperatingConfig())}
        request = PaperCycleRequest(context="weather", draft={"action": "abstain"})
        self.assertEqual(
            prepare_trader_input(SimpleNamespace(state=state), request),
            {"context": "weather", "draft": {"action": "abstain"}},
        )

        evidence = EvidenceRecord(
            evidence_id=EVIDENCE_ID,
            url="https://polymarket.com/event/will-it-rain",
            title="Will it rain?",
            retrieved_at="2026-09-01T00:00:00Z",
            source_kind="market_snapshot",
            snapshot_id="snapshot-1",
        )
        with self.assertRaises(ValidationError):
            evidence.title = "changed"
        for changes in (
            {"evidence_id": "x" * 201},
            {"url": "http://polymarket.com/event/will-it-rain"},
            {"url": "https://polymarket.com/event/will-it-rain?forged=1"},
            {"title": "x" * 501},
            {"retrieved_at": "2026-09-01"},
            {"source_kind": "unknown"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EvidenceRecord.model_validate({**evidence.model_dump(), **changes})

    def test_rich_snapshot_prepares_one_canonical_evidence_record_for_both_agents(self) -> None:
        state = cycle_state()
        state[EVIDENCE_KEY] = [{"evidence_id": "injected"}]
        ctx = SimpleNamespace(state=state)

        trader_input = prepare_trader_input(ctx, PaperCycleRequest())
        proposal = ProposalOutput(
            snapshot_id="snapshot-1", market_id="market-1", action="trade",
            probability=0.55, amount=10, citations=[EVIDENCE_ID],
            rationale="Evidence supports a trade.",
            max_entry_price=0.41, exit_plan=EXIT_PLAN,
        )
        reviewer_input = prepare_reviewer_input(ctx, proposal)

        expected = [EvidenceRecord(
            evidence_id=EVIDENCE_ID,
            url="https://polymarket.com/event/will-it-rain",
            title="Will it rain?",
            retrieved_at="2026-09-01T00:00:00+00:00",
            source_kind="market_snapshot",
            snapshot_id="snapshot-1",
        ).model_dump()]
        self.assertEqual(state[EVIDENCE_KEY], expected)
        self.assertEqual(trader_input["evidence"], expected)
        self.assertEqual(reviewer_input.evidence, [EvidenceRecord.model_validate(expected[0])])
        self.assertEqual(reviewer_input.market_snapshot, state["market_snapshot"])
        self.assertEqual(
            EvidenceRecord.model_validate(expected[0]).url,
            rich_snapshot().source_url,
        )

    def test_proposal_citations_reject_invalid_trade_and_allow_empty_abstention(self) -> None:
        state = cycle_state()
        ctx = SimpleNamespace(state=state)
        prepare_trader_input(ctx, PaperCycleRequest())
        base = {
            "snapshot_id": "snapshot-1", "market_id": "market-1", "action": "trade",
            "probability": 0.55, "amount": 10,
            "rationale": "Evidence supports a trade.",
            "max_entry_price": 0.41, "exit_plan": EXIT_PLAN,
        }
        for citations in ([], ["unknown"], [EVIDENCE_ID, EVIDENCE_ID]):
            with self.subTest(citations=citations), self.assertRaises((ValidationError, ValueError)):
                route_proposal(ctx, ProposalOutput.model_validate({**base, "citations": citations}))
            self.assertNotIn(PAPER_CYCLE_FILL_KEY, state)

        state[EVIDENCE_KEY] = [{
            **state[EVIDENCE_KEY][0],
            "evidence_id": "market_snapshot:other",
            "snapshot_id": "other",
        }]
        with self.assertRaises(ValueError):
            route_proposal(ctx, ProposalOutput.model_validate({
                **base, "citations": ["market_snapshot:other"],
            }))
        abstain = ProposalOutput.model_validate({
            **base, "action": "abstain", "amount": 0, "citations": [],
            "max_entry_price": None, "exit_plan": None,
        })
        report = complete_abstention(SimpleNamespace(state=cycle_state()), abstain)
        self.assertEqual(report.status, "abstained")

        legacy = cycle_state()
        legacy["market_snapshot"] = asdict(
            MarketSnapshot("snapshot-1", "market-1", 0.4, 1_000, 0, 0)
        )
        legacy_ctx = SimpleNamespace(state=legacy)
        prepare_trader_input(legacy_ctx, PaperCycleRequest())
        self.assertEqual(legacy[EVIDENCE_KEY], [])
        self.assertEqual(complete_abstention(legacy_ctx, abstain).status, "abstained")

    def test_trade_without_exact_successful_tool_check_is_rejected(self) -> None:
        state = cycle_state()
        state.pop(LAST_SUCCESSFUL_PLAN_KEY)
        state.pop(LAST_SUCCESSFUL_SNAPSHOT_KEY)
        proposal = ProposalOutput.model_validate(cycle_state()[PROPOSAL_KEY])

        event = route_proposal(SimpleNamespace(state=state), proposal)
        self.assertEqual(event.actions.route, "unchecked")
        self.assertNotIn(LAST_SUCCESSFUL_PLAN_KEY, state)

        state[LAST_SUCCESSFUL_PLAN_KEY] = {**proposal.model_dump(), "amount": 9.0}
        self.assertEqual(
            route_proposal(SimpleNamespace(state=state), proposal).actions.route,
            "unchecked",
        )

    def test_reviewer_citations_reject_invalid_approval_and_allow_empty_rejection(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewOutput(
                snapshot_id="snapshot-1", market_id="market-1", approved=True,
                reason="supported", citations=[],
            )
        state = cycle_state()
        state[REVIEW_KEY] = {
            **state[REVIEW_KEY], "citations": ["unknown"],
        }
        with self.assertRaises(ValueError):
            finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))
        state = cycle_state(approved=False)
        preserved = copy.deepcopy(state[EVIDENCE_KEY])
        report = finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))
        self.assertEqual(report["reason"], "review_rejected")
        self.assertEqual(state[EVIDENCE_KEY], preserved)

    def test_complete_cycle_uses_exact_routed_review_over_stored_replacement(self) -> None:
        injected = {
            "snapshot_id": "snapshot-1",
            "market_id": "market-1",
            "approved": False,
            "reason": "injected replacement",
            "citations": [],
        }

        class ReplacingReviewState(dict[str, object]):
            replace_next_read = True

            def get(self, key: str, default: object = None) -> object:
                if key == REVIEW_KEY and self.replace_next_read:
                    self.replace_next_read = False
                    return injected
                return super().get(key, default)

        state = ReplacingReviewState(cycle_state())
        state[REVIEW_KEY] = injected
        routed = ReviewOutput(
            snapshot_id="snapshot-1",
            market_id="market-1",
            approved=True,
            reason="routed approval",
            citations=[EVIDENCE_ID],
        )

        report = complete_paper_cycle(SimpleNamespace(state=state), routed)

        self.assertEqual(report.status, "approved")
        self.assertTrue(state[PAPER_CYCLE_DECISION_KEY]["allowed"])
        self.assertEqual(state[REVIEW_KEY], routed.model_dump())

    def test_overlong_review_reason_is_truncated_not_fatal(self) -> None:
        raw = json.dumps({
            "snapshot_id": "snapshot-1", "market_id": "market-1", "approved": False,
            "reason": "x" * 2_000, "citations": [],
        })
        response = LlmResponse(content=types.Content(role="model", parts=[types.Part(text=raw)]))

        self.assertIn(bound_review_reason, reviewer_agent.after_model_callback)
        asyncio.run(bound_review_reason(SimpleNamespace(), response))
        review = ReviewOutput.model_validate_json(response.content.parts[0].text)

        self.assertEqual(review.reason, "x" * 500)

    def test_trader_rationale_is_required_bounded_and_model_output_is_truncated(self) -> None:
        proposal = cycle_state()[PROPOSAL_KEY]
        with self.assertRaises(ValidationError):
            ProposalOutput.model_validate({key: value for key, value in proposal.items() if key != "rationale"})
        with self.assertRaises(ValidationError):
            ProposalOutput.model_validate({**proposal, "rationale": "x" * 501})
        response = LlmResponse(content=types.Content(parts=[types.Part(
            function_call=types.FunctionCall(
                name="set_model_response", args={**proposal, "rationale": "x" * 2_000}
            )
        )]))

        asyncio.run(bound_trader_rationale(SimpleNamespace(), response))

        self.assertEqual(response.content.parts[0].function_call.args["rationale"], "x" * 500)

    def test_approved_state_cycle_emits_event_without_fill(self) -> None:
        state = cycle_state()
        state["model_cost_policy"] = {"version": "test"}
        state["model_cost_ledger"] = [{"status": "completed"}]
        preserved = copy.deepcopy({key: state[key] for key in (
            "operating_config", "market_snapshot", "model_cost_policy", "model_cost_ledger",
        )})

        report = finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))

        self.assertEqual(report["status"], "approved")
        self.assertIsNone(state[PAPER_CYCLE_FILL_KEY])
        event = state[TRADE_PLAN_READY_KEY]
        self.assertEqual(event["record_type"], "trade_plan_ready")
        self.assertEqual(event["reviewer_citations"], [EVIDENCE_ID])
        self.assertEqual(event["evidence_references"], [EVIDENCE_ID])
        self.assertNotIn("reason", event)
        self.assertTrue(state[PAPER_CYCLE_DECISION_KEY]["allowed"])
        self.assertEqual(state[PAPER_CYCLE_REPORT_KEY], report)
        self.assertEqual({key: state[key] for key in preserved}, preserved)

    def test_finalizer_rejects_unchecked_or_changed_plan_and_snapshot(self) -> None:
        for change in ("missing", "plan", "snapshot"):
            state = cycle_state()
            if change == "missing":
                del state[LAST_SUCCESSFUL_PLAN_KEY]
            elif change == "plan":
                state[PROPOSAL_KEY] = {**state[PROPOSAL_KEY], "amount": 9.0}
            else:
                state["market_snapshot"] = {
                    **state["market_snapshot"], "price": 0.41,
                    "asks": ({"price": 0.41, "size": 100},),
                }
            report = finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))
            with self.subTest(change=change):
                self.assertEqual(report["reason"], "trade requires a successful matching plan check")
                self.assertIsNone(state[TRADE_PLAN_READY_KEY])

    def test_offline_compiled_workflow_path_reaches_finalizer_in_order(self) -> None:
        state = cycle_state()
        del state[PROPOSAL_KEY]
        del state[REVIEW_KEY]
        ctx = SimpleNamespace(state=state)
        expected_order = [
            "__START__", "prepare_trader_input", trader_agent.name, "route_proposal", "prepare_reviewer_input",
            reviewer_agent.name, "complete_paper_cycle",
        ]

        order = ["__START__"]
        while order[-1] != expected_order[-1]:
            route = "trade" if order[-1] == "route_proposal" else None
            order.extend(paper_cycle_workflow.graph.get_next_pending_nodes(order[-1], route))
        trader_input = prepare_trader_input(ctx, PaperCycleRequest())
        self.assertEqual(trader_input["market_snapshot"], state["market_snapshot"])
        proposal = ProposalOutput.model_validate(cycle_state()[PROPOSAL_KEY])
        state[PROPOSAL_KEY] = proposal.model_dump()
        reviewer_input = prepare_reviewer_input(ctx, proposal)
        self.assertEqual(reviewer_input.market_snapshot, state["market_snapshot"])
        review = ReviewOutput(snapshot_id="snapshot-1", market_id="market-1", approved=True, reason="supported", citations=[EVIDENCE_ID])
        report = complete_paper_cycle(ctx, review)

        self.assertEqual(order, expected_order)
        self.assertEqual(report.status, "approved")
        self.assertIsNone(state[PAPER_CYCLE_FILL_KEY])
        self.assertEqual(state[REVIEW_KEY], review.model_dump())

    def test_serialized_rich_snapshot_rehydrates_and_reaches_both_agents(self) -> None:
        snapshot = MarketSnapshot(
            "snapshot-1", "market-1", 0.4, 1_000, 0, 0,
            question="Will it rain?",
            resolution_rules="Resolves Yes if rain is measured.",
            end_time="2026-09-02T00:00:00+00:00",
            captured_at="2026-09-01T00:00:00+00:00",
            source_url="https://polymarket.com/event/will-it-rain",
            yes_token_id="yes-token",
            asks=tuple(BookLevel(0.4 + index / 1000, 10) for index in range(50)),
            fee_rate=0.02,
            fee_source="paper-assumption:flat-2pct-v1",
            book_captured_at="2026-09-01T00:00:00+00:00",
        )
        state = cycle_state()
        state["market_snapshot"] = json.loads(json.dumps(asdict(snapshot)))
        ctx = SimpleNamespace(state=state)

        trader_input = prepare_trader_input(ctx, PaperCycleRequest())
        reviewer_input = prepare_reviewer_input(
            ctx,
            ProposalOutput(snapshot_id="snapshot-1", market_id="market-1", action="trade", probability=0.55, amount=10, citations=[EVIDENCE_ID], rationale="Evidence supports a trade.", max_entry_price=0.41, exit_plan=EXIT_PLAN),
        )

        self.assertEqual(trader_input["market_snapshot"]["question"], "Will it rain?")
        self.assertEqual(reviewer_input.market_snapshot["fee_rate"], 0.02)
        self.assertEqual(len(trader_input["market_snapshot"]["asks"]), 50)
        self.assertEqual(trader_input["market_snapshot"], reviewer_input.market_snapshot)
        self.assertEqual(trader_input["evidence"], [record.model_dump() for record in reviewer_input.evidence])

    def test_runner_executes_paper_cycle_offline_with_structured_models(self) -> None:
        calls = []
        fake_trader = StructuredFakeLlm(
            model=DEFAULT_HARNESS_CONFIG.models.trader,
            agent_name=trader_agent.name,
            calls=calls,
            response={"snapshot_id": "snapshot-1", "market_id": "market-1", "action": "trade", "probability": 0.46, "amount": 10, "citations": [EVIDENCE_ID], "rationale": "Evidence supports a trade.", "max_entry_price": 0.41, "exit_plan": EXIT_PLAN},
        )
        fake_reviewer = StructuredFakeLlm(
            model=DEFAULT_HARNESS_CONFIG.models.reviewer,
            agent_name=reviewer_agent.name,
            calls=calls,
            response={"snapshot_id": "snapshot-1", "market_id": "market-1", "approved": True, "reason": "supported", "citations": [EVIDENCE_ID]},
        )
        test_trader = trader_agent.clone(update={"model": fake_trader})
        test_reviewer = reviewer_agent.clone(update={"model": fake_reviewer})
        workflow = Workflow(
            name=paper_cycle_workflow.name,
            description=paper_cycle_workflow.description,
            input_schema=PaperCycleRequest,
            output_schema=paper_cycle_workflow.output_schema,
            edges=[
                ("START", prepare_trader_input),
                (prepare_trader_input, test_trader),
                (test_trader, route_proposal),
                (route_proposal, {"trade": prepare_reviewer_input}),
                (prepare_reviewer_input, test_reviewer),
                (test_reviewer, complete_paper_cycle),
            ],
        )
        state = {
            "operating_config": asdict(OperatingConfig()),
            "market_snapshot": asdict(rich_snapshot()),
            "model_cost_policy": DEFAULT_HARNESS_CONFIG.cost_policy,
            "cycle_id": "cycle-1",
        }
        authoritative = copy.deepcopy(state)

        async def run_cycle() -> tuple[dict[str, object], list[object]]:
            sessions = InMemorySessionService()
            await sessions.create_session(app_name="test", user_id="user", session_id="session", state=state)
            runner = Runner(app_name="test", node=workflow, session_service=sessions)
            events = []
            async for event in runner.run_async(
                user_id="user",
                session_id="session",
                new_message=types.Content(role="user", parts=[types.Part(text=PaperCycleRequest().model_dump_json())]),
            ):
                events.append(event)
            session = await sessions.get_session(app_name="test", user_id="user", session_id="session")
            self.assertIsNotNone(session)
            return session.state, events

        result, events = asyncio.run(run_cycle())

        self.assertEqual(calls, [trader_agent.name, trader_agent.name, reviewer_agent.name])
        self.assertTrue(any(event.author == trader_agent.name and event.actions.state_delta.get(PROPOSAL_KEY) == fake_trader.response for event in events))
        self.assertTrue(any(event.author == reviewer_agent.name and event.actions.state_delta.get(REVIEW_KEY) == fake_reviewer.response for event in events))
        self.assertEqual(result[PROPOSAL_KEY], fake_trader.response)
        self.assertEqual(result[REVIEW_KEY], fake_reviewer.response)
        self.assertEqual(
            [(record["agent"], record["status"], record["actual_input_tokens"], record["actual_output_tokens"])
             for record in result["model_cost_ledger"]],
            [
                (trader_agent.name, "completed", 11, 7),
                (trader_agent.name, "completed", 11, 7),
                (reviewer_agent.name, "completed", 11, 7),
            ],
        )
        self.assertTrue(result[PAPER_CYCLE_DECISION_KEY]["allowed"])
        self.assertIsNone(result[PAPER_CYCLE_FILL_KEY])
        self.assertEqual(result[PAPER_CYCLE_REPORT_KEY]["status"], "approved")
        for key, value in authoritative.items():
            self.assertEqual(result[key], value)

    def test_reviewer_rejection_records_no_fill_and_explicit_reason(self) -> None:
        state = cycle_state(approved=False)

        report = finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))

        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["reason"], "review_rejected")
        self.assertIsNone(state[PAPER_CYCLE_FILL_KEY])
        self.assertIsNone(state[TRADE_PLAN_READY_KEY])
        self.assertFalse(state[PAPER_CYCLE_DECISION_KEY]["allowed"])

    def test_existing_risk_rejections_record_no_fill(self) -> None:
        cases = (
            ({"probability": 0.44}, {}, "minimum net edge of 0.05 not met"),
            ({}, {"market_exposure": 1, "total_exposure": 5}, "per-market exposure limit exceeded"),
            ({}, {"market_exposure": 0, "total_exposure": 95}, "total exposure limit exceeded"),
        )
        for proposal_changes, snapshot_changes, reason in cases:
            state = cycle_state()
            state[PROPOSAL_KEY] = {**state[PROPOSAL_KEY], **proposal_changes}
            state["market_snapshot"] = {**state["market_snapshot"], **snapshot_changes}
            with self.subTest(reason=reason):
                report = finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))
                self.assertEqual(report, {"status": "rejected", "reason": reason, "summary": state[PAPER_CYCLE_REPORT_KEY]["summary"]})
                self.assertIsNone(state[PAPER_CYCLE_FILL_KEY])
                self.assertIsNone(state[TRADE_PLAN_READY_KEY])

    def test_invalid_or_inconsistent_state_rejects_before_fill(self) -> None:
        invalid_states = []
        for missing in ("operating_config", "market_snapshot", PROPOSAL_KEY, REVIEW_KEY):
            state = cycle_state()
            del state[missing]
            invalid_states.append(state)
        for key, changes in (
            ("market_snapshot", {"price": math.nan}),
            ("market_snapshot", {"price": True}),
            (PROPOSAL_KEY, {"probability": math.inf}),
            (PROPOSAL_KEY, {"probability": True}),
            (PROPOSAL_KEY, {"amount": 0}),
            (PROPOSAL_KEY, {"amount": True}),
            (REVIEW_KEY, {"approved": 1}),
            (REVIEW_KEY, {"reason": "x" * 501}),
            ("operating_config", {"bankroll": "invalid"}),
        ):
            state = cycle_state()
            state[key] = {**state[key], **changes}
            invalid_states.append(state)
        for state in invalid_states:
            with self.subTest(state=state), self.assertRaises(ValueError):
                finalize_paper_cycle(state, ReviewOutput.model_validate(state.get(REVIEW_KEY)))
            self.assertNotIn(PAPER_CYCLE_FILL_KEY, state)

        for key in (PROPOSAL_KEY, REVIEW_KEY):
            state = cycle_state()
            state[key] = {**state[key], "market_id": "other"}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "identity"):
                finalize_paper_cycle(state, ReviewOutput.model_validate(state[REVIEW_KEY]))
            self.assertNotIn(PAPER_CYCLE_FILL_KEY, state)

    def test_structured_wiring_and_tool_boundaries(self) -> None:
        self.assertIs(trader_agent.output_schema, ProposalOutput)
        self.assertEqual(trader_agent.output_key, PROPOSAL_KEY)
        self.assertIs(reviewer_agent.output_schema, ReviewOutput)
        self.assertEqual(reviewer_agent.output_key, REVIEW_KEY)
        self.assertEqual((trader_agent.mode, reviewer_agent.mode), ("single_turn", "single_turn"))
        self.assertEqual((trader_agent.include_contents, reviewer_agent.include_contents), ("none", "none"))
        self.assertNotEqual(trader_agent.name, reviewer_agent.name)
        self.assertNotEqual(trader_agent.output_key, reviewer_agent.output_key)
        node_names = {node.name for node in paper_cycle_workflow.graph.nodes}
        self.assertIn(trader_agent.name, node_names)
        self.assertIn(reviewer_agent.name, node_names)
        self.assertTrue(any(getattr(tool, "name", None) == paper_cycle_workflow.name for tool in root_agent.tools))
        for schema, forbidden in (
            (ProposalOutput, {"approved", "reason", "execute", "url"}),
            (ReviewOutput, {"probability", "amount", "execute", "url"}),
        ):
            self.assertTrue(forbidden.isdisjoint(schema.model_fields))
            with self.assertRaises(ValidationError):
                schema.model_validate({
                    "snapshot_id": "snapshot-1", "market_id": "market-1", "action": "trade", "probability": 0.5, "amount": 1, "max_entry_price": 0.41, "exit_plan": EXIT_PLAN,
                    "approved": True, "reason": "ok", "execute": True, "citations": [EVIDENCE_ID],
                })
        for agent in (trader_agent, reviewer_agent, root_agent):
            tools = " ".join(str(tool).lower() for tool in agent.tools)
            for forbidden in ("paper_execute", "run_decision_cycle", "check_risk", "finalize_paper_cycle"):
                self.assertNotIn(forbidden, tools)
        for agent in (trader_agent, reviewer_agent, root_agent):
            self.assertEqual(agent.before_model_callback.func, before_model_cost)
            callbacks = agent.after_model_callback
            first = callbacks[0] if isinstance(callbacks, list) else callbacks
            self.assertIs(first, after_model_cost)
            self.assertIs(agent.on_model_error_callback, on_model_cost_error)
        from chrysopoeia.agent import context_agent
        self.assertEqual(context_agent.before_model_callback.func, before_model_cost)
        self.assertIs(context_agent.after_model_callback, after_model_cost)
        self.assertIs(context_agent.on_model_error_callback, on_model_cost_error)
        self.assertFalse(hasattr(paper_cycle_workflow, "before_model_callback"))

    def test_review_reason_is_bounded_actionable_output(self) -> None:
        self.assertEqual(ReviewOutput.model_fields["reason"].metadata[1].max_length, 500)
        with self.assertRaises(ValidationError):
            ReviewOutput(
                snapshot_id="snapshot-1", market_id="market-1", approved=False, reason="x" * 501, citations=[],
            )


if __name__ == "__main__":
    unittest.main()
