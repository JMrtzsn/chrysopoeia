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
COST_POLICY_VERSION = "project-estimate-2026-10-v1"


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
    adapter: str
    location: str
    root: str
    context: str
    trader: str
    reviewer: str


@dataclass(frozen=True)
class ModelPrice:
    model: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal


@dataclass(frozen=True)
class CostConfig:
    model: str
    prices: tuple[ModelPrice, ...]
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
        cost_keys = {
            "model",
            "input_usd_per_million_tokens",
            "output_usd_per_million_tokens",
            "maximum_input_tokens_per_call",
            "maximum_output_tokens_per_call",
            "maximum_model_calls_per_cycle",
        }
        cost_raw = root["cost"]
        if isinstance(cost_raw, Mapping) and "models" in cost_raw:
            cost_keys.add("models")
        cost = _table(root["cost"], cost_keys, "cost")
        models_raw = root["models"]
        model_keys = {"root", "context", "trader", "reviewer"}
        if isinstance(models_raw, Mapping) and "adapter" in models_raw:
            model_keys.add("adapter")
        if isinstance(models_raw, Mapping) and "location" in models_raw:
            model_keys.add("location")
        models = _table(models_raw, model_keys, "models")

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

        model_adapter = _text(
            models.get("adapter", "adk-gemini")
            if isinstance(models, Mapping)
            else models,
            "models adapter",
        )
        if model_adapter not in {"adk-gemini", "adk-registry"}:
            raise ConfigurationError("models adapter is unsupported")
        model_location = _text(models.get("location", "us"), "models location")
        if model_location != "us":
            raise ConfigurationError("models location is unsupported")
        model_config = ModelConfig(
            model_adapter,
            model_location,
            *(_text(models[name], f"{name} model") for name in ("root", "context", "trader", "reviewer")),
        )
        if not model_config.context.startswith("gemini-"):
            raise ConfigurationError("context model must be a Gemini model")
        configured_models = [
            getattr(model_config, role)
            for role in ("root", "context", "trader", "reviewer")
        ]
        cost_model = _text(cost["model"], "cost model")
        flat_input = _price(cost["input_usd_per_million_tokens"], "input price")
        flat_output = _price(cost["output_usd_per_million_tokens"], "output price")
        if "models" in cost:
            pricing = cost["models"]
            if not isinstance(pricing, Mapping) or not pricing:
                raise ConfigurationError("cost model pricing is missing or invalid")
            priced: list[ModelPrice] = []
            for name in sorted(pricing):
                entry = pricing[name]
                if not isinstance(entry, Mapping) or set(entry) != {
                    "input_usd_per_million_tokens",
                    "output_usd_per_million_tokens",
                }:
                    raise ConfigurationError(
                        f"{name} cost pricing is missing or invalid"
                    )
                priced.append(
                    ModelPrice(
                        _text(name, "cost model"),
                        _price(
                            entry["input_usd_per_million_tokens"],
                            f"{name} input price",
                        ),
                        _price(
                            entry["output_usd_per_million_tokens"],
                            f"{name} output price",
                        ),
                    )
                )
            required = {*configured_models, cost_model}
            if any(price.model not in required for price in priced):
                raise ConfigurationError(
                    "priced cost models must all be configured models"
                )
            if any(
                model not in {price.model for price in priced} for model in required
            ):
                raise ConfigurationError(
                    "every configured model must have explicit pricing"
                )
        else:
            priced = (ModelPrice(cost_model, flat_input, flat_output),)
            if any(model != cost_model for model in configured_models):
                raise ConfigurationError(
                    "all configured models must match the priced model"
                )
        cost_config = CostConfig(
            cost_model,
            tuple(priced),
            flat_input,
            flat_output,
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
        maximum_input = self.cost.maximum_input_tokens_per_call
        maximum_output = self.cost.maximum_output_tokens_per_call
        maximum_calls = self.cost.maximum_model_calls_per_cycle
        if len(self.cost.prices) == 1:
            price = self.cost.prices[0]
            return {
                "version": COST_POLICY_VERSION,
                "model": price.model,
                "input_usd_per_million_tokens": str(price.input_usd_per_million_tokens),
                "output_usd_per_million_tokens": str(
                    price.output_usd_per_million_tokens
                ),
                "maximum_input_tokens_per_call": maximum_input,
                "maximum_output_tokens_per_call": maximum_output,
                "maximum_model_calls_per_cycle": maximum_calls,
            }
        return {
            "version": COST_POLICY_VERSION,
            "models": {
                price.model: {
                    "input_usd_per_million_tokens": str(
                        price.input_usd_per_million_tokens
                    ),
                    "output_usd_per_million_tokens": str(
                        price.output_usd_per_million_tokens
                    ),
                }
                for price in self.cost.prices
            },
            "maximum_input_tokens_per_call": maximum_input,
            "maximum_output_tokens_per_call": maximum_output,
            "maximum_model_calls_per_cycle": maximum_calls,
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
