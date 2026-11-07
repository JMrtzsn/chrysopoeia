# Observer roadmap

The observer is an independent, read-only work unit. Harness and Consumer own
their events and journals; Platform owns archive infrastructure, IAM, and any
future deployment. The BigQuery archive is an analytics copy, never a ledger.

## Complete

- **Insight service v1** (operator direction 2026-10-28): pull-based,
  profile-scoped decision/lifecycle/cost aggregates and the 20-completed-trade
  campaign gate. No subscription, alerting, projection database, execution
  authority, Harness command, or event-schema change. Eight offline tests, Ruff,
  ty, and the wheel build pass.
- **In-process archive check** (2026-10-29): one operator-approved local
  `GET /v1/insights` through FastAPI TestClient queried
  `PROJECT_ID.chrysopoeia_events_local.raw_events` using ambient ADC.
  This established the real BigQuery boundary, but not Uvicorn or TCP serving.
- **Full local serving check** (2026-10-29): with `GOOGLE_CLOUD_PROJECT` set to
  `PROJECT_ID`, `OBSERVER_BIGQUERY_LOCATION=us-central1`, and the archive
  table above, one loopback worker was started with
  `.venv/bin/uvicorn observer.app:app --host 127.0.0.1 --port 8080 --workers 1`
  from a `uv run python` bounded-check process.
  After log-confirmed startup in 1.028 seconds, exactly two TCP requests were
  made: `curl --max-time 5 --max-filesize 1048576 ... /healthz` returned HTTP
  200 and exactly `{"status":"ok"}`; then
  `curl --max-time 60 --max-filesize 1048576 ... /v1/insights` returned HTTP 200
  and 813 bytes of valid v1 insight JSON. Total live time was 7.908 seconds.
  Insights caused exactly one read-only, 90-day/partition-bounded BigQuery query
  with the existing 100 MiB maximum billed and 20-second query and result
  timeouts. The response had one untruncated context and no raw payload or
  Pub/Sub attributes. Its known BTC profile had 54 decisions, 6 accepted plans,
  47 abstentions, 1 Harness rejection, 3 Consumer rejections, 2 fills, 2
  completed trades, 1 win, -4.644444444444445 realized paper P&L, and
  3.3113437499999994 recorded actual estimated model/research cost. Win rate was
  0.5, the gate remained closed with 18 of 20 trades remaining, and reserved
  model cost was null. All counts, context bounds, win-rate consistency, and
  campaign arithmetic were checked. Estimated query cost was under $0.001;
  actual billing remains unknown. Uvicorn received SIGTERM and exited, and all
  response and log captures were removed. No retry or corroborating query ran.
  No cloud writes, models, deployments, or resources were used. This did not
  test Cloud Run, any deployed service, or a dedicated read-only observer
  identity; it used ambient operator ADC.
- **Reserved model cost** (coordinated operator approval 2026-10-30): consume
  Harness `turn_outcome` v4 while retaining v3 counts and actual costs. Sum
  reservations only for v4-only profile/context groups; v3-only and mixed
  groups return `null`. Offline acceptance passed with 10 Observer and 386
  Harness tests. Live verified 2026-10-30 with one real CS2 v4 outcome: the
  Observer returned its exact context, 0.180846 actual cost, and 1.43376
  reservation in one bounded BigQuery read.

## Next

1. **Private Cloud Run deployment** (coordinated operator approval 2026-10-31):
   wheel-only image, dedicated read-only runtime identity, and a single
   configured invoker; Platform owns the resources. Deployed 2026-11-07: one
   authenticated deployed query returned 200 and unauthenticated access 403.
   Cloud Run reserves `/healthz`, so the health route moved to `/health`
   (redeployed `sha256:ac0de602…`; 200 authenticated, 403 unauthenticated).

## Deferred

- v2 subscription and alerting, only when live alerts are needed.
- Per-campaign/session grouping, which requires a coordinated event-schema tag.
- Cloud billing export, dashboards, and any authoritative storage, each
  requiring separate approval.

## Updating this roadmap

Mark v1 complete only after offline gates and a bounded live query against the
real archive pass. Keep live calls read-only, byte-capped, time-bounded, and
separately operator-approved.
