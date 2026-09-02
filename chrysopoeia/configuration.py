from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


MAX_TEXT_LENGTH = 200
MAX_COST_LIMIT = 100_000_000
COST_POLICY_VERSION = "project-estimate-2026-08-v1"


class ConfigurationError(ValueError):
    """A safe operator-configuration failure."""


def _table(value: object, keys: set[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ConfigurationError(f"{name} configuration is missing or invalid")
    return value


def _text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > MAX_TEXT_LENGTH
    ):
        raise ConfigurationError(
            f"{name} must be a non-blank string of at most {MAX_TEXT_LENGTH} characters"
        )
    return value


def _price(value: object, name: str) -> Decimal:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > MAX_TEXT_LENGTH
    ):
        raise ConfigurationError(f"{name} must be a finite non-negative decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ConfigurationError(
            f"{name} must be a finite non-negative decimal string"
        ) from None
    if not result.is_finite() or result < 0:
        raise ConfigurationError(f"{name} must be a finite non-negative decimal string")
    return result


def _positive_int(value: object, name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= MAX_COST_LIMIT
    ):
        raise ConfigurationError(
            f"{name} must be a positive integer no greater than {MAX_COST_LIMIT}"
        )
    return value


@dataclass(frozen=True)
class RuntimeConfig:
    adapter: str
    mode: str


@dataclass(frozen=True)
class VenueConfig:
    adapter: str
    paper_fee_rate: float
    paper_fee_source: str


@dataclass(frozen=True)
class ModelConfig:
    root: str
    context: str
    trader: str
    reviewer: str


@dataclass(frozen=True)
class CostConfig:
    model: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal
    maximum_input_tokens_per_call: int
    maximum_output_tokens_per_call: int
    maximum_model_calls_per_cycle: int


@dataclass(frozen=True)
class HarnessConfig:
    runtime: RuntimeConfig
    venue: VenueConfig
    models: ModelConfig
    cost: CostConfig

    @classmethod
    def from_mapping(cls, value: object) -> "HarnessConfig":
        root = _table(value, {"runtime", "venue", "models", "cost"}, "harness")
        runtime = _table(root["runtime"], {"adapter", "mode"}, "runtime")
        venue = _table(
            root["venue"],
            {"adapter", "paper_fee_rate", "paper_fee_source"},
            "venue",
        )
        models = _table(
            root["models"], {"root", "context", "trader", "reviewer"}, "models"
        )
        cost = _table(
            root["cost"],
            {
                "model",
                "input_usd_per_million_tokens",
                "output_usd_per_million_tokens",
                "maximum_input_tokens_per_call",
                "maximum_output_tokens_per_call",
                "maximum_model_calls_per_cycle",
            },
            "cost",
        )

        runtime_config = RuntimeConfig(
            _text(runtime["adapter"], "runtime adapter"),
            _text(runtime["mode"], "runtime mode"),
        )
        if runtime_config != RuntimeConfig("adk", "paper"):
            raise ConfigurationError("runtime adapter or mode is unsupported")

        adapter = _text(venue["adapter"], "venue adapter")
        if adapter != "polymarket":
            raise ConfigurationError("venue adapter is unsupported")
        fee = venue["paper_fee_rate"]
        if (
            isinstance(fee, bool)
            or not isinstance(fee, (int, float))
            or not isfinite(fee)
            or not 0 <= fee < 1
        ):
            raise ConfigurationError(
                "paper fee rate must be finite and between 0 and 1"
            )
        fee_source = _text(venue["paper_fee_source"], "paper fee source")
        if fee and fee_source == "paper-assumption:no-fee-v1":
            raise ConfigurationError("positive paper fee requires explicit provenance")
        venue_config = VenueConfig(adapter, float(fee), fee_source)

        model_config = ModelConfig(
            *(
                _text(models[name], f"{name} model")
                for name in ModelConfig.__annotations__
            )
        )
        cost_model = _text(cost["model"], "cost model")
        if any(model != cost_model for model in model_config.__dict__.values()):
            raise ConfigurationError(
                "all configured models must match the priced model"
            )
        cost_config = CostConfig(
            cost_model,
            _price(cost["input_usd_per_million_tokens"], "input price"),
            _price(cost["output_usd_per_million_tokens"], "output price"),
            _positive_int(
                cost["maximum_input_tokens_per_call"], "maximum input tokens"
            ),
            _positive_int(
                cost["maximum_output_tokens_per_call"], "maximum output tokens"
            ),
            _positive_int(cost["maximum_model_calls_per_cycle"], "maximum model calls"),
        )
        return cls(runtime_config, venue_config, model_config, cost_config)

    @property
    def cost_policy(self) -> dict[str, object]:
        return {
            "version": COST_POLICY_VERSION,
            "model": self.cost.model,
            "input_usd_per_million_tokens": str(self.cost.input_usd_per_million_tokens),
            "output_usd_per_million_tokens": str(
                self.cost.output_usd_per_million_tokens
            ),
            "maximum_input_tokens_per_call": self.cost.maximum_input_tokens_per_call,
            "maximum_output_tokens_per_call": self.cost.maximum_output_tokens_per_call,
            "maximum_model_calls_per_cycle": self.cost.maximum_model_calls_per_cycle,
        }


def load_harness_config(path: Path) -> HarnessConfig:
    """Load one exact, non-secret operator configuration from TOML."""
    try:
        with path.open("rb") as source:
            value = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError):
        raise ConfigurationError(
            f"could not load harness configuration from {path}"
        ) from None
    return HarnessConfig.from_mapping(value)
