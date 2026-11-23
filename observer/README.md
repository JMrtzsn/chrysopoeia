# Insight observer

Independent, read-only FastAPI service over the raw BigQuery event archive. It
queries at read time and keeps no projection store, subscribes to nothing, and
writes nowhere. `GET /health` does not query the archive.

## `GET /v1/insights`

Groups `turn_outcome` v3/v4 decisions by full context identity (`scope_key`,
profile ID/version/manifest hash), joins archived Consumer outcomes by
trade-plan event ID, and reports:

- decisions, accepted plans, abstentions, Harness/Consumer rejections, fills,
  and closed/settled trades;
- win rate and realized paper P&L for completed trades;
- actual estimated model/research cost on decided turns, and for v4-only groups
  the sum of reservation ceilings (including research allowance); v3-only and
  mixed groups return `reserved_model_cost_usd: null`;
- completed trades remaining before the 20-trade profile gate.

Bounds: dedupe by `(record_type, event_id)`, 90-day lookback on the required
`publish_time` partition, 100 MiB billing cap, 20-second timeout, at most 100
contexts (`truncated` when more exist). Synthetic verification records and
unversioned/context-free outcomes are excluded.

The archive is not authoritative and only holds published events: local runs
without `CHRYSOPOEIA_EVENT_SINK`, Harness in-process fills/settlements, and
failed turns are absent. Cost is an estimate, not a provider bill.

## `GET /v1/health`

Answers "is the trading loop producing outcomes?" with two bounded reads: the
platform-maintained `open_positions` projection (rebuilt from `raw_events` every
15 minutes by scheduled query; not authoritative) and a 24-hour archive scan
extended back to the last completed trade. Returns `healthy`/`degraded` with
`reasons`. Degraded when:

- no `turn_outcome` in the last four hours during the scheduled window
  (13:40–23:00 UTC; runs at :40 of hours 13–22, so overnight silence is
  expected);
- a filled position has no `closed`/`settled` Consumer outcome 24 hours after
  its plan's `market_end`;
- `OBSERVER_DAILY_COST_BUDGET_USD` is set and 24-hour actual model cost exceeds
  it.

Informational metrics (no effect on status): last decision/completion times,
24-hour decisions, abstention rate, fills, wins, realized P&L, model cost,
maximum settlement lag in hours, and context revisions since the last completed
trade. Same read-only, byte-capped, partition-bounded limits as insights.

## Run locally

Needs Python 3.10+, `uv`, and ambient Google credentials with BigQuery query and
archive read access:

```sh
uv sync --all-groups
OBSERVER_ARCHIVE_TABLE=project.dataset.raw_events \
OBSERVER_BIGQUERY_LOCATION=us-central1 \
  uv run uvicorn observer.app:app --host 127.0.0.1 --port 8080 --workers 1
```

Then open `http://127.0.0.1:8080/v1/insights` (no local authentication).

## Container and deployment

`./build.sh` builds the wheel, exports frozen requirements, builds
`chrysopoeia-observer:local` for `linux/amd64`, and import-checks it offline. It
never pushes; publishing and digest pinning are separately approved. Platform
deploys the pinned digest as a private Cloud Run service whose identity can only
run BigQuery jobs and read the archive dataset, invocable only by
`observer_invoker_member`, with `GOOGLE_CLOUD_PROJECT`,
`OBSERVER_ARCHIVE_TABLE`, and `OBSERVER_BIGQUERY_LOCATION`. See
[`../platform/docs/deployment.md`](../platform/docs/deployment.md).

## Offline checks

```sh
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ty check .
```

Tests use fake BigQuery clients and make no network calls.
