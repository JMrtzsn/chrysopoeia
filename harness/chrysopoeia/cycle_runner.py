import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal, InvalidOperation

from google.adk.models import BaseLlm, Gemini, LLMRegistry
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.adk.workflow import RetryConfig, Workflow
from google.genai import types

from chrysopoeia.agent import (
    build_agents,
    complete_abstention,
    complete_paper_cycle,
    prepare_reviewer_input,
    prepare_trader_input,
    route_proposal,
)
from chrysopoeia.configuration import HarnessConfig, ModelPrice
from chrysopoeia.cost import LEDGER_KEY
from chrysopoeia.paper_cycle import (
    PAPER_CYCLE_FILL_KEY,
    PAPER_CYCLE_REPORT_KEY,
    PROPOSAL_KEY,
    TRADE_PLAN_READY_KEY,
    VALIDATED_EXTERNAL_EVIDENCE_KEY,
    EvidenceRecord,
    PaperCycleReportOutput,
    PaperCycleRequest,
    ProposalOutput,
    validate_evidence_bundle,
)
from chrysopoeia.trading import MarketSnapshot, OperatingConfig

logger = logging.getLogger(__name__)


def reserved_ceiling(config: HarnessConfig, model_calls: int = 2) -> Decimal:
    prices = config.cost.prices or (
        ModelPrice(
            config.cost.model,
            config.cost.input_usd_per_million_tokens,
            config.cost.output_usd_per_million_tokens,
        ),
    )
    return (
        model_calls
        * (
            max(price.input_usd_per_million_tokens for price in prices)
            * config.cost.maximum_input_tokens_per_call
            + max(price.output_usd_per_million_tokens for price in prices)
            * config.cost.maximum_output_tokens_per_call
        )
        / Decimal(1_000_000)
    )


def resolve_model(adapter: str, model_name: str) -> BaseLlm:
    """Resolve one configured model through the selected ADK model boundary."""
    if adapter == "adk-gemini":
        return Gemini(model=model_name)
    return LLMRegistry.new_llm(model=model_name)


