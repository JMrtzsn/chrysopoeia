# Consumer Roadmap

Completed items are removed; see git history.

## Next

1. **Settle positions with no usable exit quote** (2026-11-18; needed only if
   paper trading resumes). Positions whose markets stopped quoting log
   repeated `sweep deferred … exit quote is stale or future-dated` errors and
   never settle. Scope: after market end, settle from public resolution
   metadata, or after a bounded staleness window close as `unsettled` with a
   recorded reason, never a guessed price; log a deferral once per position.
   Acceptance: offline tests for resolved, expired-without-quote, and
   still-fresh cases, plus one live sweep that clears the stuck positions (two
   open as of 2026-11-19). Gates the Platform sweep resume
   (`../platform/ROADMAP.md` item 13).
2. **Remaining paper live checks:** deployed model-produced `trade_plan_ready`
   ingress to a Consumer fill, YES/NO settlement, dead-letter delivery and
   replay, and the revision-rollover single-writer ceiling. Local
   model-produced delivery was verified 2026-10-15.
3. **Polymarket live execution foundation:** verify the official Python SDK and
   supported EOA/order flow; implement isolated execution, structural limits,
   preflight, reconciliation, and kill switch here. Live mode stays disabled
   until all spec gates pass.
4. **Bounded live activation:** only after gates pass, run a separately approved
   smallest-possible live order and exit with the dedicated $10 wallet.

Authenticated execution remains prohibited until step 3 is approved.
