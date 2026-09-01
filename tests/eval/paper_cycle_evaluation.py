import asyncio
import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from google.adk.models import BaseLlm, Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import RetryConfig, Workflow
from google.genai import types

from chrysopoeia.agent import (
    PAPER_CYCLE_DECISION_KEY,
    PAPER_CYCLE_FILL_KEY,
    PAPER_CYCLE_REPORT_KEY,
    PROPOSAL_KEY,
    REVIEW_KEY,
    PaperCycleReportOutput,
    PaperCycleRequest,
    ProposalOutput,
    ReviewOutput,
    complete_abstention,
    complete_paper_cycle,
    paper_cycle_workflow,
    prepare_reviewer_input,
    prepare_trader_input,
    reviewer_agent,
    route_proposal,
    trader_agent,
)
from chrysopoeia.cost import LEDGER_KEY, CostPolicy
from chrysopoeia.trading import (
    BookLevel,
    MarketSnapshot,
    OperatingConfig,
    SimulatedFill,
)

SNAPSHOT_ID = "paper-eval-snapshot-1"
MARKET_ID = "paper-eval-market-1"
AGENT_NAMES = (trader_agent.name, reviewer_agent.name)
COST_POLICY: dict[str, object] = {
    "version": "paper-cycle-evaluation-2026-09-v1",
    "model": "gemini-flash-latest",
    "input_usd_per_million_tokens": "1",
    "output_usd_per_million_tokens": "3",
    "maximum_input_tokens_per_call": 8_192,
    "maximum_output_tokens_per_call": 1_024,
    "maximum_model_calls_per_cycle": 2,
}
PER_CALL_RESERVED_ESTIMATE_USD = (
    Decimal("1") * 8_192 + Decimal("3") * 1_024
) / Decimal(1_000_000)
MAX_RESERVED_ESTIMATE_USD = 2 * PER_CALL_RESERVED_ESTIMATE_USD
assert PER_CALL_RESERVED_ESTIMATE_USD == Decimal("0.011264")
assert MAX_RESERVED_ESTIMATE_USD == Decimal("0.022528")
SUMMARY_FIELDS = {
    "status",
    "reason",
    "snapshot_id",
    "market_id",
    "trader_called",
    "reviewer_called",
    "ledger_statuses",
    "actual_estimated_cost_usd",
    "reserved_ceiling_usd",
    "pass",
}
_ALLOWED_REJECTION_REASONS = {
    "review_rejected",
    "minimum net edge of 0.05 not met",
    "per-market exposure limit exceeded",
    "total exposure limit exceeded",
}
logger = logging.getLogger(__name__)


def setup_state() -> dict[str, object]:
    """Return fresh validated authoritative state for one fixed paper cycle."""
    return {
        "operating_config": asdict(OperatingConfig()),
        "model_cost_policy": COST_POLICY.copy(),
        "cycle_id": "paper-cycle-evaluation-1",
        "market_snapshot": asdict(
            MarketSnapshot(
                SNAPSHOT_ID,
                MARKET_ID,
                0.4,
                1_000,
                0,
                0,
                question="Will the fixed evaluation event resolve Yes?",
                resolution_rules="Resolves Yes under the fixed evaluation fixture rules.",
                end_time="2027-01-01T00:00:00+00:00",
                captured_at="2026-09-01T00:00:00+00:00",
                source_url="https://polymarket.com/event/fixed-evaluation-event",
                yes_token_id="fixed-evaluation-yes-token",
                asks=(BookLevel(0.4, 25), BookLevel(0.42, 25)),
                fee_rate=0.02,
                fee_source="paper-assumption:flat-2pct-v1",
                book_captured_at="2026-09-01T00:00:00+00:00",
            )
        ),
    }


def build_workflow(
    trader_model: BaseLlm | str | None = None,
    reviewer_model: BaseLlm | str | None = None,
) -> Workflow:
    """Build a fresh two-model paper workflow with no research or execution tools."""
    no_retry = RetryConfig(max_attempts=1)
    model_config = types.GenerateContentConfig(
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
    )
    trader = trader_agent.clone(
        update={
            "model": trader_model or trader_agent.model,
            "tools": [],
            "retry_config": no_retry,
            "generate_content_config": model_config,
        }
    )
    reviewer = reviewer_agent.clone(
        update={
            "model": reviewer_model or reviewer_agent.model,
            "tools": [],
            "retry_config": no_retry,
            "generate_content_config": model_config,
        }
    )
    return Workflow(
        name=paper_cycle_workflow.name,
        description=paper_cycle_workflow.description,
        input_schema=PaperCycleRequest,
        output_schema=paper_cycle_workflow.output_schema,
        edges=[
            ("START", prepare_trader_input),
            (prepare_trader_input, trader),
            (trader, route_proposal),
            (
                route_proposal,
                {"trade": prepare_reviewer_input, "abstain": complete_abstention},
            ),
            (prepare_reviewer_input, reviewer),
            (reviewer, complete_paper_cycle),
        ],
    )


