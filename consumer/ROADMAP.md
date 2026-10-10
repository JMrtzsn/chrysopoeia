# Consumer Roadmap

## Complete

- [x] Strict shared-schema Pub/Sub ingress with terminal ack versus transient retry.
- [x] Independent bounded public quote, risk, fee, and depth checks.
- [x] Durable append-only journal, restart replay, and event deduplication.
- [x] Full-position take-profit, stop-loss, time exit, and YES/NO settlement sweeps.
- [x] Separate container path and optional Platform deployment contract.
- [x] Bounded live verification 2026-10-10: authenticated push, fresh-quote fill,
  one Scheduler sweep time-exit close, mounted ledger across revision deploys.
  Evidence: `../platform/docs/deployment.md`.

## Not yet exercised live

- YES/NO settlement, dead-letter delivery, and concurrent-revision writers.

Authenticated execution remains prohibited.
