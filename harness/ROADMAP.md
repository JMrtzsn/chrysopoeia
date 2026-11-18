# Harness roadmap

`.agents-cli-spec.md` defines product scope and acceptance. This roadmap orders
approved harness work only. Paths are relative to `harness/` unless noted.
Verification policy and harness evidence are in `docs/verification.md`.
The platform consumes a released harness artifact. Event adapters and consumers
are coordinated harness/platform work recorded in both roadmaps.

Operator-approved cross-work-unit direction (2026-10-06): use the supported
Vertex `gemini-3.5-flash` model and its non-global pricing, with the `us` model
endpoint configured separately from the platform compute region.

## Complete

- Runtime-neutral paper-cycle contracts with ADK at the runtime edge; validated
  configuration and local `inspect`/`validate` commands.
- Public Polymarket discovery and capture, canonical snapshot evidence, and a
  snapshot-driven cycle with abstention, review, risk checks, and depth/fee-aware
  paper fills.
- Deterministic model-cost gates and offline evaluation/pre-commit checks.
- Durable local journal for sessions, turns, fills, marks, settlement, model
  costs, and book inspection. Admission is idempotent; interrupted turns recover
  without repeating model work. Venue resolution and price marks are
  read-only/public. Live verified 2026-09-15 and 2026-09-30.
- Bounded `chrysopoeia run`: harness-selected markets, persisted session limits,
  max-cycle/cost/loss/deadline/stop controls, recovery, and target win-rate/net
  P&L report. Live verified 2026-09-30.
- Reviewer-approved entry/exit plans and the in-process paper bracket simulator
  (`d944289`): fresh executable bids, full closes, journal recovery, and
  resolution handling. Live verified 2026-10-05.
- The `trade_plan_ready` event producer and idempotent in-process paper consumer
  (`690d8f9`): `cycle` returns the reviewed, policy-accepted event; `run`
  consumes it locally while preserving bracket behavior.
- Standalone local paper consumer (`31d2642`): `consume` reads an existing event,
  obtains a fresh public quote, rechecks the plan, and writes the local journal
  idempotently. Live verified 2026-10-07.
- Optional journal-backed producer outbox and the former Platform Pub/Sub publisher
  (`3d942a5`): accepted plans are durably pending until publish confirmation and
  CLI acknowledgement. Bounded live verification passed 2026-10-08; no subscriber
  or consumer is included. Evidence is in `docs/verification.md`.
- Direct Harness event publishing (`a4d71d5`, `ac64302`): configured HTTP or
  Pub/Sub sinks drain the durable outbox and acknowledge confirmed delivery.
  Live evidence is in `docs/verification.md`.
- Turn-outcome events and single-topic publishing: every decided turn is
  journaled and optionally published through the shared outbox; subscribers can
  filter by record type. Live-verified 2026-10-12; evidence is in
  `docs/verification.md` and `../platform/docs/deployment.md`.
- Shared `trade_plan_ready` v1 schema in `../contracts/` (`3b495d1`), consumed
  as data by the independent paper consumer in `../consumer/`. Harness work for
  event consumption ends at the schema, event, and outbox.
- The bounded trader-tool loop (`292b762`): deterministic market discovery,
  snapshot retrieval, and trade-plan checks with fail-closed limits. Live
  verified with the checked-in Vertex model 2026-10-06.
- One bounded live paper cycle through a non-Gemini provider (OpenRouter via ADK
  registry). Live verified 2026-09-27.
- Bounded trader-tool loop through OpenRouter/LiteLLM using
  `openai/gpt-4.1-mini` at the explicitly recorded rates. Live verified
  2026-10-08; evidence is in `docs/verification.md`.
- Vertex Gemini Google Search grounding: one bounded pre-trader research call,
  strict citable evidence normalization, failure-safe status, and query cost
  accounting. Live verified 2026-10-14; evidence is in
  `docs/verification.md`.
- BYOK model provider for every role through the ADK boundary (`adk-gemini` for
  Vertex or `adk-registry` for other providers). Live verified 2026-10-15;
  evidence is in `docs/verification.md`.
- BYOK research providers selected by the context model: Google Search grounding
  (Vertex Gemini) and OpenRouter web search (Exa), normalized into
  snapshot-bound external evidence with bounded results and cost accounting.
  OpenRouter web live verified 2026-10-15; evidence is in `docs/verification.md`.
