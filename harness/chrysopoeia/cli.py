import argparse
import asyncio
import json
import os
import signal
import stat
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from chrysopoeia.configuration import (
    ConfigurationError,
    HarnessConfig,
    load_harness_config,
)
from chrysopoeia.paper_cycle import (
    EvidenceRecord,
    PaperCycleRequest,
    _canonical_evidence,
    validate_evidence_bundle,
)
from chrysopoeia.polymarket import _fetch as polymarket_fetch
from chrysopoeia.polymarket import discover_markets, load_market_snapshot
from chrysopoeia.trading import (
    BookLevel,
    MarketSnapshot,
    OperatingConfig,
    market_snapshot_identity,
)

DEFAULT_CONFIG_ENV = "CHRYSOPOEIA_CONFIG"


def default_config_path() -> Path:
    """Config resolution: environment override, then repo-local default."""
    override = os.environ.get(DEFAULT_CONFIG_ENV)
    if override:
        return Path(override)
    return Path(__file__).parents[1] / "chrysopoeia.toml"


MAX_SNAPSHOT_BYTES = 512 * 1024
_CAPTURE_KEYS = {"schema_version", "record_type", "venue", "mode", "snapshot"}
_SNAPSHOT_KEYS = {
    "snapshot_id",
    "market_id",
    "price",
    "question",
    "resolution_rules",
    "end_time",
    "captured_at",
    "source_url",
    "yes_token_id",
    "asks",
    "fee_rate",
    "fee_source",
}
_EVIDENCE_BUNDLE_KEYS = {
    "schema_version",
    "record_type",
    "snapshot_id",
    "market_id",
    "evidence",
    "provenance",
}


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
            "series": config.venue.series,
            "forecast_offset_seconds": config.venue.forecast_offset_seconds,
            "window_baseline": config.venue.window_baseline,
        },
        "models": {
            "location": config.models.location,
            "root": config.models.root,
            "context": config.models.context,
            "trader": config.models.trader,
            "reviewer": config.models.reviewer,
        },
        "cost_policy": config.cost_policy,
        "research": {"enabled": config.research.enabled},
        "session": {**asdict(config.session), "cost_budget": str(config.session.cost_budget)},
        "risk": asdict(config.risk),
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
            **({
                "no_token_id": snapshot.no_token_id,
                "no_asks": [{"price": level.price, "size": level.size} for level in snapshot.no_asks],
                "no_bids": [{"price": level.price, "size": level.size} for level in snapshot.no_bids],
                "no_book_captured_at": snapshot.no_book_captured_at,
            } if snapshot.no_token_id else {}),
        },
    }


