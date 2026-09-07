import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from chrysopoeia.configuration import (
    ConfigurationError,
    HarnessConfig,
    load_harness_config,
)

DEFAULT_CONFIG = Path(__file__).parents[1] / "chrysopoeia.toml"


def _summary(config: HarnessConfig, command: str, label: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": command,
        "valid": True,
        "config_path": label,
        "runtime": {"adapter": config.runtime.adapter, "mode": config.runtime.mode},
        "venue": {
            "adapter": config.venue.adapter,
            "market_data": "public-read-only",
            "execution": "paper-only",
            "paper_fee_rate": config.venue.paper_fee_rate,
            "paper_fee_source": config.venue.paper_fee_source,
        },
        "models": {
            "root": config.models.root,
            "context": config.models.context,
            "trader": config.models.trader,
            "reviewer": config.models.reviewer,
        },
        "cost_policy": config.cost_policy,
    }


def _human(summary: dict[str, object]) -> str:
    runtime = summary["runtime"]
    venue = summary["venue"]
    models = summary["models"]
    cost = summary["cost_policy"]
    assert isinstance(runtime, dict)
    assert isinstance(venue, dict)
    assert isinstance(models, dict)
    assert isinstance(cost, dict)
    return "\n".join(
        (
            f"configuration valid: {summary['config_path']}",
            f"runtime: {runtime['adapter']} ({runtime['mode']})",
            f"venue: {venue['adapter']} ({venue['market_data']}, {venue['execution']})",
            f"paper fee: {venue['paper_fee_rate']} ({venue['paper_fee_source']})",
            "models: " + ", ".join(f"{role}={model}" for role, model in models.items()),
            f"cost policy: {cost['version']} ({cost['model']})",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chrysopoeia")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path)
        command.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    path = args.config or DEFAULT_CONFIG
    label = "chrysopoeia.toml" if args.config is None else args.config.name
    try:
        config = load_harness_config(path)
    except (ConfigurationError, OSError, TypeError, ValueError) as exc:
        message = str(exc)
        if str(path) in message:
            message = "could not load harness configuration"
        parser.exit(2, f"configuration invalid: {message}\n")
    summary = _summary(config, args.command, label[:200])
    print(json.dumps(summary, sort_keys=True) if args.json else _human(summary))
    return 0
