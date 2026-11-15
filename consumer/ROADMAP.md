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
- [x] Ignore routing: offline checks and a live `turn_outcome` delivery returned
  HTTP 204 without a ledger write on 2026-10-12.
- [x] Per-position sweep isolation (operator-approved 2026-11-15): a position
  whose public exit quote is unreadable (stale/future-dated) is deferred with a
  structured ERROR log and retried on the next sweep, instead of failing the
  whole sweep with HTTP 503 — one flaky venue quote no longer blocks settlement
  of other open positions or spams the sweep scheduler with UNAVAILABLE.
  Fail-safe semantics are unchanged: nothing settles on bad data, and ledger or
  outbox failures still fail the sweep. 42 tests, Ruff, and ty pass; image
  `sha256:6f53a5e6…` deployed with the documented quiescing (trigger queue
  already paused, no active Harness execution, sweep Scheduler paused, resumed
  after revision `00005-w4m` served 204 sweeps); evidence:
  `../platform/docs/deployment.md`.

## Next

Coordinated operator approval (2026-10-17): consume Harness v2 two-sided paper
plans while retaining v1 YES compatibility. Check the selected token and outcome
against public metadata, fill its real book, and settle the held token correctly.
Harness approval and acceptance are in `../harness/ROADMAP.md`. This does not
authorize deployment or real orders.

0. Team-named binary outcomes (2026-10-26, coordinated with the Harness
   esports benchmark approval): market metadata checks accept any two distinct
   outcome labels; the first listed outcome token remains the YES side. No
   contract change; 40 offline tests pass.
1. **Remaining paper live checks:** a live model-produced `trade_plan_ready`
   through ingress to a Consumer fill, YES/NO settlement, dead-letter delivery
   and replay, and the revision-rollover single-writer ceiling. A model-produced
   plan reaching a local Consumer fill was verified 2026-10-15
   (`../harness/docs/verification.md`); deployed ingress, settlement, dead-letter,
   and rollover remain unverified.
2. **Polymarket live execution foundation:** verify the official Python SDK and
   supported EOA/order flow; implement isolated execution, structural limits,
   preflight, reconciliation, and kill switch here. Live mode stays disabled
   until all spec gates pass.
3. **Bounded live activation:** only after gates pass, run a separately approved
   smallest-possible live order and exit with the dedicated $10 wallet.
4. ~~**Consumer lifecycle outcome events**~~ (done 2026-10-25): the Consumer
   publishes versioned `consumer_outcome` records for durable fill, rejection,
   close, and settlement transitions to the Harness event topic, derived from
   the Consumer journal with stable event IDs and durable delivery
   acknowledgements. Deployed and live-verified 2026-10-25 (image
   `sha256:6807f5c7…`): a labeled synthetic plan was filled on a fresh public
   quote and settled by the minute sweep at resolution, with
   rejected/filled/settled outcomes archived in BigQuery; evidence in
   `../platform/docs/deployment.md`. Model-produced deployed delivery remains
   pending a non-abstaining Harness turn.

Authenticated execution remains prohibited until step 3 is approved.
