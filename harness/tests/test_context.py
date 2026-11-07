import unittest

from chrysopoeia.context import ContextIdentity, context_identity_for_source_url

BTC_5M = ContextIdentity(
    "polymarket:series:btc-updown-5m", "crypto.btcusd.5m.updown", 1
)


class ContextIdentityTests(unittest.TestCase):
    def test_source_url_routes_only_canonical_btc_series_markets(self) -> None:
        self.assertEqual(
            context_identity_for_source_url(
                "https://polymarket.com/event/btc-updown-5m-1792600000"
            ),
            BTC_5M,
        )
        football = context_identity_for_source_url(
            "https://polymarket.com/event/arsenal-vs-chelsea"
        )
        self.assertIsNotNone(football)
        assert football is not None
        self.assertEqual(football.scope_key, "polymarket:event:arsenal-vs-chelsea")
        crypto_series = context_identity_for_source_url(
            "https://polymarket.com/event/eth-updown-5m-1792600000"
        )
        self.assertIsNotNone(crypto_series)
        assert crypto_series is not None
        self.assertEqual(crypto_series.scope_key, "polymarket:series:eth-updown-5m")
