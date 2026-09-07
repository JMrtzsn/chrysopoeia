import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from chrysopoeia.configuration import (
    ConfigurationError,
    HarnessConfig,
    load_harness_config,
)
from chrysopoeia.polymarket import _fetch as polymarket_fetch
from chrysopoeia.polymarket import load_market_snapshot
from chrysopoeia.trading import MarketSnapshot

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


def serialize_market_snapshot(snapshot: MarketSnapshot) -> dict[str, object]:
    """Return the bounded public capture record for one rich market snapshot."""
    if not snapshot.asks or not all(
        (
            snapshot.question,
            snapshot.resolution_rules,
            snapshot.end_time,
            snapshot.captured_at,
            snapshot.source_url,
            snapshot.yes_token_id,
        )
    ):
        raise ValueError("market snapshot metadata is incomplete")
    return {
        "schema_version": 1,
        "record_type": "market_snapshot",
        "venue": "polymarket",
        "mode": "paper",
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "market_id": snapshot.market_id,
            "price": snapshot.price,
            "question": snapshot.question,
            "resolution_rules": snapshot.resolution_rules,
            "end_time": snapshot.end_time,
            "captured_at": snapshot.captured_at,
            "source_url": snapshot.source_url,
            "yes_token_id": snapshot.yes_token_id,
            "asks": [
                {"price": level.price, "size": level.size} for level in snapshot.asks
            ],
            "fee_rate": snapshot.fee_rate,
            "fee_source": snapshot.fee_source,
        },
    }


def _write_new(path: Path, content: bytes) -> None:
    temporary: str | None = None
    linked = False
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
            temporary = target.name
            os.chmod(temporary, 0o600)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path)
        linked = True
        os.unlink(temporary)
        temporary = None
    except OSError:
        if linked:
            try:
                os.unlink(path)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chrysopoeia")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path)
        command.add_argument("--json", action="store_true")
    capture = commands.add_parser("capture")
    capture.add_argument("market")
    capture.add_argument("--config", type=Path)
    capture.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    path = args.config or DEFAULT_CONFIG
    label = "chrysopoeia.toml" if args.config is None else args.config.name
    try:
        config = load_harness_config(path)
    except (ConfigurationError, OSError, TypeError, ValueError) as exc:
        if args.command == "capture":
            parser.exit(2, "capture failed: invalid configuration\n")
        message = str(exc)
        if str(path) in message:
            message = "could not load harness configuration"
        parser.exit(2, f"configuration invalid: {message}\n")
    if args.command == "capture":
        try:
            snapshot = load_market_snapshot(
                args.market,
                bankroll=1.0,
                market_exposure=0.0,
                total_exposure=0.0,
                fetch=polymarket_fetch,
                paper_fee_rate=config.venue.paper_fee_rate,
                paper_fee_source=config.venue.paper_fee_source,
            )
            content = (
                json.dumps(
                    serialize_market_snapshot(snapshot),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
        except Exception:
            parser.exit(2, "capture failed: market data unavailable\n")
        if args.output is not None:
            try:
                _write_new(args.output, content)
            except (OSError, ValueError):
                parser.exit(2, "capture failed: output unavailable\n")
        print(content.decode(), end="")
        return 0
    summary = _summary(config, args.command, label[:200])
    print(json.dumps(summary, sort_keys=True) if args.json else _human(summary))
    return 0