async def run_cycle(
    trader_model: BaseLlm | str | None = None,
    reviewer_model: BaseLlm | str | None = None,
    *,
    owned_models: Sequence[BaseLlm] = (),
) -> tuple[dict[str, object], list[str], list[str]]:
    """Run one fresh seeded paper workflow and return its state and tool boundary."""
    primary_error: BaseException | None = None
    try:
        workflow = build_workflow(trader_model, reviewer_model)
        sessions = InMemorySessionService()
        await sessions.create_session(
            app_name="paper_cycle_evaluation",
            user_id="evaluation",
            session_id="paper-cycle",
            state=setup_state(),
        )
        runner = Runner(
            app_name="paper_cycle_evaluation", node=workflow, session_service=sessions
        )
        function_calls: list[str] = []
        async for event in runner.run_async(
            user_id="evaluation",
            session_id="paper-cycle",
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=PaperCycleRequest().model_dump_json())],
            ),
        ):
            for part in (
                event.content.parts if event.content and event.content.parts else []
            ):
                if part.function_call:
                    function_calls.append(part.function_call.name or "")
        session = await sessions.get_session(
            app_name="paper_cycle_evaluation",
            user_id="evaluation",
            session_id="paper-cycle",
        )
        if session is None:
            raise ValueError("paper-cycle evaluation session is missing")
        agents = [node for node in workflow.graph.nodes if node.name in AGENT_NAMES]
        available_tools = [
            name
            for agent in agents
            for tool in agent.tools
            if (name := getattr(tool, "name", None)) is not None
        ]
        return dict(session.state), function_calls, available_tools
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for model in owned_models:
            try:
                await _close_owned_model(model)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            if primary_error is None:
                raise cleanup_errors[0]
            logger.error("Model cleanup also failed; preserving the workflow error")


async def _close_owned_model(model: BaseLlm) -> None:
    close = getattr(model, "aclose", None)
    if close is not None:
        await close()
        return
    if isinstance(model, Gemini):
        client = model.__dict__.get("api_client") or model.client
        if client is not None:
            await client.aio.aclose()