- Trader-facing financial analysis tools for daily US equities and public crypto
  OHLCV: bounded history, deterministic statistical/technical indicators, and
  snapshot-bound citations. Verified locally 2026-10-15; evidence is in
  `docs/verification.md`.
- Polymarket BTC 5m series history and local forecast evaluation: the trader can
  inspect resolved sibling windows, and `polymarket-eval` scores each binary
  market's first pre-close P(YES), trade or abstain, with Brier against the
  Gamma-resolved outcome and same-time CLOB price (optionally filtered to one
  series). Up/Down markets are now capturable, with Up as the YES side. The initial five-window CLOB
  baseline scored 0.247; there are not yet agent forecasts in the local journal.
  Evidence is in `docs/verification.md`.
- Venue-coupling audit (2026-11-13, read-only): report in
  `docs/venue-coupling-audit.md`. Four cross-unit couplings (core
  Polymarket-URL validation inside `MarketSnapshot`, YES-first outcome
  semantics, `polymarket:*` context namespaces persisted in archived events,
  and the numeric `market_id` pattern), adapter-only wiring at six direct
  call-site modules, and config-only closed gates. No code changes; no
  abstraction added ahead of a second venue.
- Reserved-cost `turn_outcome` v4 and Observer actual/reserved reporting: decided,
  context-attributed cycles carry the existing reservation ceiling including
  research; v1/v2/v3 remain compatible, and mixed-version Observer groups keep
  reservations null rather than partial. Live verified 2026-10-30 with a real
  CS2 outcome and exact Observer values; evidence is in `docs/verification.md`.

The recorded commands and evidence for harness milestones are in
`docs/verification.md`.

## Next

1. **Bounded cycle wall-clock (paused-platform blocker, 2026-11-18).** Since
   2026-11-17 most scheduled scan cycles stall after a model call and are
   killed at the Cloud Run 900 s task timeout (all 6 on Nov 17, 18:42Z on
   Nov 18). The trace showed a `function_call` response and then no output for
   about 14 minutes. Scope: find the stalled call from journal and log
   evidence; put deterministic per-call timeouts on model, research, and venue
   calls plus an overall cycle deadline below the task timeout; record a
   journal outcome when the deadline hits instead of being killed. Acceptance:
   an offline test where a hanging tool or model stub ends the cycle with a
   recorded timeout outcome before the deadline, plus a bounded live cycle
   that finishes under the deadline. Gates the Platform scan resume
   (`../platform/ROADMAP.md` item 13).

Previously empty; the Observer journey health endpoint (operator-approved
2026-11-13) is owned and tracked in `../observer/ROADMAP.md`.

## Older

1. **Automated paper trading for esports match winners** (operator-approved
   2026-11-12; implemented same day): the Platform profile sets
   `[session] scored_only = false`; `run` accepts both scored-only and
   paper-trading profiles, and approved plans that pass deterministic risk
   policy produce journal fills and `trade_plan_ready` events under the
   existing risk, fee, and cost caps. Real-money execution remains
   prohibited. Live evidence: Platform ROADMAP item 9.

Coordinated operator approval (2026-11-07): retire BTC 5m automation and make
CS2/Dota 2 match winners the automated venue, scored-only. `[venue].markets =
"esports-match-winner"` replaces `[venue].series`; discovery keeps only
upcoming match-winner markets (start at least 10 minutes away); deterministic
policy records approved plans as `policy_rejected`/`scored_only` with no plan or
fill; `run` refuses non-scored-only profiles. The BTC series, offset,
window-baseline, and BTC-only prompt code are removed; BTC context routing stays
for archived outcomes. This supersedes the BTC-only restrictions recorded below.
Offline implementation is complete; a bounded live `run` check and a Platform
image rebuild remain, each separately approved.

Operator direction (2026-10-28): BTC 5m runs are stopped as a default. The
accumulation campaign was halted 2026-10-26 and no further BTC executions run
unless explicitly approved for verification. The venue direction is match and
game markets: esports (CS2, Dota 2) as the primary candidate, with NBA/NFL
pre-game as the sharp control group.

