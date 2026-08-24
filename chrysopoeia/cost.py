from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from google.adk.agents.context import Context
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions.state import State

from chrysopoeia.trading import OperatingConfig


LEDGER_KEY = "model_cost_ledger"
MAX_TOKENS = 100_000_000
MILLION = Decimal(1_000_000)
DEFAULT_COST_POLICY: dict[str, object] = {
    "version": "project-estimate-2026-08-v1",
    "model": "gemini-flash-latest",
    "input_usd_per_million_tokens": "1",
    "output_usd_per_million_tokens": "3",
    "maximum_input_tokens_per_call": 8_192,
    "maximum_output_tokens_per_call": 1_024,
    "maximum_model_calls_per_cycle": 12,
}
BOOTSTRAP_COST_POLICY: dict[str, object] = {
    **DEFAULT_COST_POLICY,
    "version": "onboarding-bootstrap-2026-08-v1",
    "maximum_input_tokens_per_call": 2_048,
    "maximum_output_tokens_per_call": 512,
    "maximum_model_calls_per_cycle": 1,
}
BOOTSTRAP_DAILY_BUDGET = Decimal("0.01")
StateMap = MutableMapping[str, object] | State


def _state(value: object) -> StateMap:
    if not isinstance(value, (MutableMapping, State)):
        raise ValueError("session state is invalid")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{name} must be a non-empty string of at most 200 characters")
    return value


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{name} must be a finite non-negative number") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def _tokens(value: object, name: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= MAX_TOKENS:
        raise ValueError(f"{name} must be a {'positive' if positive else 'non-negative'} integer")
    return value


@dataclass(frozen=True)
class CostPolicy:
    version: str
    model: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal
    maximum_input_tokens_per_call: int
    maximum_output_tokens_per_call: int
    maximum_model_calls_per_cycle: int

    @classmethod
    def from_mapping(cls, value: object) -> "CostPolicy":
        keys = {
            "version", "model", "input_usd_per_million_tokens", "output_usd_per_million_tokens",
            "maximum_input_tokens_per_call", "maximum_output_tokens_per_call", "maximum_model_calls_per_cycle",
        }
        if not isinstance(value, Mapping) or set(value) != keys:
            raise ValueError("model cost policy is missing or invalid")
        return cls(
            _identifier(value["version"], "policy version"),
            _identifier(value["model"], "policy model"),
            _decimal(value["input_usd_per_million_tokens"], "input price"),
            _decimal(value["output_usd_per_million_tokens"], "output price"),
            _tokens(value["maximum_input_tokens_per_call"], "input token ceiling", positive=True),
            _tokens(value["maximum_output_tokens_per_call"], "output token ceiling", positive=True),
            _tokens(value["maximum_model_calls_per_cycle"], "cycle model-call ceiling", positive=True),
        )

def _records(state: StateMap) -> list[dict[str, object]]:
    records = state.get(LEDGER_KEY, [])
    required = {
        "date", "cycle_id", "agent", "model", "call_id", "invocation_id", "estimated_reserved_usd",
        "input_token_ceiling", "output_token_ceiling", "input_usd_per_million_tokens",
        "output_usd_per_million_tokens", "status",
    }
    if not isinstance(records, list) or any(not isinstance(record, dict) or not required <= set(record) for record in records):
        raise ValueError("model cost ledger is invalid")
    call_ids: set[str] = set()
    for record in records:
        for key in ("date", "cycle_id", "agent", "model", "call_id", "invocation_id"):
            _identifier(record[key], key.replace("_", " "))
        if record["call_id"] in call_ids or not isinstance(record["status"], str) or record["status"] not in {"reserved", "completed", "released", "violation"}:
            raise ValueError("model cost ledger is invalid")
        call_ids.add(str(record["call_id"]))
        _decimal(record["estimated_reserved_usd"], "reserved cost")
        _decimal(record["input_usd_per_million_tokens"], "reserved input price")
        _decimal(record["output_usd_per_million_tokens"], "reserved output price")
        _tokens(record["input_token_ceiling"], "input token ceiling")
        _tokens(record["output_token_ceiling"], "output token ceiling")
        if record["status"] in {"completed", "violation"}:
            _tokens(record.get("actual_input_tokens"), "actual input tokens")
            _tokens(record.get("actual_output_tokens"), "actual output tokens")
            _decimal(record.get("actual_cost_usd"), "actual cost")
    return records


