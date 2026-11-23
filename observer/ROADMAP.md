# Observer roadmap

Completed items are removed; see git history.

The observer is an independent, read-only work unit. Harness and Consumer own
their events and journals; Platform owns archive infrastructure, IAM, and any
future deployment. The BigQuery archive is an analytics copy, never a ledger.

## Next

1. **Platform item 11 — journey-health event alerting**: platform-owned
   evaluator over the existing `/v1/health` endpoint, `degraded`/absence
   alerting, and a dashboard health panel (details and acceptance in
   `../platform/ROADMAP.md`).

## Deferred

- v2 subscription and alerting, only when live alerts are needed.
- Per-campaign/session grouping, which requires a coordinated event-schema tag.
- Cloud billing export, dashboards, and any authoritative storage, each
  requiring separate approval.

## Updating this roadmap

Remove work only after offline gates and a bounded live query against the real
archive pass. Keep live calls read-only, byte-capped, time-bounded, and
separately operator-approved.
