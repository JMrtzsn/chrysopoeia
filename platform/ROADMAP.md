# Platform Roadmap

Completed items are removed; see git history.

`../.agents-cli-spec.md` is authoritative for product scope and acceptance. This
roadmap only orders approved platform work and cannot expand that scope.
Development and live-verification gates are in
`../harness/docs/verification.md`; deployment details are in
`docs/deployment.md`. Paths below are relative to `platform/`.

The platform consumes a released harness artifact. Future event adapters and
consumers are coordinated with the harness contract and appear in both roadmaps.

Operator-approved coordination boundary (2026-10-06): the harness owns Vertex
model endpoint selection (`gemini-3.5-flash` at `us`). Platform supplies ambient
project/auth and places resources in its configured compute region.

Coordination boundary (2026-10-19): the Dockerfile installs the locked
dependency set in its own layer before copying the wheel and configs; keep that
ordering so code or TOML changes push only small layers. The size saving is not
yet measured.

## Next

3. Deploy the live-execution consumer (separate identity and secret handling)
   only after `../consumer/ROADMAP.md` live-execution gates pass and are
   approved.
5. **Self-learning rollout** (coordinated with Harness roadmap item 8; each
   step separately approved): run bounded cycles until a context has 20
   finalized outcomes, then verify the first agent-approved profile revision
   end to end. Model-produced deployed Consumer delivery is still pending a
   non-abstaining turn. No scheduling is authorized by this entry alone.
11. **Journey-health event alerting** (operator-approved 2026-11-13;
    implementation separately approved). Existing health alerts page only on
    process-failure logs; outcome-level degradation must react to the event
    stream, not poll `/v1/health`. Design:
    - A platform-owned filtered push subscription on `chrysopoeia-events`
      triggers a small Cloud Run evaluator that calls the private Observer
      `/v1/health` once per event with its OIDC invoker identity and logs one
      structured `observer_health` record (`ERROR` when `degraded`, else
      `INFO`). The evaluator owns no ledger and only logs.
    - One threshold alert on `degraded` record rate >0 for ~10 minutes, and
      one in-window absence condition on the health-record rate.
    - The `Chrysopoeia health (local)` dashboard gains a journey-health panel.
    - Acceptance: offline evaluator tests; image build, pin, and deploy; one
      bounded live check (labeled event → one structured record → alert metric
      visible); no model or campaign spend. Cost bound: ~10 events/day,
      scale-to-zero evaluator, one ≤100 MiB Observer query per event.
12. **Terraform migration with plan gates:** cutover is done and Pulumi is
    retired. Remaining from 12f: scheduled drift checks (`run.sh drift`), CI
    required checks, and apply approval once a remote repository policy
    exists. The ghost-diff allowance list stays empty.
13. **Paused for re-evaluation; resume gate** (2026-11-18). Both Scheduler
    jobs are paused through Terraform (`scan_paused`, `consumer_sweep_paused`).
    The research forecaster is retired (`../harness/ROADMAP.md` Next), so the
    scan stays paused indefinitely. The sweep resumes only if paper trading
    resumes, after Consumer Next item 1. Before resuming, enable the Cloud
    Billing export to BigQuery and record the last 30 days of spend by service.
    Acceptance: a recorded spend breakdown, then each resume applied separately
    through the gated plan→policy→apply flow, with one clean scheduled tick or
    sweep observed.

## Deferred

- Cloud SQL, RAG Engine, Memory Bank, and managed runtime services, gated on
  adoption triggers in `docs/deployment.md`.
- Multi-tenant or public-facing deployment (Level 3), which requires explicit
  design before anything exists.

## Updating This Roadmap

- Change only work owned by `platform/`.
- Start a milestone only with explicit user approval and an agreed contract.
- Every externally observable feature addition or change requires both offline
  checks and bounded live verification against the real changed boundary, as
  defined in `../harness/docs/verification.md`. A failed or unavailable live check
  leaves the feature incomplete and blocks any commit recommendation.
- Remove work only after acceptance evidence exists and the change is
  committed.
- Do not add speculative services or infrastructure.