Operator approval (2026-10-26): benchmark esports match-winner markets (CS2,
Dota 2) as the next forecast venue, with NBA/NFL pre-game as the sharp control
group; macro, daily crypto, and other quant-priced markets are explicitly
skipped. Two-plus weeks of scored-only forecasting (`polymarket-eval`, no
trading); paper-trade a family only if measured edge survives fees. Team-named
binary outcomes are now supported in the adapter and Consumer metadata checks
(first listed outcome = YES side; no contract change). The BTC-only automated
restriction is unchanged; benchmark cycles run as explicit `capture`/`cycle`
verification inputs. Implementation evidence: 382 harness + 40 consumer offline
tests pass; a real Spirit/FURIA match-winner book captured ($220k top-level
depth).

Resume state (2026-10-28): four forecasts are journaled (Astralis YES @0.58,
Alliance/FaZe approved+filled, two Dota 2 abstains at p=0.5) and matches are
resolving; next action is `polymarket-eval` on the benchmark journal, then
daily match batches toward 20-30 scored forecasts. The grounded-prompt
input-ceiling root cause is fixed and `configs/esports.toml` (32768 input)
exists for the benchmark. Retry failed turns by recapturing, since the journal
replays a recorded failure idempotently. Vertex auth locally:
`GOOGLE_CLOUD_PROJECT=PROJECT_ID` with operator ADC; OpenRouter has no
credits. Benchmark journal lives under the opencode temp dir
(`esports-bench/journal`); recapture fresh snapshots per cycle.

Operator direction (2026-10-28): insight is an independent **observer** work
unit, not a Harness command. Like the Consumer, it consumes Harness-owned
event schemas as data with its own read-only identity and no execution
authority; Harness event consumption still ends at the schema. v1 is
pull-based: at read time it queries the BigQuery archive (its event log) for
per-context decisions, fills, settlements, win rate, realized P&L, actual vs
reserved model cost, and campaign counters against the 20-trade gate. v2 adds
its own subscription and alerting only when live alerts are needed. No new
authoritative store and no projection database in v1; the Harness and
Consumer journals stay the financial ledgers. Local and benchmark runs must
publish to the topic (`CHRYSOPOEIA_EVENT_SINK`) or the observer cannot see
them; a per-campaign/session tag on events would be a coordinated schema
change. The Harness-local insight CLI is dropped as the central surface.
Observer implementation and verification are owned by `../observer/`; see its
README and roadmap. Harness ownership remains event production and schemas.

Operator approval (2026-10-19): improve BTC 5m forecasts with deterministic
window context and later entry. (1) Attach a snapshot-bound baseline evidence
record with the window open, latest price, delta, seconds remaining, recent
1-minute volatility, and a normal-approximation P(Up); it is measured evidence,
not an instruction. (2) Forecast at a configured offset into the window instead
of at its boundary (`[venue].forecast_offset_seconds`), so the trader sees real
price movement rather than a coin flip. Keep research off for BTC. Acceptance:
offline math/selection tests, one bounded live cycle showing the baseline and
the offset, then a clean multi-window benchmark. No platform, schema, or
authenticated-execution change.

Implementation evidence: 354 offline tests pass. Live cycles at the 120-second
offset attached `window_open/last/delta_bps/seconds_remaining/minute_vol/
baseline_p_up` evidence ($0.0259 and $0.0503 booked); one produced a plan at
p=0.75. An earlier attempt exposed a stale-price bug (last closed 1-minute
candle equal to the window open, delta 0.0), fixed by reading the public last
price and the window-start candle's open. The configured offset is a minimum
elapsed time: a session started later in a window forecasts immediately and can
land closer to close. A clean multi-window benchmark has not rerun since.

Follow-ups recorded from the same review, not implemented:
`window_baseline` remains a config-gated Harness measurement only; replay-based
A/B scoring, archive-backed past-outcome context, and a bounded provider-error
retry stay unapproved future work. A ~9-market pilot is not evidence for tuning.

Operator approval (2026-10-19): implement local missing-trader-output diagnostics
only. Store safe cost error/reason and reserved model-call count in the failed
turn, without changing tools, retries, budgets, or running paid cycles. Offline
tests reproduce the cost-cap missing-output failure; the prior live trigger is
still unconfirmed. See `docs/verification.md`.

