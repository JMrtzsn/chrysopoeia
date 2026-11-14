# Insight observer

Independent FastAPI service for read-only insight over the raw BigQuery event
archive. `GET /v1/insights` runs a bounded query at read time; it does not keep a
projection database of its own, subscribe to events, or write anywhere. `GET
/health` does not query the archive.

Each result groups `turn_outcome` v3/v4 decisions by full context identity
(`scope_key`, profile ID/version/manifest hash), joins archived Consumer outcomes
by trade-plan event ID, and reports:

- decisions, accepted plans, abstentions, Harness/Consumer rejections, fills, and
  closed/settled trades;
- win rate and realized paper P&L for completed trades;
- actual estimated model/research cost recorded on decided Harness turns and,
  only for v4-only groups, the sum of their reservation ceilings (including the
  configured research allowance);
- completed trades remaining before the 20-trade profile gate opens.

Delivery duplicates are removed by `(record_type, event_id)`. Queries look back
90 days, filter the required `publish_time` partition, cap billing at 100 MiB,
time out after 20 seconds, and return at most 100 contexts. The response sets
`truncated` when more contexts exist. Synthetic archive-verification records and
unversioned/context-free legacy outcomes do not enter these aggregates.

The archive is not authoritative. Only published events are visible: local runs
without `CHRYSOPOEIA_EVENT_SINK`, Harness in-process fills/settlements, and failed
turns without a `turn_outcome` are absent. V3-only and mixed v3/v4 groups return
`reserved_model_cost_usd: null`; the observer never reports a partial v4
reservation sum beside actual costs from all versions. Actual cost keeps its
existing meaning and is an estimate, not a provider bill.

## Journey health

`GET /v1/health` answers "is the trading loop producing outcomes?" with two
bounded reads: a lookup of lifecycle state in the platform-maintained
`open_positions` projection (same dataset as the archive; the projection is a
scheduled-query rebuild of `raw_events` every 15 minutes, never authoritative),
and a 24-hour archive scan that extends back to the last completed trade for
context revisions. It returns `healthy`/`degraded` plus `reasons`, and degrades
when:

- inside the scheduled window (13:40–23:00 UTC; executions run hourly at :40 of
  hours 13–22, so overnight silence is by design) no `turn_outcome` exists within
  the last four hours;
- a filled position has no terminal (`closed`/`settled`) Consumer outcome more
  than 24 hours after its plan's `market_end` (stuck settlement);
- `OBSERVER_DAILY_COST_BUDGET_USD` is set and the 24-hour actual model cost
  exceeds it (unset means the budget check is skipped).

Metrics — last decision/completion timestamps, 24-hour decisions, abstention
rate, fills, wins, realized P&L, model cost, maximum settlement lag in hours, and
context revisions since the last completed trade — are informational; they do
not change the status. Like `/v1/insights`, this route is read-only, byte-capped,
partition-bounded, and never writes or subscribes.

## Run locally

Requires Python 3.10+, `uv`, ambient Google credentials with BigQuery query and
archive read access, and the fully qualified archive table:

```sh
uv sync --all-groups
OBSERVER_ARCHIVE_TABLE=project.dataset.raw_events \
OBSERVER_BIGQUERY_LOCATION=us-central1 \
  uv run uvicorn observer.app:app --host 127.0.0.1 --port 8080 --workers 1
```

Then request `http://127.0.0.1:8080/v1/insights`. Local binding provides no
authentication.

## Container and deployment

`./build.sh` builds the wheel, exports the frozen runtime requirements, builds
`chrysopoeia-observer:local` for `linux/amd64`, and import-checks it with
networking disabled. It never pushes; publication and the digest pin are a
separate approved operation. Platform deploys the pinned digest as a private
Cloud Run service with a dedicated identity that can only run BigQuery jobs and
read the archive dataset; only the configured `observer_invoker_member` may
invoke it. The service receives `GOOGLE_CLOUD_PROJECT`,
`OBSERVER_ARCHIVE_TABLE`, and `OBSERVER_BIGQUERY_LOCATION`. See
`../platform/docs/deployment.md`.

## Offline checks

```sh
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ty check .
```

Tests inject fake BigQuery clients and make no network calls.
