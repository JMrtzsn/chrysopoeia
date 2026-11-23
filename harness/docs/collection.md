# Esports automated collection

- Automated sessions forecast CS2 and Dota 2 match winners only; every bundled
  profile sets `[venue] markets = "esports-match-winner"`.
- The Platform profile paper-trades (`[session] scored_only = false`):
  approved plans that pass risk policy produce paper fills, positions, and
  settled P&L. Other profiles may stay scored-only and never emit plans or
  fills.
- BTC 5m automation is retired; old BTC journals and archived events remain
  scoreable. Real-money execution is prohibited.

## Discovery

Reuses the volume-ranked Gamma read (at most three 25-record pages, 5 s and
256 KiB each). A market qualifies when:

- its event slug is a match winner (`cs2-<team>-<team>-YYYY-MM-DD` or
  `dota2-...`, no map/game suffix);
- its question starts with `Counter-Strike: ` or `Dota 2: `;
- Gamma's `gameStartTime` is at least 10 minutes away.

Each cycle forecasts the first eligible market not yet admitted; otherwise it
idles until the next interval. Coverage depends on esports reaching the top 75
markets by 24-hour volume.

## Scored-only

Enforced by policy, not the prompt: an approved, policy-allowed plan is recorded
as `policy_rejected` with reason `scored_only`. The `turn_outcome` (with
probability) is journaled and published; no `trade_plan_ready`, Harness fill, or
Consumer fill follows. `polymarket-eval` scores every decided turn.

The raw archive holds published outcome events only, not every journal record
or model failure. Keep the local journal for scoring, failures, and booked
costs. See [Platform storage](../../platform/docs/deployment.md#event-archive).

## Run a bounded session

Nothing starts automatically. Get approval for cycle, deadline, daily
model-cost, and session cost limits first. `configs/esports.toml` enables
grounded research with a 32768-token input ceiling, so one cycle reserves up to
about $1.43; selecting it is not approval to spend. For other approved bounds,
edit a local TOML copy (setting flags are rejected). From `harness/`, with
ambient ADC and a new persistent `JOURNAL` directory:

```sh
GOOGLE_CLOUD_PROJECT=PROJECT_ID \
CHRYSOPOEIA_EVENT_SINK=pubsub:projects/PROJECT_ID/topics/chrysopoeia-events \
uv run chrysopoeia run --config configs/esports.toml \
  --journal "${JOURNAL:?choose a persistent local journal}" \
  --stop-file "$JOURNAL/stop"
```

- Check settings offline: `uv run chrysopoeia validate --config configs/esports.toml --json`.
- Use one writer per journal.
- Failed deliveries stay pending for a later drain; inspect with
  `outbox-pending --journal "$JOURNAL"` and never acknowledge an unconfirmed
  event.

## Score

After matches resolve:

```sh
uv run chrysopoeia polymarket-eval --journal "$JOURNAL"
```

Report agent and same-time market Brier on paired samples, forecasts per
attempted cycle, failed/missing/late/pending markets, and booked model costs.
Failed turns may book conservative reservations rather than confirmed spend.
Small samples are not evidence of edge.
