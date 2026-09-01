import asyncio
import copy
import io
import json
import os
import unittest
from collections.abc import AsyncGenerator
from contextlib import redirect_stdout
from unittest.mock import patch

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import SkipValidation

from chrysopoeia.agent import reviewer_agent, trader_agent
from tests.eval import paper_cycle_evaluation as evaluation


class FakeLlm(BaseLlm):
    calls: SkipValidation[list[str]]
    agent_name: str
    response: dict[str, object]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if stream:
            raise AssertionError("streaming is not allowed")
        self.calls.append(self.agent_name)
        if llm_request.tools_dict:
            parts = [
                types.Part(
                    function_call=types.FunctionCall(
                        id="structured-response",
                        name="set_model_response",
                        args=self.response,
                    )
                )
            ]
        else:
            parts = [types.Part(text=json.dumps(self.response))]
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=11, candidates_token_count=7
            ),
        )


class CloseAwareFakeLlm(FakeLlm):
    closed: bool = False
    failure: SkipValidation[BaseException | None] = None
    close_failure: SkipValidation[Exception | None] = None

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if self.failure:
            raise self.failure
        async for response in super().generate_content_async(llm_request, stream):
            yield response

    async def aclose(self) -> None:
        self.closed = True
        if self.close_failure:
            raise self.close_failure


