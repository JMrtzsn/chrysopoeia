import unittest

from chrysopoeia.context import (
    context_identity_for_series,
    context_identity_for_source_url,
)


class ContextIdentityTests(unittest.TestCase):
    def test_btc_five_minute_series_has_a_stable_profile_identity(self) -> None:
        context = context_identity_for_series("btc-updown-5m")

        self.assertEqual(context.scope_key, "polymarket:series:btc-updown-5m")
        self.assertEqual(context.profile_id, "crypto.btcusd.5m.updown")
        self.assertEqual(context.profile_version, 1)

    def test_unsupported_series_has_no_context_identity(self) -> None:
        with self.assertRaises(ValueError):
            context_identity_for_series("football")

    def test_source_url_routes_only_canonical_btc_series_markets(self) -> None:
        self.assertEqual(
            context_identity_for_source_url(
                "https://polymarket.com/event/btc-updown-5m-1792600000"
            ),
            context_identity_for_series("btc-updown-5m"),
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
