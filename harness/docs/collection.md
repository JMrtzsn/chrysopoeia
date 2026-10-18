# Local BTC 5m collection

`run --series btc-updown-5m` selects the current UTC five-minute window from
the clock, not the broad volume-ranked discovery list. It starts immediately,
then waits for each next five-minute boundary (not 300 seconds after model
completion). Other intervals are rejected. Missing captures wait until the
next boundary; admitted markets, including failed turns, are not retried.
Slow cycles can skip windows. `--max-cycles` bounds admitted turns, not guaranteed
forecasts: discovery/capture failures do not count, but the deadline still applies.
The default non-series loop is unchanged.

The Platform-owned raw archive is deployed before any forecasting session.
It stores published outcome/plan events, not every journal record, model failure,
paper fill, mark, or settlement. Keep the local journal for scoring, failure
coverage, booked model costs, and paper accounting. Never treat archived plans
as fills. See [Platform storage](../../platform/docs/deployment.md#event-archive).

## Explicitly start a bounded session

No collection starts automatically. Before running, obtain approval for cycle,
deadline, loss, daily model-cost, and session cost limits. Set `JOURNAL` to a
new persistent local directory, and the other variables to approved values.
From `harness/`, with ambient ADC:

```sh
GOOGLE_CLOUD_PROJECT=PROJECT_ID \
CHRYSOPOEIA_EVENT_SINK=pubsub:projects/PROJECT_ID/topics/chrysopoeia-events \
uv run chrysopoeia run --series btc-updown-5m \
  --journal "${JOURNAL:?choose a persistent local journal}" \
  --max-cycles "${MAX_CYCLES:?set approved cycle limit}" \
  --window-minutes "${WINDOW_MINUTES:?set approved deadline}" \
  --cost-budget "${COST_BUDGET:?set approved session cost ceiling}" \
  --daily-cloud-cost-budget "${DAILY_COST_BUDGET:?set approved daily ceiling}" \
  --maximum-loss "${MAXIMUM_LOSS:?set approved paper loss ceiling}" \
  --stop-file "$JOURNAL/stop"
```

The session uses the checked-in model configuration and local paper simulator.
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
