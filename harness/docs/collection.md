# Local BTC 5m collection

`run --config configs/btc5m.toml` selects the current UTC five-minute window from
the clock. BTC 5m Up/Down is the only automated market during development:
`[venue].series` is required and the volume-ranked fallback is unreachable from
the CLI. The run starts immediately, then waits for each next five-minute
boundary (not 300 seconds after model completion). The profile sets
`[venue].series = "btc-updown-5m"` and
`[session].interval_seconds = 300`; incompatible cadence fails config validation.
Missing captures wait until the next boundary; admitted markets, including
failed turns, are not retried.
Slow cycles can skip windows. `[session].max_cycles` bounds admitted turns, not guaranteed
forecasts: discovery/capture failures do not count, but the deadline still applies.
BTC 5m is the only automated market in development; there is no non-series run.

The Platform-owned raw archive is deployed before any forecasting session.
It stores published outcome/plan events, not every journal record, model failure,
paper fill, mark, or settlement. Keep the local journal for scoring, failure
coverage, booked model costs, and paper accounting. Never treat archived plans
as fills. See [Platform storage](../../platform/docs/deployment.md#event-archive).

## Explicitly start a bounded session

No collection starts automatically. Before running, obtain approval for cycle,
deadline, loss, daily model-cost, and session cost limits. The bundled BTC profile
sets 20 cycles, a 110-minute window, $15 session/daily model ceilings, and a
$100 paper loss limit on $1,000 paper capital. Selecting it is not approval to
spend. Edit a local TOML copy for different approved bounds; old setting flags
are rejected rather than override the file. Set `JOURNAL` to a new persistent
local directory.
From `harness/`, with ambient ADC:

```sh
GOOGLE_CLOUD_PROJECT=PROJECT_ID \
CHRYSOPOEIA_EVENT_SINK=pubsub:projects/PROJECT_ID/topics/chrysopoeia-events \
uv run chrysopoeia run --config configs/btc5m.toml \
  --journal "${JOURNAL:?choose a persistent local journal}" \
  --stop-file "$JOURNAL/stop"
```

The session uses the checked-in model configuration and local paper simulator.
Inspect all settings without model/network calls using
`uv run chrysopoeia validate --config configs/btc5m.toml --json`.
This does not run a Cloud Run job or deploy a consumer. Use one writer per local
journal. The publisher needs topic-scoped Pub/Sub publishing permission; it
does not need BigQuery write access. Delivery failures leave pending outbox
events for a later drain, so inspect `outbox-pending --journal "$JOURNAL"`.
Do not manually acknowledge events unless delivery has been confirmed.

## Score and account separately

After resolution, score the journal; a concrete window URL supplies the series
prefix, not a historical forecast input:

```sh
uv run chrysopoeia polymarket-eval --journal "$JOURNAL" \
  --series-url https://polymarket.com/event/btc-updown-5m-1792306500
uv run chrysopoeia book --journal "$JOURNAL"
```

Report agent and same-time market Brier on paired samples, forecasts divided by
attempted windows, proposed-trade coverage, actual paper fills, failed/missing/
late/pending windows, booked model costs, and paper P&L separately. The evaluator's
`trade_coverage` counts proposals, not fills. Failed turns may book conservative
reservations rather than confirmed provider spend. The final open paper position
may need `settle --journal "$JOURNAL" --market <id>` once Gamma resolves it.
BigQuery scoring, historical backfill, and scheduled collection are not included.