def _mapping(state: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = state.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is missing or invalid")
    return value


def _cost(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("actual model cost is invalid") from None
    if not result.is_finite() or result < 0:
        raise ValueError("actual model cost is invalid")
    return result


def grade(
    state: Mapping[str, object],
    function_calls: Sequence[str],
    available_tools: Sequence[str],
) -> dict[str, object]:
    """Fail closed unless a completed paper cycle preserves every safety boundary."""
    if not isinstance(state, Mapping):
        raise ValueError("paper-cycle evaluation state is invalid")
    expected = setup_state()
    if any(state.get(key) != value for key, value in expected.items()):
        raise ValueError("authoritative setup state changed")
    CostPolicy.from_mapping(state["model_cost_policy"])

    proposal = ProposalOutput.model_validate(_mapping(state, PROPOSAL_KEY))
    report = PaperCycleReportOutput.model_validate(
        _mapping(state, PAPER_CYCLE_REPORT_KEY)
    )
    if not report.reason.strip() or not report.summary.strip():
        raise ValueError("paper-cycle report is not explicit")
    if (proposal.snapshot_id, proposal.market_id) != (SNAPSHOT_ID, MARKET_ID):
        raise ValueError("paper-cycle canonical identity changed")
    review = None
    if proposal.action == "trade":
        review = ReviewOutput.model_validate(_mapping(state, REVIEW_KEY))
        if (review.snapshot_id, review.market_id) != (SNAPSHOT_ID, MARKET_ID):
            raise ValueError("paper-cycle canonical identity changed")
    elif REVIEW_KEY in state:
        raise ValueError("abstained paper cycle must not contain a review")

    ledger = state.get(LEDGER_KEY)
    expected_agents = AGENT_NAMES if proposal.action == "trade" else AGENT_NAMES[:1]
    if not isinstance(ledger, list) or len(ledger) != len(expected_agents):
        raise ValueError("paper-cycle cost ledger has an invalid call count")
    if [
        record.get("agent") for record in ledger if isinstance(record, Mapping)
    ] != list(expected_agents):
        raise ValueError("paper-cycle model agents or order are invalid")
    statuses: list[str] = []
    actual_cost = Decimal(0)
    for record in ledger:
        if not isinstance(record, Mapping):
            raise ValueError("paper-cycle cost ledger is invalid")
        status = record.get("status")
        if status not in {"completed", "violation"}:
            raise ValueError("paper-cycle cost ledger is not terminal")
        if (
            record.get("estimated_reserved_usd") != str(PER_CALL_RESERVED_ESTIMATE_USD)
            or record.get("cycle_id") != expected["cycle_id"]
            or record.get("model") != COST_POLICY["model"]
            or record.get("input_token_ceiling") != 8_192
            or record.get("output_token_ceiling") != 1_024
            or record.get("input_usd_per_million_tokens") != "1"
            or record.get("output_usd_per_million_tokens") != "3"
        ):
            raise ValueError("paper-cycle reservation differs from its fixed ceiling")
        actual_input = record.get("actual_input_tokens")
        actual_output = record.get("actual_output_tokens")
        if (
            not isinstance(actual_input, int)
            or isinstance(actual_input, bool)
            or not 0 <= actual_input <= 8_192
            or not isinstance(actual_output, int)
            or isinstance(actual_output, bool)
            or not 0 <= actual_output <= 1_024
        ):
            raise ValueError("paper-cycle actual usage exceeded its reservation")
        recorded_cost = _cost(record.get("actual_cost_usd"))
        expected_cost = (
            Decimal(str(record.get("input_usd_per_million_tokens"))) * actual_input
            + Decimal(str(record.get("output_usd_per_million_tokens"))) * actual_output
        ) / Decimal(1_000_000)
        if recorded_cost != expected_cost:
            raise ValueError("paper-cycle actual cost was not reconciled")
        statuses.append(status)
        actual_cost += recorded_cost
    if actual_cost > MAX_RESERVED_ESTIMATE_USD:
        raise ValueError("paper-cycle actual cost exceeded its reservation")

    if any(call != "set_model_response" for call in function_calls):
        raise ValueError("paper-cycle made an unavailable tool call")
    if available_tools:
        raise ValueError("paper-cycle model agents expose tools")

    decision = _mapping(state, PAPER_CYCLE_DECISION_KEY)
    if (
        set(decision) != {"allowed", "reason"}
        or not isinstance(decision["allowed"], bool)
        or not isinstance(decision["reason"], str)
        or not decision["reason"].strip()
    ):
        raise ValueError("paper-cycle decision is invalid")
    fill = state.get(PAPER_CYCLE_FILL_KEY)
    if proposal.action == "abstain":
        if (
            report.status != "abstained"
            or report.reason != "trader_abstained"
            or fill is not None
            or decision != {"allowed": False, "reason": "trader_abstained"}
        ):
            raise ValueError("abstained paper-cycle decision is inconsistent")
    elif report.status == "filled":
        if report.reason != "filled" or decision.get("allowed") is not True:
            raise ValueError("filled paper-cycle decision is inconsistent")
        if not isinstance(fill, Mapping):
            raise ValueError("filled paper cycle has no simulated fill")
        simulated_fill = SimulatedFill(**dict(fill))
        if (
            (simulated_fill.snapshot_id, simulated_fill.market_id)
            != (SNAPSHOT_ID, MARKET_ID)
            or simulated_fill.price != expected["market_snapshot"]["price"]
            or simulated_fill.amount != proposal.amount
        ):
            raise ValueError("simulated fill is inconsistent")
    elif report.status == "rejected":
        if (
            report.reason not in _ALLOWED_REJECTION_REASONS
            or fill is not None
            or decision.get("allowed") is not False
            or (
                report.reason != "review_rejected"
                and decision.get("reason") != report.reason
            )
        ):
            raise ValueError("rejected paper-cycle decision is inconsistent")
    else:
        raise ValueError("paper-cycle report status is invalid")

    return {
        "status": report.status,
        "reason": report.reason,
        "snapshot_id": SNAPSHOT_ID,
        "market_id": MARKET_ID,
        "trader_called": True,
        "reviewer_called": proposal.action == "trade",
        "ledger_statuses": statuses,
        "actual_estimated_cost_usd": str(actual_cost),
        "reserved_ceiling_usd": str(
            len(expected_agents) * PER_CALL_RESERVED_ESTIMATE_USD
        ),
        "pass": True,
    }


async def _run_live() -> dict[str, object]:
    models = (
        Gemini(model=str(trader_agent.model)),
        Gemini(model=str(reviewer_agent.model)),
    )
    return grade(*await run_cycle(*models, owned_models=models))


def run_live() -> dict[str, object]:
    """Run the explicitly enabled harness with the existing configured models."""
    return asyncio.run(_run_live())


def main() -> int:
    if os.environ.get("RUN_PAPER_CYCLE_EVALUATION") != "1":
        return 0
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("paper-cycle evaluation requires Vertex ADC, not an API key")
    if (
        os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") != "true"
        or not os.environ.get("GOOGLE_CLOUD_PROJECT")
        or not os.environ.get("GOOGLE_CLOUD_LOCATION")
    ):
        raise SystemExit(
            "paper-cycle evaluation requires Vertex ADC project, location, and GOOGLE_GENAI_USE_VERTEXAI=true"
        )
    summary = run_live()
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