def build_cycle_workflow(
    config: HarnessConfig,
    trader_model: BaseLlm | str,
    reviewer_model: BaseLlm | str,
) -> tuple[Workflow, tuple[str, str]]:
    agents = build_agents(config)
    no_retry = RetryConfig(max_attempts=1)
    model_config = types.GenerateContentConfig(
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)
        ),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    trader = agents.trader_agent.clone(
        update={
            "model": trader_model,
            "tools": [],
            "retry_config": no_retry,
            "generate_content_config": model_config,
        }
    )
    reviewer = agents.reviewer_agent.clone(
        update={
            "model": reviewer_model,
            "tools": [],
            "retry_config": no_retry,
            "generate_content_config": model_config,
        }
    )
    workflow = Workflow(
        name=agents.paper_cycle_workflow.name,
        description=agents.paper_cycle_workflow.description,
        input_schema=PaperCycleRequest,
        output_schema=agents.paper_cycle_workflow.output_schema,
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
    return workflow, (trader.name, reviewer.name)


async def _close_owned_model(model: BaseLlm) -> None:
    close = getattr(model, "aclose", None)
    if close is not None:
        await close()
    elif isinstance(model, Gemini):
        client = model.__dict__.get("api_client") or model.client
        if client is not None:
            await client.aio.aclose()


def _cost(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid model cost ledger") from None
    if not result.is_finite() or result < 0:
        raise ValueError("invalid model cost ledger")
    return result


def summarize_cycle(
    config: HarnessConfig,
    snapshot: MarketSnapshot,
    state: Mapping[str, object],
) -> dict[str, object]:
    report = PaperCycleReportOutput.model_validate(state.get(PAPER_CYCLE_REPORT_KEY))
    proposal = ProposalOutput.model_validate(state.get(PROPOSAL_KEY))
    ledger = state.get(LEDGER_KEY)
    if not isinstance(ledger, list) or len(ledger) not in {1, 2}:
        raise ValueError("invalid model cost ledger")
    statuses: list[str] = []
    actual = Decimal(0)
    for record in ledger:
        if not isinstance(record, Mapping) or record.get("status") not in {
            "completed",
            "violation",
        }:
            raise ValueError("invalid model cost ledger")
        statuses.append(str(record["status"]))
        actual += _cost(record.get("actual_cost_usd"))
    maximum = reserved_ceiling(config)
    if actual > maximum:
        raise ValueError("model cost exceeded reserved ceiling")
    fill = state.get(PAPER_CYCLE_FILL_KEY)
    event = state.get(TRADE_PLAN_READY_KEY)
    public_fill = None
    if fill is not None:
        if not isinstance(fill, Mapping):
            raise ValueError("invalid paper fill")
        public_fill = {
            key: fill[key]
            for key in (
                "price",
                "amount",
                "shares",
                "fee",
                "total_cost",
                "levels_consumed",
                "exit_plan",
            )
        }
    return {
        "schema_version": 1,
        "record_type": "paper_cycle_result",
        "snapshot_id": snapshot.snapshot_id,
        "market_id": snapshot.market_id,
        "status": report.status,
        "reason": report.reason,
        "trader_called": True,
        "reviewer_called": proposal.action == "trade",
        "fill": public_fill,
        "event": event,
        "ledger_statuses": statuses,
        "actual_estimated_cost_usd": str(actual),
        "maximum_reserved_cost_usd": str(maximum),
    }


async def run_paper_cycle_state(
    config: HarnessConfig,
    snapshot: MarketSnapshot,
    operating: OperatingConfig,
    trader_model: BaseLlm | str | None = None,
    reviewer_model: BaseLlm | str | None = None,
    *,
    session_service: BaseSessionService | None = None,
    owned_models: Sequence[BaseLlm] = (),
    evidence: Sequence[EvidenceRecord] | None = None,
) -> tuple[dict[str, object], list[str], list[str]]:
    """Run one bounded ADK paper cycle and return runtime evaluation evidence."""
    external: list[EvidenceRecord] = []
    if evidence is not None:
        validated = validate_evidence_bundle(snapshot, list(evidence))
        if len(validated) < 2:
            raise ValueError("external evidence bundle is missing")
        external = validated[1:]
    created: tuple[BaseLlm, ...] = ()
    if trader_model is None and reviewer_model is None:
        created = (
            resolve_model(config.models.adapter, config.models.trader),
            resolve_model(config.models.adapter, config.models.reviewer),
        )
        trader_model, reviewer_model = created
    elif trader_model is None or reviewer_model is None:
        raise ValueError("both cycle models are required")
    primary_error: BaseException | None = None
    try:
        workflow, _ = build_cycle_workflow(config, trader_model, reviewer_model)
        sessions = session_service or InMemorySessionService()
        app_name = "chrysopoeia_cycle"
        user_id = "operator"
        session_id = "paper-cycle"
        await sessions.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state={
                "operating_config": asdict(operating),
                "model_cost_policy": config.cost_policy,
                "cycle_id": f"paper-cycle:{snapshot.snapshot_id}",
                "market_snapshot": asdict(snapshot),
                **(
                    {
                        VALIDATED_EXTERNAL_EVIDENCE_KEY: [
                            record.model_dump() for record in external
                        ]
                    }
                    if external
                    else {}
                ),
            },
        )
        runner = Runner(app_name=app_name, node=workflow, session_service=sessions)
        function_calls: list[str] = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
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
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise ValueError("paper cycle session is missing")
        available_tools = [
            name
            for node in workflow.graph.nodes
            if node.name in {"paper_market_trader", "independent_trade_reviewer"}
            for tool in node.tools
            if (name := getattr(tool, "name", None)) is not None
        ]
        return dict(session.state), function_calls, available_tools
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_errors: list[BaseException] = []
        for model in (*created, *owned_models):
            try:
                await _close_owned_model(model)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            if primary_error is None:
                raise cleanup_errors[0]
            logger.error("Model cleanup also failed; preserving the workflow error")


async def run_paper_cycle(
    config: HarnessConfig,
    snapshot: MarketSnapshot,
    operating: OperatingConfig,
    trader_model: BaseLlm | str | None = None,
    reviewer_model: BaseLlm | str | None = None,
    *,
    session_service: BaseSessionService | None = None,
    owned_models: Sequence[BaseLlm] = (),
    evidence: Sequence[EvidenceRecord] | None = None,
) -> dict[str, object]:
    """Run one bounded ADK paper cycle over an already captured snapshot."""
    state, _, _ = await run_paper_cycle_state(
        config,
        snapshot,
        operating,
        trader_model,
        reviewer_model,
        session_service=session_service,
        owned_models=owned_models,
        evidence=evidence,
    )
    return summarize_cycle(config, snapshot, state)
