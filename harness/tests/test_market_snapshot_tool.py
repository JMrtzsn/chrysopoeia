import math
import inspect
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from chrysopoeia.agent import capture_market_snapshot, reviewer_agent, root_agent, trader_agent
from chrysopoeia.polymarket import PolymarketError
from chrysopoeia.trading import MarketSnapshot, OperatingConfig


class MarketSnapshotToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.configuration = asdict(OperatingConfig(bankroll=1_000))

    def test_capture_uses_authoritative_state_and_stores_small_snapshot(self) -> None:
        state = {
            "operating_config": self.configuration.copy(),
            "portfolio_exposure": {"market_exposure": 4, "total_exposure": 20},
        }
        context = SimpleNamespace(state=state)
        calls: list[tuple[object, ...]] = []

        def load(market: str, bankroll: float, market_exposure: float, total_exposure: float, **fee: object) -> MarketSnapshot:
            calls.append((market, bankroll, market_exposure, total_exposure))
            self.assertEqual(fee, {"paper_fee_rate": 0.02, "paper_fee_source": "paper-assumption:flat-2pct-v1"})
            return MarketSnapshot("snapshot-1", "12345", 0.42, bankroll, market_exposure, total_exposure)

        with patch("chrysopoeia.agent.load_market_snapshot", load):
            result = capture_market_snapshot("12345", context)

        expected = asdict(MarketSnapshot("snapshot-1", "12345", 0.42, 1_000, 4, 20))
        self.assertEqual(calls, [("12345", 1_000, 4, 20)])
        self.assertEqual(result, expected)
        self.assertEqual(state["market_snapshot"], expected)
        self.assertEqual(state["operating_config"], self.configuration)

    def test_missing_exposure_state_is_explicit_first_cycle_zero(self) -> None:
        context = SimpleNamespace(state={"operating_config": self.configuration.copy()})

        def load(market: str, bankroll: float, market_exposure: float, total_exposure: float, **_: object) -> MarketSnapshot:
            self.assertEqual((market_exposure, total_exposure), (0, 0))
            return MarketSnapshot("snapshot-1", "12345", 0.42, bankroll, market_exposure, total_exposure)

        with patch("chrysopoeia.agent.load_market_snapshot", load):
            capture_market_snapshot("12345", context)

    def test_invalid_state_fails_before_adapter_call(self) -> None:
        invalid_states = (
            {},
            {"operating_config": "invalid"},
            {"operating_config": {**self.configuration, "bankroll": True}},
            {"operating_config": self.configuration, "portfolio_exposure": None},
            {"operating_config": self.configuration, "portfolio_exposure": "invalid"},
            {"operating_config": self.configuration, "portfolio_exposure": {"market_exposure": math.nan, "total_exposure": 0}},
            {"operating_config": self.configuration, "portfolio_exposure": {"market_exposure": 2, "total_exposure": 1}},
        )
        for state in invalid_states:
            with self.subTest(state=state), patch("chrysopoeia.agent.load_market_snapshot") as load:
                with self.assertRaises(ValueError):
                    capture_market_snapshot("12345", SimpleNamespace(state=state))
                load.assert_not_called()

    def test_adapter_validation_is_preserved_and_unknown_failures_are_sanitized(self) -> None:
        context = SimpleNamespace(state={"operating_config": self.configuration.copy()})
        with patch("chrysopoeia.agent.load_market_snapshot", side_effect=PolymarketError("safe market validation")):
            with self.assertRaisesRegex(PolymarketError, "safe market validation"):
                capture_market_snapshot("bad-market", context)

        secret = "secret response body"
        with patch("chrysopoeia.agent.load_market_snapshot", side_effect=RuntimeError(secret)):
            with self.assertRaises(ValueError) as raised:
                capture_market_snapshot("12345", context)
        self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_only_root_agent_has_snapshot_capture_tool(self) -> None:
        self.assertTrue(any("capture_market_snapshot" in str(tool) for tool in root_agent.tools))
        self.assertEqual(set(inspect.signature(capture_market_snapshot).parameters), {"market", "tool_context"})
        for agent in (trader_agent, reviewer_agent):
            tools = " ".join(str(tool).lower() for tool in agent.tools)
            self.assertNotIn("capture_market_snapshot", tools)
            self.assertNotIn("check_risk", tools)
            self.assertNotIn("paper_execute", tools)


if __name__ == "__main__":
    unittest.main()
