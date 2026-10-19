import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from chrysopoeia.accounting import (
    JournalError,
    Position,
    admit_turn,
    cycle_turn_id,
    finish_turn,
    open_session,
    record_fill,
    replay,
    settle,
)
from chrysopoeia.configuration import load_harness_config
from chrysopoeia.cycle_runner import reserved_ceiling
from chrysopoeia.loop import LoopParams, StopFlag, run_loop
from chrysopoeia.polymarket import MarketCandidate, PolymarketError
from chrysopoeia.trading import (
    BookLevel,
    ExitPlan,
    MarketSnapshot,
    market_snapshot_identity,
)

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def candidate(market: str) -> MarketCandidate:
    return MarketCandidate(
        market,
        f"Market {market}?",
        (NOW + timedelta(days=1)).isoformat(),
        f"https://polymarket.com/event/market-{market}",
        market,
    )


def snapshot(market: str, exposure: float = 0) -> MarketSnapshot:
    value = MarketSnapshot(
        "pending",
        market,
        0.4,
        1_000,
        0,
        exposure,
        question=f"Market {market}?",
        resolution_rules="Resolves from the published outcome.",
        end_time=(NOW + timedelta(days=1)).isoformat(),
        captured_at=NOW.isoformat(),
        source_url=f"https://polymarket.com/event/market-{market}",
        yes_token_id=f"yes-{market}",
        asks=(BookLevel(0.4, 100),),
        fee_rate=0.02,
        fee_source="paper-assumption:flat-2pct-v1",
        book_captured_at=NOW.isoformat(),
    )
    from dataclasses import replace

    return replace(value, snapshot_id=market_snapshot_identity(value))


def abstained(cost: str = "0.01") -> dict[str, object]:
    return {
        "status": "abstained",
        "event": None,
        "fill": None,
        "actual_estimated_cost_usd": cost,
    }


class LoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_series_offset_sleeps_into_the_window_before_forecasting(self) -> None:
        current = NOW + timedelta(seconds=75)
        sleeps = []

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            nonlocal current
            current += timedelta(seconds=seconds)

        with (
            patch("chrysopoeia.loop.discover_markets", return_value=(candidate("1"),)) as discover,
            patch("chrysopoeia.loop.load_market_snapshot", return_value=snapshot("1")),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(return_value=abstained()),
            ),
        ):
            await run_loop(
                self.params(
                    series="btc-updown-5m",
                    series_offset_seconds=120,
                    interval_seconds=300,
                ),
                self.config,
                now=lambda: current,
                sleep=sleep,
            )

        self.assertEqual(sleeps, [45])
        self.assertEqual(discover.call_args.kwargs["series_offset_seconds"], 120)

    async def test_series_waits_for_next_boundary_without_retrying_failed_window(
        self,
    ) -> None:
        current = NOW + timedelta(seconds=75)
        captures = []

        def capture(*_: object, **__: object):
            captures.append(current)
            if len(captures) == 1:
                raise PolymarketError("unavailable")
            return snapshot("2")

        async def sleep(seconds: float) -> None:
            nonlocal current
            self.assertEqual(seconds, 225)
            current += timedelta(seconds=seconds)

        with (
            patch(
                "chrysopoeia.loop.discover_markets", return_value=(candidate("2"),)
            ) as discover,
            patch("chrysopoeia.loop.load_market_snapshot", side_effect=capture),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(return_value=abstained()),
            ),
        ):
            report, iterations = await run_loop(
                self.params(series="btc-updown-5m", interval_seconds=300),
                self.config,
                now=lambda: current,
                sleep=sleep,
            )

        self.assertEqual(
            captures, [NOW + timedelta(seconds=75), NOW + timedelta(seconds=300)]
        )
        self.assertEqual(report["cycles_run"], 1)
        self.assertEqual(iterations[0]["status"], "failed")
        self.assertEqual(discover.call_args.kwargs["series"], "btc-updown-5m")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.journal = Path(self.temporary.name)
        self.config = load_harness_config(ROOT / "chrysopoeia.toml")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def params(self, **changes: object) -> LoopParams:
        values = {
            "journal": self.journal,
            "bankroll": 1_000.0,
            "maximum_loss": 100.0,
            "target_win_rate": 0.6,
            "window_minutes": 10.0,
            "max_cycles": 1,
            "cost_budget": Decimal("10"),
            "interval_seconds": 0.0,
        }
        values.update(changes)
        return LoopParams(**values)

    async def run_session(self, params: LoopParams | None = None, **patches: object):
        discover = patches.get("discover", (candidate("1"),))
        capture = patches.get("capture", snapshot("1"))
        cycle = patches.get("cycle", abstained())
        with (
            patch("chrysopoeia.loop.discover_markets", return_value=discover),
            patch("chrysopoeia.loop.load_market_snapshot", return_value=capture),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(return_value=cycle),
            ),
        ):
            return await run_loop(
                params or self.params(),
                self.config,
                now=lambda: NOW,
                sleep=patches.get("sleep", AsyncMock()),
            )

    async def test_loop_stops_at_deadline(self) -> None:
        report, iterations = await self.run_session(self.params(window_minutes=1))
        resumed, _ = await run_loop(
            self.params(window_minutes=1),
            self.config,
            now=lambda: NOW + timedelta(minutes=1),
            sleep=AsyncMock(),
        )
        self.assertEqual(
            (report["stop_reason"], resumed["stop_reason"]), ("max_cycles", "deadline")
        )
        self.assertEqual(len(iterations), 1)

    async def test_loop_resume_keeps_window_and_refuses_mismatched_params(self) -> None:
        await self.run_session(self.params(window_minutes=1))
        resumed, _ = await run_loop(
            self.params(window_minutes=1),
            self.config,
            now=lambda: NOW + timedelta(seconds=30),
            sleep=AsyncMock(),
        )
        self.assertEqual(
            resumed["window_end"], (NOW + timedelta(minutes=1)).isoformat()
        )
        with self.assertRaises(JournalError):
            await run_loop(
                self.params(window_minutes=2),
                self.config,
                now=lambda: NOW + timedelta(seconds=30),
                sleep=AsyncMock(),
            )

    async def test_loop_stops_at_max_cycles(self) -> None:
        report, _ = await self.run_session()
        self.assertEqual(
            (report["stop_reason"], report["cycles_run"]), ("max_cycles", 1)
        )

    async def test_loop_stops_on_cost_budget(self) -> None:
        report, _ = await self.run_session(self.params(cost_budget=Decimal("0")))
        self.assertEqual(report["stop_reason"], "cost_budget")

    async def test_repeated_failed_turns_stop_on_cost_budget(self) -> None:
        ceiling = reserved_ceiling(self.config)
        flag = StopFlag()
        sleeps = 0

        async def stop_after_three_failures(_: float) -> None:
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                flag.stop()

        with (
            patch(
                "chrysopoeia.loop.discover_markets",
                return_value=tuple(candidate(str(index)) for index in range(1, 5)),
            ),
            patch(
                "chrysopoeia.loop.load_market_snapshot",
                side_effect=tuple(snapshot(str(index)) for index in range(1, 4)),
            ),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(side_effect=RuntimeError("model failed")),
            ) as cycle,
        ):
            report, _ = await run_loop(
                self.params(max_cycles=10, cost_budget=ceiling * 2, stop_flag=flag),
                self.config,
                now=lambda: NOW,
                sleep=stop_after_three_failures,
            )

        self.assertEqual(report["stop_reason"], "cost_budget")
        self.assertEqual(report["model_cost_usd"], float(ceiling * 2))
        self.assertEqual(cycle.await_count, 2)

    async def test_loop_stops_on_stop_file(self) -> None:
        stop = self.journal / "stop"
        stop.touch()
        report, _ = await self.run_session(self.params(stop_file=stop))
        self.assertEqual(report["stop_reason"], "stopped")

    async def test_loop_stops_on_signal_flag(self) -> None:
        flag = StopFlag()
        flag.stop()
        report, _ = await self.run_session(self.params(stop_flag=flag))
        self.assertEqual(report["stop_reason"], "stopped")

    async def test_loop_finishes_in_flight_turn_before_signal_stop(self) -> None:
        flag = StopFlag()

        async def finish_then_signal(*_: object, **__: object) -> dict[str, object]:
            flag.stop()
            return abstained()

        with (
            patch("chrysopoeia.loop.discover_markets", return_value=(candidate("1"),)),
            patch("chrysopoeia.loop.load_market_snapshot", return_value=snapshot("1")),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(side_effect=finish_then_signal),
            ),
        ):
            report, _ = await run_loop(
                self.params(stop_flag=flag, max_cycles=2),
                self.config,
                now=lambda: NOW,
                sleep=AsyncMock(),
            )
        self.assertEqual((report["stop_reason"], report["cycles_run"]), ("stopped", 1))

    async def test_loop_stops_on_loss_halt(self) -> None:
        open_session(
            self.journal,
            1_000,
            10,
            target_win_rate=0.6,
            window_end=NOW + timedelta(minutes=10),
            window_minutes=10,
        )
        admit_turn(self.journal, "old", "snap", "9")
        record_fill(
            self.journal,
            Position("9", "snap", NOW.isoformat(), 0.4, 10, 25, 0.2, 10.2, ExitPlan(0.1, -0.2, "2026-09-30T13:00:00+00:00")),
            "old",
        )
        finish_turn(self.journal, "old", "filled")

        def settle_loss(journal: Path, *_: object, **__: object):
            from chrysopoeia.accounting import check_halt

            settle(journal, replay(journal), "9", "resolved_no")
            check_halt(journal, replay(journal))
            return []

        with patch("chrysopoeia.loop.settle_positions", side_effect=settle_loss):
            report, _ = await run_loop(
                self.params(maximum_loss=10, max_cycles=2),
                self.config,
                now=lambda: NOW,
                sleep=AsyncMock(),
            )
        self.assertEqual(report["stop_reason"], "halted")

    async def test_win_rate_report_is_unavailable_without_settlements(self) -> None:
        report, _ = await self.run_session()
        self.assertIsNone(report["win_rate"])
        self.assertIsNone(report["target_met"])

    async def test_win_rate_report_counts_winning_settlements(self) -> None:
        end = NOW + timedelta(minutes=10)
        open_session(
            self.journal,
            1_000,
            100,
            target_win_rate=0.6,
            window_end=end,
            window_minutes=10,
        )
        admit_turn(self.journal, "old", "snap", "9")
        record_fill(
            self.journal,
            Position("9", "snap", NOW.isoformat(), 0.4, 10, 25, 0.2, 10.2, ExitPlan(0.1, -0.2, "2026-09-30T13:00:00+00:00")),
            "old",
        )
        finish_turn(self.journal, "old", "filled")
        settle(self.journal, replay(self.journal), "9", "resolved_yes")
        report, _ = await self.run_session()
        self.assertEqual(
            (
                report["settled_trades"],
                report["winning_trades"],
                report["win_rate"],
                report["target_met"],
            ),
            (1, 1, 1.0, True),
        )

    async def test_loop_skips_open_and_already_admitted_markets(self) -> None:
        open_session(
            self.journal,
            1_000,
            100,
            target_win_rate=0.6,
            window_end=NOW + timedelta(minutes=10),
            window_minutes=10,
        )
        admit_turn(self.journal, "old", "snap", "1")
        finish_turn(self.journal, "old", "abstained")
        with (
            patch(
                "chrysopoeia.loop.discover_markets",
                return_value=(candidate("1"), candidate("2")),
            ),
            patch(
                "chrysopoeia.loop.load_market_snapshot", return_value=snapshot("2")
            ) as capture,
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(return_value=abstained()),
            ),
        ):
            await run_loop(
                self.params(max_cycles=2),
                self.config,
                now=lambda: NOW,
                sleep=AsyncMock(),
            )
        self.assertEqual(capture.call_args.args[0], "2")

    async def test_venue_error_is_recorded_and_loop_continues(self) -> None:
        calls = 0

        def discover(**_: object):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PolymarketError("down")
            return (candidate("1"),)

        async def sleep(_: float) -> None:
            if calls > 1:
                return

        with (
            patch("chrysopoeia.loop.discover_markets", side_effect=discover),
            patch("chrysopoeia.loop.load_market_snapshot", return_value=snapshot("1")),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(return_value=abstained()),
            ),
        ):
            report, iterations = await run_loop(
                self.params(), self.config, now=lambda: NOW, sleep=sleep
            )
        self.assertEqual(report["cycles_run"], 1)
        self.assertEqual(iterations[0]["errors"], ["discovery unavailable"])

    async def test_idle_iteration_sleeps_for_interval(self) -> None:
        flag = StopFlag()

        async def stop_after_sleep(_: float) -> None:
            flag.stop()

        sleep = AsyncMock(side_effect=stop_after_sleep)
        report, iterations = await self.run_session(
            self.params(stop_flag=flag, interval_seconds=7), discover=(), sleep=sleep
        )

        self.assertEqual(report["stop_reason"], "stopped")
        self.assertEqual(iterations[0]["status"], "idle")
        sleep.assert_awaited_once_with(7)

    async def test_loop_does_not_double_fill_across_iterations(self) -> None:
        fill = {
            "price": 0.4,
            "amount": 4.0,
            "shares": 10.0,
            "fee": 0.08,
            "total_cost": 4.08,
            "levels_consumed": 1,
            "exit_plan": {
                "take_profit_roi": 0.1,
                "stop_loss_roi": -0.2,
                "exit_by": "2026-10-01T00:00:00+00:00",
                "hold_to_resolution": False,
            },
        }
        async def filled_cycle(
            _config: object, current: MarketSnapshot, _operating: object, **_: object
        ) -> dict[str, object]:
            event = {
                "schema_version": 1,
                "record_type": "trade_plan_ready",
                "event_id": cycle_turn_id(current.snapshot_id, current.market_id),
                "created_at": NOW.isoformat(),
                "market_id": current.market_id,
                "snapshot_id": current.snapshot_id,
                "instrument_id": current.yes_token_id,
                "outcome": "YES",
                "probability": 0.46,
                "stake": 4.0,
                "max_entry_price": 0.41,
                "exit_plan": fill["exit_plan"],
                "reviewer_approved": True,
                "reviewer_citations": ["market_snapshot"],
                "policy_references": ["hard-policy-v1"],
                "evidence_references": ["market_snapshot"],
                "expires_at": (NOW + timedelta(days=1)).isoformat(),
                "market_end": (NOW + timedelta(days=1)).isoformat(),
            }
            from chrysopoeia.paper_cycle import build_turn_outcome

            outcome = build_turn_outcome(
                proposal={
                    "snapshot_id": current.snapshot_id, "market_id": current.market_id,
                    "action": "trade", "probability": 0.46, "amount": 4.0,
                    "max_entry_price": 0.41, "exit_plan": fill["exit_plan"],
                    "citations": ["market_snapshot"], "rationale": "Evidence supports a trade.",
                },
                review={
                    "snapshot_id": current.snapshot_id, "market_id": current.market_id,
                    "approved": True, "reason": "supported", "citations": ["market_snapshot"],
                },
                policy={"allowed": True, "reason": "approved by review and deterministic risk policy"},
                status="plan_ready", reason="approved by review and deterministic risk policy",
                created_at=current.captured_at, trade_plan_event_id=event["event_id"],
                model_cost_usd="0.01",
            )
            return {**abstained(), "status": "filled", "event": event, "fill": fill, "outcome_event": outcome}
        with (
            patch(
                "chrysopoeia.loop.discover_markets",
                return_value=(candidate("1"), candidate("2")),
            ),
            patch(
                "chrysopoeia.loop.load_market_snapshot",
                side_effect=(snapshot("1"), snapshot("2")),
            ),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(side_effect=filled_cycle),
            ),
            patch("chrysopoeia.loop.evaluate_exits", return_value=[]),
            patch.dict(
                os.environ,
                {"CHRYSOPOEIA_EVENT_SINK": "http://127.0.0.1:8080/push"},
            ),
            patch("chrysopoeia.events.publish"),
        ):
            report, _ = await run_loop(
                self.params(max_cycles=2),
                self.config,
                now=lambda: NOW,
                sleep=AsyncMock(),
            )
        self.assertEqual(report["trades_filled"], 2)
        positions = replay(self.journal).positions
        self.assertEqual(set(positions), {"1", "2"})
        self.assertEqual(
            positions["1"].trade_plan.event_id,
            cycle_turn_id(snapshot("1").snapshot_id, "1"),
        )
        records = [
            json.loads(line)
            for line in self.journal.joinpath("chrysopoeia.jsonl").read_text().splitlines()
        ]
        for event_id in (cycle_turn_id(snapshot("1").snapshot_id, "1"), cycle_turn_id(snapshot("2").snapshot_id, "2")):
            enqueue = next(i for i, record in enumerate(records) if record.get("event", {}).get("event_id") == event_id)
            fill_record = next(i for i, record in enumerate(records) if record.get("turn_id") == event_id and record["record_type"] == "fill_recorded")
            self.assertLess(enqueue, fill_record)

    async def test_loop_evaluates_open_brackets_before_discovering_a_new_market(self) -> None:
        open_session(
            self.journal,
            1_000,
            100,
            target_win_rate=0.6,
            window_end=NOW + timedelta(minutes=10),
            window_minutes=10,
        )
        admit_turn(self.journal, "old", "snap", "9")
        record_fill(
            self.journal,
            Position("9", "snap", NOW.isoformat(), 0.4, 10, 25, 0.2, 10.2, ExitPlan(0.1, -0.2, "2026-09-30T13:00:00+00:00")),
            "old",
        )
        finish_turn(self.journal, "old", "filled")
        with (
            patch("chrysopoeia.loop.settle_positions", return_value=[]),
            patch("chrysopoeia.loop.evaluate_exits", return_value=[]) as exits,
            patch("chrysopoeia.loop.discover_markets", return_value=(candidate("1"),)),
            patch("chrysopoeia.loop.load_market_snapshot", return_value=snapshot("1")),
            patch("chrysopoeia.cycle_runner.run_paper_cycle", AsyncMock(return_value=abstained())),
        ):
            await run_loop(
                self.params(max_cycles=2),
                self.config,
                now=lambda: NOW,
                sleep=AsyncMock(),
            )

        exits.assert_called_once()
        self.assertEqual(exits.call_args.args[1], ("9",))

    async def test_per_turn_failure_is_finalized_and_does_not_crash_loop(self) -> None:
        with (
            patch("chrysopoeia.loop.discover_markets", return_value=(candidate("1"),)),
            patch("chrysopoeia.loop.load_market_snapshot", return_value=snapshot("1")),
            patch(
                "chrysopoeia.cycle_runner.run_paper_cycle",
                AsyncMock(side_effect=RuntimeError("model failed")),
            ),
        ):
            report, iterations = await run_loop(
                self.params(), self.config, now=lambda: NOW, sleep=AsyncMock()
            )

        self.assertEqual(report["stop_reason"], "max_cycles")
        self.assertEqual(set(replay(self.journal).finished_turns.values()), {"failed"})
        self.assertEqual(iterations[0]["status"], "failed")