def _budget(state: StateMap, policy: CostPolicy) -> Decimal:
    value = state.get("operating_config")
    if value is None and policy.version == BOOTSTRAP_COST_POLICY["version"]:
        return BOOTSTRAP_DAILY_BUDGET
    if not isinstance(value, Mapping):
        raise ValueError("operating configuration is missing or invalid")
    try:
        return Decimal(str(OperatingConfig(**dict(value)).daily_cloud_cost_budget))
    except (TypeError, ValueError):
        raise ValueError("operating configuration is missing or invalid") from None


def reserve_model_call(
    state: StateMap, agent_name: str, model: str, input_token_ceiling: int, output_token_ceiling: int,
    call_id: str, now: datetime, invocation_id: str | None = None,
) -> dict[str, object]:
    state = _state(state)
    agent_name, model, call_id = (_identifier(agent_name, "agent name"), _identifier(model, "model"), _identifier(call_id, "call ID"))
    invocation_id = _identifier(invocation_id or call_id, "invocation ID")
    cycle_id = _identifier(state.get("cycle_id"), "cycle ID")
    policy, records = CostPolicy.from_mapping(state.get("model_cost_policy", DEFAULT_COST_POLICY)), _records(state)
    if any(record["call_id"] == call_id for record in records):
        raise ValueError("model call ID already exists")
    if model != policy.model:
        raise ValueError("model is not allowed by the cost policy")
    input_token_ceiling = _tokens(input_token_ceiling, "input token ceiling")
    output_token_ceiling = _tokens(output_token_ceiling, "output token ceiling")
    if input_token_ceiling > policy.maximum_input_tokens_per_call:
        raise ValueError("input token ceiling exceeds cost policy")
    if output_token_ceiling > policy.maximum_output_tokens_per_call:
        raise ValueError("output token ceiling exceeds cost policy")
    if sum(record["cycle_id"] == cycle_id for record in records) >= policy.maximum_model_calls_per_cycle:
        raise ValueError("cycle model-call ceiling is exhausted")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("current time must include a UTC offset")
    day = now.astimezone(timezone.utc).date().isoformat()
    reserved = (
        policy.input_usd_per_million_tokens * input_token_ceiling
        + policy.output_usd_per_million_tokens * output_token_ceiling
    ) / MILLION
    spent = Decimal(0)
    for record in records:
        if record["date"] == day and record["status"] != "released":
            amount = _decimal(record["estimated_reserved_usd"], "reserved cost")
            if record["status"] in {"completed", "violation"}:
                actual = _decimal(record["actual_cost_usd"], "actual cost")
                amount = max(actual, amount if record["status"] == "violation" else Decimal(0))
            spent += amount
    if spent + reserved > _budget(state, policy):
        raise ValueError("daily model cost budget is exhausted; increase the user budget or wait for the next UTC day")
    record: dict[str, object] = {
        "date": day, "cycle_id": cycle_id, "agent": agent_name, "model": model, "call_id": call_id,
        "invocation_id": invocation_id, "estimated_reserved_usd": str(reserved),
        "input_token_ceiling": input_token_ceiling, "output_token_ceiling": output_token_ceiling,
        "input_usd_per_million_tokens": str(policy.input_usd_per_million_tokens),
        "output_usd_per_million_tokens": str(policy.output_usd_per_million_tokens), "status": "reserved",
    }
    # ponytail: session state is single-writer; use a persistent atomic ledger when concurrent invocations arrive.
    state[LEDGER_KEY] = [*records, record]
    return record


