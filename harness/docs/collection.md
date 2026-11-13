# Esports automated collection

Automated sessions forecast CS2 and Dota 2 match-winner markets only. Every
bundled profile sets `[venue] markets = "esports-match-winner"`. The Platform
profile runs automated paper trading (`[session] scored_only = false`,
operator-approved 2026-11-12): reviewer-approved plans that pass risk policy
produce paper fills, positions, and settled PnL in the journal. Other profiles
may stay scored-only (`run` accepts both); scored-only sessions never emit
plans or fills. BTC 5m automation is retired; older BTC journals and archived
events remain scoreable. Real-money execution remains prohibited.

Discovery reuses the bounded volume-ranked Gamma read (at most three 25-record
pages, 5 s and 256 KiB each) and keeps a market only when its event slug is a
match winner (`cs2-<team>-<team>-YYYY-MM-DD` or `dota2-...`, no map/game
suffix), its question starts with `Counter-Strike: ` or `Dota 2: `, and Gamma's
`gameStartTime` is at least 10 minutes away. Each cycle forecasts the first
eligible market not yet admitted in the journal; with none, the cycle idles until
the next interval. Coverage depends on esports appearing in the top 75 markets by
24-hour volume.

Scored-only, where configured, is enforced by deterministic policy, not the
prompt: a plan the reviewer approves and the risk policy would allow is recorded
as `policy_rejected` with reason `scored_only`. The `turn_outcome` (with its
probability) is journaled and published; no `trade_plan_ready` event, Harness
paper fill, or Consumer fill is produced. Paper-trading sessions emit
`trade_plan_ready` and journal fills under the same risk, fee, and cost caps.
`polymarket-eval` scores every decided turn regardless of status.

The Platform-owned raw archive stores published outcome events, not every
journal record or model failure. Keep the local journal for scoring, failure
coverage, and booked model costs. See
[Platform storage](../../platform/docs/deployment.md#event-archive).

## Explicitly start a bounded session

No collection starts automatically. Before running, obtain approval for cycle,
deadline, daily model-cost, and session cost limits. `configs/esports.toml`
enables grounded research with a 32768-token input ceiling, so one cycle reserves
up to about $1.43; selecting it is not approval to spend. Edit a local TOML copy
for different approved bounds; old setting flags are rejected. Set `JOURNAL` to a
new persistent local directory. From `harness/`, with ambient ADC:

```sh
GOOGLE_CLOUD_PROJECT=PROJECT_ID \
CHRYSOPOEIA_EVENT_SINK=pubsub:projects/PROJECT_ID/topics/chrysopoeia-events \
uv run chrysopoeia run --config configs/esports.toml \
  --journal "${JOURNAL:?choose a persistent local journal}" \
  --stop-file "$JOURNAL/stop"
```

Inspect settings without model or network calls using
`uv run chrysopoeia validate --config configs/esports.toml --json`. Use one
writer per journal. Delivery failures leave pending outbox events for a later
drain; inspect `outbox-pending --journal "$JOURNAL"` and never acknowledge an
event without confirmed delivery.

## Score

After matches resolve:

```sh
uv run chrysopoeia polymarket-eval --journal "$JOURNAL"
```

Report agent and same-time market Brier on paired samples, forecasts per
attempted cycle, failed/missing/late/pending markets, and booked model costs.
Failed turns may book conservative reservations rather than confirmed spend.
Small samples are not evidence of edge.
