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

## Next

1. **Remaining paper live checks:** YES/NO settlement, dead-letter delivery and
   replay, and the revision-rollover single-writer ceiling.
2. **Polymarket live execution foundation:** verify the official Python SDK and
   supported EOA/order flow; implement isolated execution, structural limits,
   preflight, reconciliation, and kill switch here. Live mode stays disabled
   until all spec gates pass.
3. **Bounded live activation:** only after gates pass, run a separately approved
   smallest-possible live order and exit with the dedicated $10 wallet.

Authenticated execution remains prohibited until step 3 is approved.