def _bounded_json(path: Path, error: str) -> dict[str, object]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError(error)
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            body = source.read(MAX_SNAPSHOT_BYTES + 1)
    except (OSError, ValueError):
        raise ValueError(error) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(body) > MAX_SNAPSHOT_BYTES:
        raise ValueError(error)
    try:

        def object_value(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result = dict(pairs)
            if len(result) != len(pairs):
                raise ValueError
            return result

        value = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=object_value,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise ValueError(error) from None
    if not isinstance(value, dict):
        raise ValueError(error)
    return value


def _bounded_capture(path: Path) -> dict[str, object]:
    return _bounded_json(path, "invalid snapshot")


def load_evidence_bundle(path: Path, snapshot: MarketSnapshot) -> list[EvidenceRecord]:
    """Load an exact snapshot-bound local evidence bundle."""
    envelope = _bounded_json(path, "invalid evidence")
    try:
        if (
            set(envelope) != _EVIDENCE_BUNDLE_KEYS
            or isinstance(envelope["schema_version"], bool)
            or envelope["schema_version"] != 1
            or envelope["record_type"] != "evidence_bundle"
            or envelope["snapshot_id"] != snapshot.snapshot_id
            or envelope["market_id"] != snapshot.market_id
            or envelope["provenance"] != "operator-supplied-unverified"
            or not isinstance(envelope["evidence"], list)
            or not 2 <= len(envelope["evidence"]) <= 20
        ):
            raise ValueError
        evidence = [
            EvidenceRecord.model_validate(item) for item in envelope["evidence"]
        ]
        if evidence[0] != _canonical_evidence(snapshot)[0] or len(evidence[1:]) > 19:
            raise ValueError
        return validate_evidence_bundle(snapshot, evidence)
    except (IndexError, TypeError, ValueError):
        raise ValueError("invalid evidence") from None


def _capture_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 10_000:
        raise ValueError("invalid snapshot")
    return value


def _capture_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid snapshot")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError("invalid snapshot") from None
    if not (result == result and abs(result) != float("inf")):
        raise ValueError("invalid snapshot")
    return result


def load_capture_snapshot(
    path: Path,
    config: HarnessConfig,
    operating: OperatingConfig,
    market_exposure: float = 0,
    total_exposure: float = 0,
) -> MarketSnapshot:
    """Load one exact capture record without market access."""
    envelope = _bounded_capture(path)
    if (
        set(envelope) != _CAPTURE_KEYS
        or envelope["schema_version"] != 1
        or isinstance(envelope["schema_version"], bool)
        or envelope["record_type"] != "market_snapshot"
        or envelope["venue"] != "polymarket"
        or envelope["mode"] != "paper"
        or not isinstance(envelope["snapshot"], dict)
        or set(envelope["snapshot"]) not in (
            _SNAPSHOT_KEYS,
            _SNAPSHOT_KEYS | {"no_token_id", "no_asks", "no_bids", "no_book_captured_at"},
        )
    ):
        raise ValueError("invalid snapshot")
    value = envelope["snapshot"]
    assert isinstance(value, dict)
    asks = value["asks"]
    if not isinstance(asks, list) or not 1 <= len(asks) <= 50:
        raise ValueError("invalid snapshot")
    try:
        levels = tuple(
            BookLevel(_capture_number(level["price"]), _capture_number(level["size"]))
            for level in asks
            if isinstance(level, dict) and set(level) == {"price", "size"}
        )
        if len(levels) != len(asks):
            raise ValueError
        fee_rate = _capture_number(value["fee_rate"])
        fee_source = _capture_text(value["fee_source"])
        if (fee_rate, fee_source) != (
            config.venue.paper_fee_rate,
            config.venue.paper_fee_source,
        ):
            raise ValueError
        snapshot = MarketSnapshot(
            _capture_text(value["snapshot_id"]),
            _capture_text(value["market_id"]),
            _capture_number(value["price"]),
            operating.bankroll,
            _capture_number(market_exposure),
            _capture_number(total_exposure),
            _capture_text(value["question"]),
            _capture_text(value["resolution_rules"]),
            _capture_text(value["end_time"]),
            _capture_text(value["captured_at"]),
            _capture_text(value["source_url"]),
            _capture_text(value["yes_token_id"]),
            levels,
            fee_rate,
            fee_source,
            _capture_text(value["captured_at"]),
            **({key: value[key] for key in ("no_token_id", "no_asks", "no_bids", "no_book_captured_at")}
               if "no_token_id" in value else {}),
        )
        if snapshot.snapshot_id != market_snapshot_identity(snapshot):
            raise ValueError
        return snapshot
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid snapshot") from None


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
    discover = commands.add_parser("discover")
    discover.add_argument("--config", type=Path)
    cycle = commands.add_parser("cycle")
    targets = cycle.add_mutually_exclusive_group()
    targets.add_argument("--snapshot", type=Path)
    targets.add_argument("--market")
    cycle.add_argument("--context")
    cycle.add_argument("--draft")
    cycle.add_argument("--config", type=Path)
    cycle.add_argument("--evidence", type=Path)
    cycle.add_argument("--journal", type=Path)
    cycle.add_argument("--output", type=Path)
    run = commands.add_parser("run")
    run.add_argument("--journal", type=Path, required=True)
    run.add_argument("--config", type=Path)
    run.add_argument("--stop-file", type=Path)
    book = commands.add_parser("book")
    book.add_argument("--journal", type=Path, required=True)
    settle_command = commands.add_parser("settle")
    settle_command.add_argument("--journal", type=Path, required=True)
    settle_command.add_argument("--market", required=True)
    mark = commands.add_parser("mark")
    mark.add_argument("--journal", type=Path, required=True)
    mark.add_argument("--config", type=Path)
    consume = commands.add_parser("consume")
    consume.add_argument("--event", type=Path, required=True)
    consume.add_argument("--journal", type=Path, required=True)
    consume.add_argument("--config", type=Path)
    pending = commands.add_parser("outbox-pending")
    pending.add_argument("--journal", type=Path, required=True)
    ack = commands.add_parser("outbox-ack")
    ack.add_argument("--journal", type=Path, required=True)
    ack.add_argument("event_id")
    polymarket_eval = commands.add_parser(
        "polymarket-eval",
        help="score local forecasts against resolved Polymarket outcomes",
    )
    polymarket_eval.add_argument("--journal", type=Path, required=True)
    polymarket_eval.add_argument(
        "--series-url",
        help="optional: only score markets in this market URL's recurring series",
    )
    args = parser.parse_args(argv)
    if args.command in {"cycle", "run"}:
        from chrysopoeia.events import configured_sink

        try:
            sink = configured_sink()
        except ValueError as exc:
            parser.exit(2, f"{args.command} failed: {exc}\n")
        if sink and args.command == "cycle" and args.journal is None:
            parser.exit(2, "cycle failed: event sink requires --journal\n")
    if args.command in {"outbox-pending", "outbox-ack"}:
        from chrysopoeia.accounting import (
            JournalError,
            acknowledge_event,
            pending_events,
        )

        try:
            if args.command == "outbox-pending":
                for event in pending_events(args.journal):
                    print(json.dumps(event, sort_keys=True, separators=(",", ":")))
            else:
                acknowledge_event(args.journal, args.event_id)
        except (JournalError, OSError, ValueError) as exc:
            parser.exit(2, f"{args.command} failed: {exc}\n")
        return 0
    if args.command == "polymarket-eval":
        from chrysopoeia.accounting import JournalError
        from chrysopoeia.polymarket_evaluation import evaluate_journal

        try:
            result = evaluate_journal(args.journal, series_url=args.series_url)
        except (JournalError, OSError, ValueError) as exc:
            parser.exit(2, f"polymarket-eval failed: {exc}\n")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "consume":
        from chrysopoeia.accounting import JournalError, replay
        from chrysopoeia.operations import consume_paper_event
        from chrysopoeia.trading import parse_trade_plan

        try:
            event = parse_trade_plan(_bounded_json(args.event, "invalid event"))
        except (TypeError, ValueError):
            parser.exit(2, "consume failed: invalid event\n")
        try:
            consume_config = load_harness_config(args.config or default_config_path())
        except (ConfigurationError, OSError, TypeError, ValueError):
            parser.exit(2, "consume failed: invalid configuration\n")
        try:
            state = replay(args.journal)
            result = consume_paper_event(
                args.journal,
                event,
                OperatingConfig(
                    bankroll=state.bankroll or 1,
                    maximum_loss=state.maximum_loss or 1,
                ),
                now=datetime.now(timezone.utc),
                fetch=polymarket_fetch,
                paper_fee_rate=consume_config.venue.paper_fee_rate,
                paper_fee_source=consume_config.venue.paper_fee_source,
                load=load_market_snapshot,
            )
        except JournalError as exc:
            parser.exit(2, f"consume failed: {exc}\n")
        except (TypeError, ValueError) as exc:
            parser.exit(2, f"consume failed: {exc}\n")
        except Exception:
            parser.exit(2, "consume failed: market data unavailable\n")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "mark":
        from chrysopoeia.accounting import JournalError, replay
        from chrysopoeia.operations import mark_positions

        try:
            journal_state = replay(args.journal)
            if not journal_state.positions:
                print(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "record_type": "book_mark_report",
                            "journal": str(args.journal),
                            "marked": [],
                            "status": journal_state.status,
                            "realized_pnl": journal_state.realized_pnl,
                            "unrealized_pnl": journal_state.unrealized_pnl,
                            "open_exposure": journal_state.open_exposure,
                            "bankroll_now": journal_state.bankroll_now,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                return 0
            try:
                mark_config = load_harness_config(
                    args.config or default_config_path()
                )
                marked = mark_positions(
                    args.journal,
                    tuple(journal_state.positions),
                    fetch=polymarket_fetch,
                    paper_fee_rate=mark_config.venue.paper_fee_rate,
                    paper_fee_source=mark_config.venue.paper_fee_source,
                    load=load_market_snapshot,
                )
            except Exception as exc:
                market_id = next(iter(journal_state.positions))
                raise JournalError(
                    f"mark capture for market {market_id} failed"
                ) from exc
            final = replay(args.journal)
        except (ConfigurationError, OSError, ValueError, JournalError) as exc:
            parser.exit(2, f"mark failed: {exc}\n")
        summary = {
            "schema_version": 1,
            "record_type": "book_mark_report",
            "journal": str(args.journal),
            "marked": marked,
            "status": final.status,
            "realized_pnl": final.realized_pnl,
            "unrealized_pnl": final.unrealized_pnl,
            "open_exposure": final.open_exposure,
            "bankroll_now": final.bankroll_now,
        }
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "settle":
        from chrysopoeia.accounting import JournalError, replay
        from chrysopoeia.operations import settle_positions
        from chrysopoeia.polymarket import load_market_resolution

        try:
            journal_state = replay(args.journal)
            if args.market not in journal_state.positions:
                raise JournalError(f"no open position for market {args.market}")
            resolution_record = settle_positions(
                args.journal,
                (args.market,),
                fetch=polymarket_fetch,
                load=load_market_resolution,
            )[0]
            settled_state = replay(args.journal)
        except (ValueError, JournalError) as exc:
            parser.exit(2, f"settle failed: {exc}\n")
        except Exception:
            parser.exit(2, "settle failed: resolution data unavailable\n")
        summary = {
            "schema_version": 1,
            "record_type": "settlement_report",
            "market_id": resolution_record["market_id"],
            "resolution": resolution_record["resolution"],
            "resolved_at": resolution_record["resolved_at"],
            "status": settled_state.status,
            "realized_pnl": settled_state.realized_pnl,
            "unrealized_pnl": settled_state.unrealized_pnl,
            "open_exposure": settled_state.open_exposure,
            "bankroll_now": settled_state.bankroll_now,
            "open_positions": len(settled_state.positions),
        }
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "book":
        from chrysopoeia.accounting import JournalError, replay

        try:
            state = replay(args.journal)
        except ValueError as exc:
            parser.exit(2, f"book failed: {exc}\n")
        except JournalError as exc:
            parser.exit(2, f"book failed: {exc}\n")
        positions = [
            {
                "market_id": position.market_id,
                "snapshot_id": position.snapshot_id,
                "quote_snapshot_id": position.quote_snapshot_id,
                "entered_at": position.entered_at,
                "price": position.price,
                "shares": position.shares,
                "total_cost": position.total_cost,
                "mark_price": state.marks.get(position.market_id, position.price),
                "exit_plan": (
                    asdict(position.exit_plan)
                    if position.exit_plan is not None
                    else None
                ),
            }
            for position in state.positions.values()
        ]
        summary = {
            "schema_version": 1,
            "record_type": "book_report",
            "journal": str(args.journal),
            "status": state.status,
            "bankroll": state.bankroll,
            "maximum_loss": state.maximum_loss,
            "realized_pnl": state.realized_pnl,
            "settled_trades": state.settled_trades,
            "closed_trades": state.closed_trades,
            "unrealized_pnl": state.unrealized_pnl,
            "open_exposure": state.open_exposure,
            "bankroll_now": state.bankroll_now,
            "open_positions": positions,
            "admitted_turns": len(state.admitted_turns),
            "open_turns": len(state.open_turns),
        }
        print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return 0
    path = args.config or default_config_path()
    label = path.name
    try:
        config = load_harness_config(path)
    except (ConfigurationError, OSError, TypeError, ValueError) as exc:
        if args.command in {"capture", "discover", "run"}:
            if args.command == "run":
                parser.exit(2, "run failed: invalid configuration\n")
            if args.command == "discover":
                parser.exit(2, "discovery failed: invalid configuration\n")
            parser.exit(2, "capture failed: invalid configuration\n")
        if args.command == "cycle":
            parser.exit(2, "cycle failed: model/workflow unavailable\n")
        message = str(exc)
        if str(path) in message:
            message = "could not load harness configuration"
        parser.exit(2, f"configuration invalid: {message}\n")
    if args.command == "run":
        from chrysopoeia.accounting import JournalError
        from chrysopoeia.loop import LoopParams, StopFlag, run_loop

        if config.risk.market_exposure or config.risk.total_exposure:
            parser.exit(2, "run failed: existing exposures are cycle-only; run uses its journal\n")
        flag = StopFlag()
        previous = {}
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, flag.stop)
            report, iterations = asyncio.run(
                run_loop(
                    LoopParams(
                        args.journal,
                        config.session.bankroll,
                        config.session.maximum_loss,
                        config.session.target_win_rate,
                        config.session.window_minutes,
                        config.session.max_cycles,
                        config.session.cost_budget,
                        config.session.interval_seconds,
                        config.risk.maximum_market_exposure,
                        config.risk.maximum_total_exposure,
                        config.session.daily_cloud_cost_budget,
                        args.stop_file,
                        flag,
                        config.venue.series,
                        config.venue.forecast_offset_seconds,
                    ),
                    config,
                    sleep=asyncio.sleep,
                    fetch=polymarket_fetch,
                )
            )
        except (JournalError, OSError, TypeError, ValueError) as exc:
            parser.exit(2, f"run failed: {exc}\n")
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        for iteration in iterations:
            print(
                json.dumps(iteration, sort_keys=True, separators=(",", ":")),
                file=sys.stderr,
            )
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "capture":
        try:
            snapshot = load_market_snapshot(
                args.market,
                bankroll=1.0,
                market_exposure=0.0,
                total_exposure=0.0,
                include_no_book=True,
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
    if args.command == "discover":
        try:
            candidates = discover_markets(
                series=config.venue.series,
                fetch=polymarket_fetch,
            )
            result = {
                "schema_version": 1,
                "record_type": "market_discovery",
                "venue": "polymarket",
                "mode": "public-read-only",
                "candidates": [candidate.as_dict() for candidate in candidates],
            }
        except Exception:
            parser.exit(2, "discovery failed: market data unavailable\n")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "cycle":
        if args.journal is not None and args.snapshot is None and args.market is None:
            parser.exit(2, "cycle failed: --journal requires --snapshot or --market\n")
        try:
            operating = config.operating
            MarketSnapshot(
                "validation",
                "validation",
                0.5,
                operating.bankroll,
                config.risk.market_exposure,
                config.risk.total_exposure,
            )
        except (TypeError, ValueError):
            parser.exit(2, "cycle failed: invalid operating configuration\n")
        total_exposure = config.risk.total_exposure
        book_state = None
        if args.journal is not None:
            from chrysopoeia.accounting import JournalError, open_session
            from chrysopoeia.events import drain

            try:
                book_state = open_session(
                    args.journal, operating.bankroll, operating.maximum_loss
                )
                if sink:
                    drain(args.journal, sink)
            except (ValueError, JournalError) as exc:
                parser.exit(2, f"cycle failed: {exc}\n")
            total_exposure += book_state.open_exposure
        try:
            if args.context is not None and len(args.context) > 2_000:
                raise ValueError
            draft_value = json.loads(args.draft) if args.draft is not None else None
            request = PaperCycleRequest(context=args.context, draft=draft_value)
            draft = request.draft.model_dump(exclude_none=True) if request.draft else None
        except (UnicodeError, json.JSONDecodeError, ValueError):
            parser.exit(2, "cycle failed: invalid context or draft\n")
        try:
            snapshot = (
                load_capture_snapshot(
                    args.snapshot,
                    config,
                    operating,
                    config.risk.market_exposure,
                    total_exposure,
                )
                if args.snapshot is not None
                else load_market_snapshot(
                    args.market,
                    operating.bankroll,
                    config.risk.market_exposure,
                    total_exposure,
                    include_no_book=True,
                    paper_fee_rate=config.venue.paper_fee_rate,
                    paper_fee_source=config.venue.paper_fee_source,
                )
                if args.market is not None
                else None
            )
        except (OSError, TypeError, ValueError):
            parser.exit(
                2,
                "cycle failed: invalid snapshot\n"
                if args.snapshot is not None
                else "cycle failed: invalid market\n",
            )
        evidence = None
        if args.journal is None:
            try:
                evidence = (
                    load_evidence_bundle(args.evidence, snapshot)
                    if args.evidence is not None
                    else None
                )
            except (OSError, TypeError, ValueError):
                parser.exit(2, "cycle failed: invalid evidence\n")
        try:
            from chrysopoeia.cycle_runner import run_paper_cycle

            if args.journal is None:
                result = asyncio.run(
                    run_paper_cycle(
                        config, snapshot, operating, evidence=evidence,
                        context=args.context, draft=draft,
                    )
                )
            else:
                from chrysopoeia.operations import run_journal_turn

                result = asyncio.run(
                    run_journal_turn(
                        args.journal,
                        config,
                        snapshot,
                        operating,
                        run=run_paper_cycle,
                        load_evidence=(
                            (lambda: load_evidence_bundle(args.evidence, snapshot))
                            if args.evidence is not None
                            else None
                        ),
                        context=args.context,
                        draft=draft,
                    )
                )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            from chrysopoeia.accounting import JournalError
            from chrysopoeia.operations import (
                InvalidTurnInputError,
                JournalWorkflowError,
            )

            if isinstance(exc, InvalidTurnInputError):
                parser.exit(2, "cycle failed: invalid evidence\n")
            if isinstance(exc, JournalWorkflowError):
                parser.exit(2, "cycle failed: journal workflow rejected the fill\n")
            if isinstance(exc, JournalError):
                parser.exit(2, f"cycle failed: {exc}\n")
            parser.exit(2, "cycle failed: model/workflow unavailable\n")
        content = (
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        if args.output is not None:
            try:
                _write_new(args.output, content)
            except (OSError, ValueError):
                parser.exit(2, "cycle failed: output unavailable\n")
        print(content.decode(), end="")
        return 0
    summary = _summary(config, args.command, label[:200])
    print(json.dumps(summary, sort_keys=True) if args.json else _human(summary))
    return 0
