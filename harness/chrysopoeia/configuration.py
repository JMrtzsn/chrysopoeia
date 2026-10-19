from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from pathlib import Path

from chrysopoeia.trading import OperatingConfig

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


def _number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= MAX_COST_LIMIT
        or not isfinite(value)
    ):
        raise ConfigurationError(f"{name} must be a finite non-negative number")
    return float(value)


@dataclass(frozen=True)
class RuntimeConfig:
    adapter: str
    mode: str


@dataclass(frozen=True)
class VenueConfig:
    adapter: str
    paper_fee_rate: float
    paper_fee_source: str
    series: str
    forecast_offset_seconds: float = 0.0
    window_baseline: bool = False


@dataclass(frozen=True)
class SessionConfig:
    bankroll: float
    maximum_loss: float
    target_win_rate: float
    window_minutes: float
    max_cycles: int
    cost_budget: Decimal
    interval_seconds: float
    daily_cloud_cost_budget: float


@dataclass(frozen=True)
class RiskConfig:
    maximum_market_exposure: float
    maximum_total_exposure: float
    market_exposure: float
    total_exposure: float


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
class ResearchConfig:
    enabled: bool = True


@dataclass(frozen=True)
class HarnessConfig:
    runtime: RuntimeConfig
    venue: VenueConfig
    models: ModelConfig
    cost: CostConfig
    session: SessionConfig
    risk: RiskConfig
    research: ResearchConfig = ResearchConfig()

    @classmethod
    def from_mapping(cls, value: object) -> "HarnessConfig":
        root_keys = {"runtime", "venue", "models", "cost", "session", "risk"}
        if isinstance(value, Mapping) and "research" in value:
            root_keys.add("research")
        root = _table(value, root_keys, "harness")
        research_raw = root.get("research", {"enabled": True})
        research = _table(research_raw, {"enabled"}, "research")
        enabled = research["enabled"]
        if not isinstance(enabled, bool):
            raise ConfigurationError("research enabled must be a boolean")
        research_config = ResearchConfig(enabled)
        runtime = _table(root["runtime"], {"adapter", "mode"}, "runtime")
        venue_keys = {"adapter", "paper_fee_rate", "paper_fee_source", "series"}
        for optional in ("forecast_offset_seconds", "window_baseline"):
            if isinstance(root["venue"], Mapping) and optional in root["venue"]:
                venue_keys.add(optional)
        venue = _table(root["venue"], venue_keys, "venue")
        session = _table(root["session"], {
            "bankroll", "maximum_loss", "target_win_rate", "window_minutes",
            "max_cycles", "cost_budget", "interval_seconds", "daily_cloud_cost_budget",
        }, "session")
        risk = _table(root["risk"], {
            "maximum_market_exposure", "maximum_total_exposure",
            "market_exposure", "total_exposure",
        }, "risk")
        session_config = SessionConfig(
            _number(session["bankroll"], "bankroll"),
            _number(session["maximum_loss"], "maximum loss"),
            _number(session["target_win_rate"], "target win rate"),
            _number(session["window_minutes"], "window minutes"),
            _positive_int(session["max_cycles"], "max cycles"),
            _price(session["cost_budget"], "cost budget"),
            _number(session["interval_seconds"], "interval seconds"),
            _number(session["daily_cloud_cost_budget"], "daily cloud cost budget"),
        )
        if (
            session_config.target_win_rate > 1
            or session_config.window_minutes <= 0
            or session_config.max_cycles > 1000
            or session_config.daily_cloud_cost_budget <= 0
        ):
            raise ConfigurationError("session operating limits are invalid")
        risk_config = RiskConfig(*(
            _number(risk[key], key) for key in (
                "maximum_market_exposure", "maximum_total_exposure",
                "market_exposure", "total_exposure",
            )
        ))
        if not 0 <= risk_config.market_exposure <= risk_config.total_exposure <= session_config.bankroll:
            raise ConfigurationError("existing exposures are inconsistent")
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
        series = _text(venue["series"], "venue series")
        if series != "btc-updown-5m":
            raise ConfigurationError("venue series is unsupported")
        if session_config.interval_seconds != 300:
            raise ConfigurationError("BTC 5m series requires a 300-second interval")
        offset = venue.get("forecast_offset_seconds", 0)
        if (
            isinstance(offset, bool)
            or not isinstance(offset, (int, float))
            or not isfinite(offset)
            or not 0 <= offset < 300
        ):
            raise ConfigurationError(
                "forecast offset must be a finite number of seconds in [0, 300)"
            )
        baseline = venue.get("window_baseline", False)
        if not isinstance(baseline, bool):
            raise ConfigurationError("window baseline must be a boolean")
        venue_config = VenueConfig(
            adapter, float(fee), fee_source, series, float(offset), baseline
        )

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
        result = cls(
            runtime_config,
            venue_config,
            model_config,
            cost_config,
            session_config,
            risk_config,
            research_config,
        )
        try:
            _ = result.operating
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from None
        return result

    @property
    def operating(self) -> OperatingConfig:
        return OperatingConfig(
            self.session.bankroll, 1,
            self.risk.maximum_market_exposure, self.risk.maximum_total_exposure,
            self.session.maximum_loss, self.session.daily_cloud_cost_budget,
        )

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