def _reserved(state: StateMap, call_id: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    records = _records(state)
    matches = [record for record in records if record["call_id"] == _identifier(call_id, "call ID")]
    if len(matches) != 1 or matches[0]["status"] != "reserved":
        raise ValueError("model call reservation is missing or already finalized")
    return records, matches[0]


def settle_model_call(state: StateMap, call_id: str, actual_input_tokens: int, actual_output_tokens: int) -> dict[str, object]:
    state = _state(state)
    actual_input_tokens = _tokens(actual_input_tokens, "actual input tokens")
    actual_output_tokens = _tokens(actual_output_tokens, "actual output tokens")
    records, record = _reserved(state, call_id)
    cost = (_decimal(record["input_usd_per_million_tokens"], "reserved input price") * actual_input_tokens +
            _decimal(record["output_usd_per_million_tokens"], "reserved output price") * actual_output_tokens) / MILLION
    record.update(actual_input_tokens=actual_input_tokens, actual_output_tokens=actual_output_tokens, actual_cost_usd=str(cost))
    exceeded = actual_input_tokens > record["input_token_ceiling"] or actual_output_tokens > record["output_token_ceiling"]
    record["status"] = "violation" if exceeded else "completed"
    state[LEDGER_KEY] = records
    if exceeded:
        raise ValueError("actual model usage exceeded reserved token ceiling")
    return record


def release_model_call(state: StateMap, call_id: str) -> dict[str, object]:
    state = _state(state)
    records, record = _reserved(state, call_id)
    record["status"] = "released"
    state[LEDGER_KEY] = records
    return record


def _active(state: StateMap, context: object) -> dict[str, object]:
    invocation_id = _identifier(getattr(context, "invocation_id", None), "invocation ID")
    agent_name = _identifier(getattr(context, "agent_name", None), "agent name")
    matches = [record for record in _records(state) if record["invocation_id"] == invocation_id and record["agent"] == agent_name and record["status"] == "reserved"]
    if len(matches) != 1:
        raise ValueError("active model call reservation is missing or ambiguous")
    return matches[0]


def _denied(code: str, message: str) -> LlmResponse:
    return LlmResponse(error_code=code, error_message=message)


def _settle_violation_at_ceiling(state: StateMap, record: dict[str, object]) -> None:
    settle_model_call(state, str(record["call_id"]), int(record["input_token_ceiling"]), int(record["output_token_ceiling"]))
    record["status"] = "violation"
    state[LEDGER_KEY] = _records(state)


async def before_model_cost(callback_context: Context, llm_request: LlmRequest, *, now: datetime | None = None) -> LlmResponse | None:
    try:
        state = _state(getattr(callback_context, "state", None))
        agent_name = _identifier(getattr(callback_context, "agent_name", None), "agent name")
        invocation_id = _identifier(getattr(callback_context, "invocation_id", None), "invocation ID")
        if "operating_config" not in state:
            if agent_name != "chrysopoeia" or _records(state):
                raise ValueError("complete root onboarding before any additional model call")
            state["model_cost_policy"] = BOOTSTRAP_COST_POLICY.copy()
            state["cycle_id"] = f"bootstrap:{invocation_id}"
        policy = CostPolicy.from_mapping(state.get("model_cost_policy", DEFAULT_COST_POLICY))
        requested_input = llm_request.cacheable_contents_token_count
        requested_output = llm_request.config.max_output_tokens
        requested_input = policy.maximum_input_tokens_per_call if requested_input is None else _tokens(requested_input, "requested input token ceiling")
        requested_output = policy.maximum_output_tokens_per_call if requested_output is None else _tokens(requested_output, "requested output token ceiling")
        if requested_input > policy.maximum_input_tokens_per_call or requested_output > policy.maximum_output_tokens_per_call:
            raise ValueError("requested token ceiling exceeds cost policy")
        llm_request.config.max_output_tokens = requested_output
        reserve_model_call(state, agent_name, str(llm_request.model), requested_input, requested_output,
                           f"{invocation_id}:{len(_records(state)) + 1}", now or datetime.now(timezone.utc), invocation_id)
        return None
    except ValueError as exc:
        return _denied("MODEL_COST_POLICY_DENIED", f"Model call denied: {exc}.")


async def after_model_cost(callback_context: Context, llm_response: LlmResponse) -> LlmResponse | None:
    try:
        state = _state(getattr(callback_context, "state", None))
        record = _active(state, callback_context)
        if llm_response.error_code:
            release_model_call(state, str(record["call_id"]))
            return None
        usage = llm_response.usage_metadata
        if usage is None or usage.prompt_token_count is None or usage.candidates_token_count is None:
            _settle_violation_at_ceiling(state, record)
            raise ValueError("model response did not include complete usage metadata")
        try:
            settle_model_call(state, str(record["call_id"]), usage.prompt_token_count + (usage.tool_use_prompt_token_count or 0),
                              usage.candidates_token_count + (usage.thoughts_token_count or 0))
        except (TypeError, ValueError):
            if record["status"] == "reserved":
                _settle_violation_at_ceiling(state, record)
            raise
        return None
    except (TypeError, ValueError) as exc:
        return _denied("MODEL_COST_USAGE_INVALID", f"Model response rejected by cost policy: {exc}.")


async def on_model_cost_error(callback_context: Context, llm_request: LlmRequest, error: Exception) -> LlmResponse | None:
    del llm_request, error
    try:
        state = _state(getattr(callback_context, "state", None))
        release_model_call(state, str(_active(state, callback_context)["call_id"]))
        return None
    except ValueError:
        return _denied("MODEL_COST_RELEASE_FAILED", "Model failure could not release its cost reservation; the reservation remains fail-closed.")