Follow-up (2026-10-26): the live trigger is now confirmed and fixed. Grounded
research inflates the served prompt server-side, so actual input usage can
exceed the 8192 policy input ceiling (measured 8413) and produce
`MODEL_COST_USAGE_INVALID` → no structured proposal. The reservation now always
uses the policy input ceiling, and research-heavy profiles can raise the
ceiling (`configs/esports.toml` uses 32768). Evidence in
`docs/verification.md`.

Operator approval (2026-10-19): add an optional validated `[research] enabled`
switch (default on) and set it `false` in the BTC and Platform profiles. Web
research dominated measured BTC cycle cost (~72%) and rarely informs a
five-minute window; disabling it also removes the research allowance from the
failure reservation ($0.7038528 to $0.2838528). Ledger the change, verify it
offline, and keep the local journal authoritative.

Implementation evidence: a local BTC cycle with research disabled abstained at
$0.04432065 and recorded zero grounded queries, versus $0.21271855 with research
enabled; no failures occurred. The reservation drops to $0.2838528. The deployed
job still runs an older image with research enabled and needs a rebuild/rollout.
See `docs/verification.md`.

Coordinated operator approval (2026-10-18): move CLI operating settings to
required validated TOML session/risk sections and venue selection; remove
setting flags rather than retain overrides. Keep invocation inputs as flags.
Update the Platform image/job to use a bundled two-cycle config and verify
one bounded two-cycle paper execution. Do not start the BTC benchmark.

Implementation evidence: 341 offline tests passed; the pinned config-only
Platform image completed execution `chrysopoeia-cycle-local-nr6tj` at its
configured two-cycle cap (one paper fill, one failed turn). Booked cost
$0.87996215 includes a conservative failure reservation. Emitted events were
confirmed in BigQuery; no BTC benchmark ran. See `docs/verification.md`.

Operator hard requirement (2026-10-18): during development, BTC 5m Up/Down is
the only automated venue market. `[venue].series` is required and restricted to
`btc-updown-5m`; CLI discovery, `run`, and the trader discovery tool are bound
to it, making the volume-ranked fallback unreachable. Explicit `capture`/`cycle`
targets remain verification inputs. The Platform profile moves to the BTC series
and must be rebuilt, redeployed, and verified with one bounded execution.

Implementation evidence: enforcement, image pinning, and one `validate`
execution are verified. The benchmark is blocked because three consecutive BTC
turns ended without a structured trader proposal (deployed 0/2, local 0/1),
each booking its full reservation ($0.7038528) and publishing no outcome.
Fix the missing-output path and verify two windows before spending the 20-window
budget. See `docs/verification.md`.

Earlier coordinated operator approval (2026-10-18): add clock-selected BTC 5m
windows at five-minute boundaries. The original `--series` flag is superseded
by `[venue].series` in the config-only contract above. Platform first
adds a raw-event BigQuery subscription to the existing topic for long-term
analytics. The local journal remains authoritative. Implement and verify the
capability only; do not start the 20-window benchmark or another forecast run.

Implementation evidence: series selection/cadence have offline
behavior tests; one bounded public Gamma read selected the current BTC window
on 2026-10-18. No models or forecasts ran. Operator commands and limitations
are in `docs/collection.md`; end-to-end model collection remains unverified.

Coordinated operator approval (2026-10-17): two-sided paper positions are now in
scope in Harness and Consumer, ahead of authenticated execution. Acceptance:
explicit outcome and actual token book, v2 NO plans, independent consumer token
binding, correct side-aware marks/exits/settlements, and local verification.
The implementation retains v1 YES compatibility. No platform change is included.

1. **Forward BTC 5m benchmark:** run the trader on at least 20 live BTC Up/Down
   5m windows and score them with `polymarket-eval --series-url ...` against the
   same-time CLOB baseline. Capture of these markets now works; no agent sample
   exists yet. No platform is needed.
2. **Live accepted-plan delivery:** verify a model-produced `trade_plan_ready`
   event reaches the independent Consumer and produces a paper fill. Local
   delivery is verified 2026-10-15 (BYOK OpenRouter trader, HTTP sink to the local
   Consumer, paper fill recorded; `docs/verification.md`); the deployed path
   (Pulumi subscription) remains unverified.