class PaperCycleEvaluationTests(unittest.TestCase):
    def models(self, approved: bool) -> tuple[FakeLlm, FakeLlm, list[str]]:
        calls: list[str] = []
        return (
            FakeLlm(
                model="gemini-flash-latest",
                agent_name=trader_agent.name,
                calls=calls,
                response={
                    "snapshot_id": evaluation.SNAPSHOT_ID,
                    "market_id": evaluation.MARKET_ID,
                    "action": "trade",
                    "probability": 0.46,
                    "amount": 9,
                    "citations": [evaluation.EVIDENCE_ID],
                },
            ),
            FakeLlm(
                model="gemini-flash-latest",
                agent_name=reviewer_agent.name,
                calls=calls,
                response={
                    "snapshot_id": evaluation.SNAPSHOT_ID,
                    "market_id": evaluation.MARKET_ID,
                    "approved": approved,
                    "reason": "supported" if approved else "weak evidence",
                    "citations": [evaluation.EVIDENCE_ID] if approved else [],
                },
            ),
            calls,
        )

    def test_real_runner_passes_fill_and_rejection_with_exact_cost_settlement(
        self,
    ) -> None:
        for approved, expected_status in ((True, "filled"), (False, "rejected")):
            trader, reviewer, calls = self.models(approved)
            initial = evaluation.setup_state()

            state, function_calls, available_tools = asyncio.run(
                evaluation.run_cycle(trader, reviewer)
            )
            summary = evaluation.grade(state, function_calls, available_tools)

            with self.subTest(status=expected_status):
                self.assertEqual(calls, [trader_agent.name, reviewer_agent.name])
                self.assertEqual(summary["status"], expected_status)
                self.assertTrue(summary["pass"])
                self.assertEqual(summary["reserved_ceiling_usd"], "0.022528")
                self.assertEqual(summary["ledger_statuses"], ["completed", "completed"])
                self.assertLessEqual(
                    evaluation.Decimal(summary["actual_estimated_cost_usd"]),
                    evaluation.MAX_RESERVED_ESTIMATE_USD,
                )
                for key, value in initial.items():
                    self.assertEqual(state[key], value)
                self.assertEqual(set(summary), evaluation.SUMMARY_FIELDS)
                self.assertEqual(function_calls, [])
                self.assertEqual(available_tools, [])

    def test_real_runner_terminates_trader_abstention_before_reviewer(self) -> None:
        trader, reviewer, calls = self.models(True)
        trader.response = {
            "snapshot_id": evaluation.SNAPSHOT_ID,
            "market_id": evaluation.MARKET_ID,
            "action": "abstain",
            "probability": 0.4,
            "amount": 0,
            "citations": [],
        }

        state, function_calls, available_tools = asyncio.run(
            evaluation.run_cycle(trader, reviewer)
        )
        summary = evaluation.grade(state, function_calls, available_tools)

        self.assertEqual(calls, [trader_agent.name])
        self.assertEqual(summary["status"], "abstained")
        self.assertEqual(summary["reason"], "trader_abstained")
        self.assertFalse(summary["reviewer_called"])
        self.assertEqual(summary["ledger_statuses"], ["completed"])
        self.assertEqual(summary["reserved_ceiling_usd"], "0.011264")
        self.assertIsNone(state["paper_cycle_fill"])
        self.assertEqual(
            state["paper_cycle_decision"],
            {"allowed": False, "reason": "trader_abstained"},
        )
        self.assertEqual(state["paper_cycle_report"]["reason"], "trader_abstained")
        self.assertNotIn("paper_cycle_review", state)

    def test_owned_models_close_after_abstain_and_trader_failure(self) -> None:
        trader, reviewer, calls = self.models(True)
        owned_trader = CloseAwareFakeLlm(
            model=trader.model,
            agent_name=trader.agent_name,
            calls=calls,
            response=trader.response,
        )
        owned_reviewer = CloseAwareFakeLlm(
            model=reviewer.model,
            agent_name=reviewer.agent_name,
            calls=calls,
            response=reviewer.response,
        )
        owned_trader.response = {
            "snapshot_id": evaluation.SNAPSHOT_ID,
            "market_id": evaluation.MARKET_ID,
            "action": "abstain",
            "probability": 0.4,
            "amount": 0,
            "citations": [],
        }

        asyncio.run(
            evaluation.run_cycle(
                owned_trader,
                owned_reviewer,
                owned_models=(owned_trader, owned_reviewer),
            )
        )

        self.assertEqual(calls, [trader_agent.name])
        self.assertTrue(owned_trader.closed)
        self.assertTrue(owned_reviewer.closed)

        cleanup = RuntimeError("cleanup failure")
        trader, reviewer, _ = self.models(True)
        owned_trader = CloseAwareFakeLlm(
            model=trader.model,
            agent_name=trader.agent_name,
            calls=trader.calls,
            response={
                "snapshot_id": evaluation.SNAPSHOT_ID,
                "market_id": evaluation.MARKET_ID,
                "action": "abstain",
                "probability": 0.4,
                "amount": 0,
                "citations": [],
            },
            close_failure=cleanup,
        )
        with self.assertRaises(RuntimeError) as raised:
            asyncio.run(
                evaluation.run_cycle(
                    owned_trader, reviewer, owned_models=(owned_trader,)
                )
            )
        self.assertIs(raised.exception, cleanup)

        trader, reviewer, _ = self.models(True)
        primary = RuntimeError("primary model failure")
        owned_trader = CloseAwareFakeLlm(
            model=trader.model,
            agent_name=trader.agent_name,
            calls=trader.calls,
            response=trader.response,
            failure=primary,
        )
        owned_reviewer = CloseAwareFakeLlm(
            model=reviewer.model,
            agent_name=reviewer.agent_name,
            calls=reviewer.calls,
            response=reviewer.response,
        )
        owned_reviewer.close_failure = cleanup
        with (
            self.assertLogs(evaluation.logger, "ERROR"),
            self.assertRaises(RuntimeError) as raised,
        ):
            asyncio.run(
                evaluation.run_cycle(
                    owned_trader,
                    owned_reviewer,
                    owned_models=(owned_trader, owned_reviewer),
                )
            )
        self.assertIs(raised.exception, primary)
        self.assertTrue(owned_trader.closed)
        self.assertTrue(owned_reviewer.closed)

        shared_trader, shared_reviewer, _ = self.models(True)
        asyncio.run(evaluation.run_cycle(shared_trader, shared_reviewer))
        self.assertFalse(hasattr(shared_trader, "closed"))

    def test_grader_rejects_malformed_or_boundary_violating_state(self) -> None:
        trader, reviewer, _ = self.models(True)
        state, function_calls, available_tools = asyncio.run(
            evaluation.run_cycle(trader, reviewer)
        )
        cases = []
        malformed = copy.deepcopy(state)
        malformed["paper_cycle_proposal"]["market_id"] = "other"
        cases.append(malformed)
        malformed = copy.deepcopy(state)
        malformed["model_cost_ledger"][0]["status"] = "reserved"
        cases.append(malformed)
        malformed = copy.deepcopy(state)
        malformed["operating_config"]["bankroll"] = 2_000
        cases.append(malformed)
        malformed = copy.deepcopy(state)
        malformed["model_cost_ledger"][0]["actual_cost_usd"] = "0"
        cases.append(malformed)
        malformed = copy.deepcopy(state)
        malformed[evaluation.EVIDENCE_KEY][0]["url"] = "https://example.com/forged"
        cases.append(malformed)
        malformed = copy.deepcopy(state)
        malformed["paper_cycle_proposal"]["citations"] = ["https://example.com/forged"]
        cases.append(malformed)
        for malformed in cases:
            with self.subTest(), self.assertRaises(ValueError):
                evaluation.grade(malformed, function_calls, available_tools)
        self.assertNotIn("url", state["paper_cycle_proposal"])
        self.assertNotIn("url", state["paper_cycle_review"])
        with self.assertRaises(ValueError):
            evaluation.grade(state, ["execute_order"], available_tools)
        with self.assertRaises(ValueError):
            evaluation.grade(state, function_calls, ["place_order"])

    def test_workflow_has_only_two_tool_less_single_attempt_model_agents(self) -> None:
        trader, reviewer, _ = self.models(True)
        workflow = evaluation.build_workflow(trader, reviewer)
        agents = [
            node for node in workflow.graph.nodes if node.name in evaluation.AGENT_NAMES
        ]

        self.assertEqual([agent.name for agent in agents], list(evaluation.AGENT_NAMES))
        for agent in agents:
            self.assertEqual(agent.retry_config.max_attempts, 1)
            self.assertEqual(
                agent.generate_content_config.http_options.retry_options.attempts, 1
            )
            self.assertEqual(agent.tools, [])

    def test_main_gates_before_live_setup_and_emits_only_sanitized_json(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(evaluation, "run_live") as run_live,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(evaluation.main(), 0)
            run_live.assert_not_called()
            self.assertEqual(output.getvalue(), "")

        with (
            patch.dict(os.environ, {"RUN_PAPER_CYCLE_EVALUATION": "1"}, clear=True),
            patch.object(evaluation, "run_live") as run_live,
            self.assertRaises(SystemExit),
        ):
            evaluation.main()
        run_live.assert_not_called()

        live_summary = dict.fromkeys(evaluation.SUMMARY_FIELDS)
        live_summary["pass"] = False
        env = {
            "RUN_PAPER_CYCLE_EVALUATION": "1",
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "GOOGLE_CLOUD_PROJECT": "project",
            "GOOGLE_CLOUD_LOCATION": "us-east1",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(evaluation, "run_live", return_value=live_summary) as run_live,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(evaluation.main(), 1)
            run_live.assert_called_once_with()
            self.assertEqual(
                set(json.loads(output.getvalue())), evaluation.SUMMARY_FIELDS
            )

        for extra in ({"GOOGLE_API_KEY": "secret"}, {"GEMINI_API_KEY": "secret"}):
            with (
                patch.dict(os.environ, env | extra, clear=True),
                patch.object(evaluation, "run_live") as run_live,
                self.assertRaises(SystemExit),
            ):
                evaluation.main()
            run_live.assert_not_called()


if __name__ == "__main__":
    unittest.main()