3. **Liquidity-aware sizing and profitability by amount** (operator-approved
   roadmap addition, 2026-10-19; offline implementation complete 2026-10-26
   with 381 passing tests; evidence in `docs/verification.md`; bounded
   public-book verification and image redeploy pending, each separately
   approved; implementation started 2026-10-26 after the
   first accumulation campaign showed 3 of 5 deployed plans rejected on the
   consumer's fresh quote): distinguish the
   policy/risk allowance from measured executable book capacity and capacity
   that still meets the configured net-edge requirement. For BTC 5m YES/Up and
   NO/Down separately, use the actual selected token's fresh asks, not a
   complemented price. Reuse the existing deterministic depth/fee quote logic;
   order-book thickness is observed data, never an operator-invented constant.
   Compare bounded candidate stake amounts using the same forecast and snapshot:
   shares, VWAP, worst entry price, slippage, fees, total cash required, expected
   net dollar profit, and expected net ROI. Show marginal as well as average
   edge so extra dollars are not added at unprofitable prices just because the
   earlier liquidity was cheap. Keep model/research costs separate and show
   their effect on break-even; do not treat model probabilities as proven returns.
   Acceptance example: when policy allows $50 but only $10 of depth meets the
   edge requirement, compare the $10 quote with the full $50 quote, flag the
   latter's deterioration/rejection, and constrain the chosen stake accordingly.
   If $50 cannot be filled within captured depth/entry limits, report unavailable
   rather than extrapolate. Preserve all risk/fee/expiry controls; never increase
   the allowed stake to match depth. Cover thin books, multiple price levels,
   insufficient depth, and YES/NO sides with offline behavior tests, followed by
   separately approved bounded public-book verification. Keep this Harness-owned:
   no Consumer/schema, platform, or authenticated-execution changes are included.
4. **Additional research providers:** Google Search, OpenRouter web search, and
   public stock/crypto OHLCV analysis are implemented. Financial/company-data
   sources (e.g. FRED, CoinGecko, SEC EDGAR) remain open until separately
   selected and verified.
5. **Trading-history context source:** read-only BigQuery-backed evidence tool,
   after outcome data exists; see the spec's approved future item.
6. **Additional venues:** separate milestones after the Polymarket paper path is
   verified. Two-sided paper positions were separately approved above; no new
   execution venue is introduced. Event-contract changes use new schema versions.
7. **Future CCXT crypto-trading integration:** CCXT is now used only for public
   OHLCV data. After the Polymarket YES-only live path is verified, separately
   plan any crypto venue execution, including exchange, spot/derivatives, and
   its own risk and activation gates.
8. **Outcome-driven market contexts and agent-approved profile iteration**
   (operator-approved roadmap addition, 2026-10-21; offline implementation
   complete, local live verification passed 2026-10-22/23): route canonical
   market families
   and stable pair/event keys to bounded, versioned context profiles. The loop is
   `trades -> outcomes -> context-scoped information -> summary -> proposed
   profile revision -> independent agent review -> next profile version`.
   Harness `turn_outcome` v3 and Consumer `consumer_outcome` v1 events provide
   the joined history; deterministic BigQuery queries deduplicate events, enforce
   an as-of cutoff, and return bounded aggregates for only the matching context.
   A context-curator agent may summarize those aggregates and propose an
   immutable profile revision; a separate context-reviewer agent approves or
   rejects it. No human approves each local profile revision. The Harness
    deterministically validates the manifest, at least 20 distinct closed/settled
    trade plans from the active profile version, outcome sample sufficiency,
   resource bounds, and registered tool/evidence allowlists before activation.
   Open positions and abstentions are not losses, and sparse outcomes do not
   trigger profile churn.

   Persist bundled profiles in source control and generated profiles in a
   Harness-owned local catalog separate from the financial journal. Every turn
   pins the exact profile ID/version/hash and its outcome provenance. Local
   generated profiles are not included in the wheel or deployed automatically;
   promotion to the bundled set is a separate release. Agents cannot create
   executable tools, change policy, risk, accounting, or execution authority.
   New tool families need separate implementation, offline contract tests, and
   bounded live verification. Acceptance: restart/replay loads the pinned
   profile; different context keys cannot share tools or history; rejected,
   malformed, under-sampled, or unregistered-tool revisions leave the active
   profile unchanged; approved revisions only affect later turns; global risk
   and accounting remain unchanged. The BTC-only automated-market restriction
   remains until separately approved and verified.

   The event/context foundation and the offline profile loop are implemented:
   context identity routing (BTC series, recurring crypto series, and generic
   events), bundled profiles, the local append-only profile catalog with
   immutable manifest hashes and outcome-summary provenance, the
   curator/reviewer agent flow with cost accounting, the 20-finalized-plan
   activation gate, and profile-scoped trader tool allowlists. Live
   verification passed 2026-10-22/23 for the local path: a v3-tagged BTC
   outcome reached the archive, an agent-approved local profile was created
   and pinned by its cycle, and the bounded BigQuery history query returned
   matching aggregates (`docs/verification.md`). Do not infer proven
   profitability from small samples.

   Ordered steps to reach a live self-learning cycle on the platform (each
   separately operator-approved; 1-3 are coordinated with Platform and
   Consumer and are recorded in both roadmaps):

   1. ~~**Rebuild and pin the feature image**~~ (done 2026-10-23): image
      `sha256:83447e14…` built from the current wheel and deployed. The job
      also gained `CHRYSOPOEIA_CONTEXT_CATALOG=/mnt/journal/context_profiles.jsonl`
      so generated profiles persist on the journal bucket between executions
      and rollouts; bundled profiles remain in the image.
   2. ~~**Enable the loop in the bundled platform profile**~~ (done
      2026-10-23): `[history].enabled`, `[context_learning].enabled`, and
      `maximum_output_tokens_per_call = 3072` are set in
      `configs/platform.toml`. Worst-case reservation ~$0.53/turn fits the
      unchanged `$1.50` / two-cycle budget (~$1.05). Forward-evaluation
      criteria are recorded in `docs/architecture.md`. Verified live by
      execution `chrysopoeia-cycle-local-j7xbh` (evidence in
      `docs/verification.md`): v3 outcome pinned the bundled BTC profile v1,
      the deployed history query returned matching aggregates, and the
      activation gate correctly stayed closed at 0 completed trades.
   3. ~~**Deploy the Consumer**~~ (done 2026-10-25): image `sha256:6807f5c7…`
      pinned, 15 consumer resources deployed, filtered push subscription live.
      Verified with a labeled synthetic plan: fresh-quote paper fill, minute
      sweep settlement at resolution, and rejected/filled/settled
      `consumer_outcome` events archived (evidence in
      `../platform/docs/deployment.md`). Two bounded harness runs abstained
      4/4 turns, so model-produced deployed delivery is still pending; the
      gate structurally counts only outcomes joined to real harness turns.
   4. **Accumulate evidence:** run bounded, operator-approved cycles (on-demand
      or scheduled via the job) until at least one context has ≥20 finalized
      outcomes under its active profile version. First campaign ran 2026-10-25/26
      and was halted early after ~39 of 80 executions ($2.76 actual): 46
      decisions produced 5 plans (~11%), of which the consumer rejected 3 for
      insufficient executable depth / maximum entry exceeded on its fresh
      quote, leaving 2 completed trades. Yield is throttled by item 3 below;
      the campaign resumes after liquidity-aware sizing ships. The counter is
      `completed_trade_count` in the archive aggregate; synthetic verification
      outcomes are structurally excluded.
   5. **First revision turn:** a later cycle in that context triggers the
      curator/reviewer revision flow; verify the new profile version is
      recorded, activated only for later turns, and that the archive
      aggregates match the journal. Record evidence in
      `docs/verification.md`.

See `docs/proposals.md` for the accepted live-trading design and other unapproved
feature proposals; proposals do not expand this roadmap.

## Deferred

- RAG/memory, lifecycle and version management.
- Authenticated order submission until all spec gates pass and each bounded live
  verification is separately approved.
- A meta-harness/control plane unless multiple independent harnesses exist.

## Updating this roadmap

- Change only harness-owned work. Cross-work-unit changes require approval in
  both plans.
- Start a milestone only with explicit user approval and an agreed contract.
- Externally observable changes require offline checks and bounded live
  verification against the changed boundary. A failed or unavailable check
  leaves the milestone incomplete.
- Mark work complete only after acceptance evidence exists and the change is
  committed. Do not add speculative abstractions or plugin systems.
