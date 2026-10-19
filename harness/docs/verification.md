# Verification

The product spec defines acceptance. Run the canonical offline checks in
[`../AGENTS.md`](../AGENTS.md) before recommending completion. Offline tests
require no credentials or live model/venue calls; paid or network checks do not
belong in automatic hooks.

## Bounded live checks

Externally observable changes need a live check of the changed boundary after
offline checks. Obtain operator approval, estimate cost, bound calls/time/data,
use least privilege and ambient/provider-standard authentication, sanitize the
evidence, and clean up temporary resources. Record command, boundary, result,
bounds, and cost. Failure or unavailability blocks completion. Venue checks are
public/read-only; model checks are bounded paper cycles; authenticated exchange
execution is prohibited. Full policy is in
[`../../.agents-cli-spec.md`](../../.agents-cli-spec.md).

## Recorded harness checks

All model runs below used ambient Vertex ADC unless noted. Operator approval was
obtained for cost or external effects; temporary local files were removed.
Costs are estimated model cost unless noted.

| Date | Command / boundary | Result and bounds |
| --- | --- | --- |
| 2026-09-15 | `uv run chrysopoeia discover --limit 1`; `uv run chrysopoeia capture 559651 --output <local file>`; public Gamma/CLOB | Validated metadata, depth, fee, and resolution rules. At most 3 Gamma pages/75 records; five-second timeout and 256 KiB response cap. No model cost. |
| 2026-09-15 | `uv run chrysopoeia cycle --snapshot <captured market 559651> --config <temp config> --journal <temp dir>`; repeat same command; Vertex | First run abstained after one trader call (~$0.00226); repeat made no model call and added no journal records. |
| 2026-09-15 | About 13 one-cycle runs with seeded snapshot and local evidence bundle; Vertex paper workflow | Observed abstain → review → edge/exposure rejection → fill (24,000 shares at VWAP $0.005, $2.40 fee) → same-market preemption. About $0.03; paper effects only. |
| 2026-09-15 | `load_market_resolution("20")`; `chrysopoeia settle --journal <temp dir> --market <market id>`; public Gamma | Market 20 normalized to `resolved_no` and settled deterministically; unresolved/ambiguous markets refused. Three bounded Gamma reads; no model cost. |
| 2026-09-15 | `chrysopoeia mark --journal <temp dir>`; public Gamma/CLOB | Open position marked at $0.038; failed capture wrote no mark. One successful capture; no model cost. |
| 2026-09-27 | `uv run chrysopoeia discover --limit 5 --config <temp>`; `uv run chrysopoeia capture 559651 --config <temp> --output <tmp>`; `uv run chrysopoeia cycle --snapshot <tmp> --config <temp>`; OpenRouter via ADK registry/LiteLlm | One trader call, abstained; estimated $0.004805 against $0.06144 reserved ceiling. `OPENROUTER_API_KEY` came only from the shell environment. |
| 2026-09-30 | `uv run chrysopoeia cycle --snapshot <capture> --config <temp config> --journal <temp dir>`; identical repeat after seeding an unfinished turn | Recovery abandoned the prior turn before model calls; current cycle abstained after one trader call (~$0.0022); repeat added no records. |
| 2026-09-30 | `uv run chrysopoeia run --journal <temp dir> --config <temp config> --bankroll 1000 --maximum-loss 100 --target-win-rate 0.6 --window-minutes 5 --max-cycles 2 --cost-budget 0.1 --interval-seconds 5 --stop-file <temp>` | Two selected markets, two abstentions, two admitted/finished turns, ~$0.004459 model cost. Stop-file halted resume before calls; changed session target was refused. |
| 2026-10-05 | Bounded Python check: `discover_markets(limit=1)`, `load_market_snapshot`, then paper `evaluate_exits` with a seeded local position; public Polymarket Gamma/CLOB | Selected market 559651; one time-triggered full paper close used captured executable bids. This validated the in-process paper simulator, not an event consumer or live execution path. Five public GETs total; each capped at 5 s and 256 KiB. No model calls or orders; estimated cost $0; temporary journal removed. |
| 2026-10-06 | Bounded Vertex smoke using `gemini-flash-latest` at `us-central1` | Reached Vertex but returned 404 for the unsupported model/location pair. Superseded by the successful `gemini-3.5-flash` smoke at the harness-configured `us` endpoint below. |
| 2026-10-06 | Intermediate bounded Vertex paper-cycle diagnostic using `gemini-3.5-flash` at `us` | Failed/inconclusive: terminated with `TypeError` after five bounded public GETs and before producing a cycle summary; no event was returned and no order was submitted. Model cost is unknown because no cost ledger was returned. The later two bounded runs completed and are recorded separately below. |
| 2026-10-06 | Two bounded Vertex paper-cycle smokes using `gemini-3.5-flash` at the harness-configured `us` endpoint | One no-target cycle called `find_markets` and `get_market`, then abstained: four model calls, actual estimated cost $0.00679470, one public GET, no event or orders, and about 52 s. One draft-seeded cycle called `check_trade_plan` and returned `rejected` with no event: three model calls, actual estimated cost $0.02125530, five public GETs, no orders, and about 23 s. Each run stayed within its approved temporary five-call cap; the combined six public GETs stayed within the approved limit of 15, with each GET capped at 5 s and 256 KiB. This verifies tool integration and fail-closed behavior, not an accepted live or paper fill. |
| 2026-10-07 | First approved attempt of the bounded Python workflow using `discover_markets(limit=1)`, one setup `load_market_snapshot`, a synthetic $1 hold-to-resolution `trade_plan_ready`, a temporary open journal, and actual CLI `consume`; public Polymarket Gamma/CLOB | Failed closed on `Polymarket adapter book is stale`; no fill, model call, or order. 5–7 public GETs were made; the exact count was not emitted. Each GET was capped at 5 s and 256 KiB. Estimated cost $0; temporary files removed. The successful retry is recorded below. |
| 2026-10-07 | One bounded Python workflow using `discover_markets(limit=1)`, one setup `load_market_snapshot`, a synthetic $1 hold-to-resolution `trade_plan_ready`, a temporary open journal, and actual CLI `consume`; public Polymarket Gamma/CLOB | Filled from a fresh quote and preserved distinct original-plan and fresh-quote snapshot IDs. An identical duplicate CLI consume made no write and no fetch. Exactly seven public GETs: three discovery, two setup, and two consume; each capped at 5 s and 256 KiB. Estimated cost $0; synthetic plan, no model calls or orders; temporary files removed. |
| 2026-10-08 | In-memory `uv run python -` calling `run_paper_cycle_state` and `summarize_cycle`; OpenRouter route `openrouter/openai/gpt-4.1-mini` with explicit rates of $0.40/M input and $1.60/M output | Three model calls; the trader called `check_trade_plan` and the cycle returned `approved`. Actual estimated cost was $0.0017388 against a $0.024576 reserved maximum and $0.03 daily cap. Each call was bounded to 8,192 input and 1,024 output tokens, with at most five calls. Zero Polymarket GETs were made against a hard cap of 13, each limited to 5 s and 256 KiB. The snapshot and draft were synthetic and in-memory; no journal, order, or temporary artifact was created. `OPENROUTER_API_KEY` was supplied only through the ambient environment and was never logged. |
| 2026-10-08 | Inline Python with `platform/infra/.venv/bin/python` called Platform `drain()` against one temporary Pub/Sub topic and active subscription using ambient ADC; Harness CLI `outbox-pending`/`outbox-ack` | One synthetic valid trade-plan event was published once with confirmation; one matching message was pulled and acknowledged. The temporary subscription and topic were deleted after the check. Total duration was 22.87 s. Estimated incremental Pub/Sub cost was ~$0 within monthly free usage; billing was not measured. No model, market, Cloud Run, order, IAM, API-enablement, or `pulumi up` operation occurred. |
| 2026-10-12 | Local direct publishing: real `run_journal_turn` on market 665374 with only the model step stubbed to a valid plan; `CHRYSOPOEIA_EVENT_SINK=http://127.0.0.1:8080/push` into a locally running Consumer | Harness journal recorded `outbox_enqueued` → `outbox_acknowledged` → `fill_recorded`; zero events pending. The Consumer received one push (HTTP 204) and recorded `filled` from its own fresh quote. Four public Gamma/CLOB GETs, no model calls or orders, no Pub/Sub; temporary journal and ledger removed. Three earlier real-model attempts that day failed closed before publishing and found the dropped `--draft`/`--context` bug, a wrong default GCP project, and the overlong reviewer reason; up to $0.28 model cost and seven GETs. |
| 2026-10-12 | `GOOGLE_CLOUD_PROJECT=PROJECT_ID CHRYSOPOEIA_EVENT_SINK=http://127.0.0.1:8080/push chrysopoeia cycle --market 665374 --journal <temp> --draft <trade draft>`; Vertex `gemini-3.5-flash` | Same draft that previously crashed on an overlong reviewer reason now completed: exit 0 in 24 s, status `rejected` (`review_rejected`), turn finished `rejected`. Actual estimated cost $0.0459. No event, so nothing was published and the local Consumer received no push. Two public GETs; no orders; temporary files removed. |
| 2026-10-12 | Harness `events.publish()` with `pubsub:projects/<project>/topics/<temporary topic>` using ambient ADC; temporary topic and subscription | Publish confirmed; exactly one message pulled; payload equal to the canonical event and `event_id` attribute matched; acknowledged. Topic and subscription deleted. 14.5 s; estimated cost ~$0. No model, market, Cloud Run, or order calls. The deployed job's image, entrypoint, and sink env remain to be verified at the next deploy. |
| 2026-10-12 | Real Vertex cycle for market 665374 in project `PROJECT_ID`; local HTTP sink into the local Consumer | The trader proposed a NO thesis at probability 0.02 versus YES 0.18; deterministic plan checking returned `plan_check_rejected`, so the reviewer was not called and `review` was null. `proposal.rationale` was present. Journal order was `session_opened`, `turn_admitted`, `turn_outcome_recorded`, `outbox_enqueued`, `outbox_acknowledged`, `turn_finished`; outcome event `outcome-c5e9f0b1c5cd198d904669c1` reached the Consumer, which returned HTTP 204 and made no ledger write. Actual estimated model cost was $0.0591 of $0.2839 reserved. This verifies the live outcome/ignore path, not a model-produced `trade_plan_ready` fill. |
| 2026-10-14 | Plan-check, `plan_inputs`, and discovery iterations using `chrysopoeia run --max-cycles 6` with OpenRouter `openai/gpt-4.1-mini` through the ADK registry, a temporary config, and a local HTTP sink into the local Consumer | Before `plan_inputs`, 0/25 checks passed and 18 had shape errors. After the fixes, 5/5 turns completed and were rejected only because `minimum net edge of 0.05 not met`; each six-turn run cost about $0.03–$0.05. Every `turn_outcome` delivery received HTTP 204 and caused no Consumer ledger write. Live `discover` confirmed discovery ordered by `volume24hr` within 30 days, returning Man City, Fed October, US–Iran/Yemen ceasefire, and Balance of Power markets. Temporary local files were removed. |
| 2026-10-14 | `chrysopoeia run --max-cycles 4 --cost-budget 2.00`; Vertex Google Search context with `gemini-3.5-flash` in project `PROJECT_ID` at `us`; OpenRouter `openai/gpt-4.1-mini` trader/reviewer; local HTTP sink into the local Consumer | All four turns reported research status `ok`: query counts were 7, 6, 5, and 3, producing 8, 7, 1, and 6 evidence records. The trader cited research evidence; all turns abstained because minimum net edge was not met. Recorded cost was $0.3448, including $0.014 per grounded query; the grounding cost is likely within Vertex's 5,000-query monthly free tier. The Consumer returned HTTP 204 four times. An earlier probe exceeded the output ceiling with thinking; disabling thinking and applying a 60 s timeout fixed it. Excerpts are Gemini grounding-support text rather than verbatim page text, and URLs are Vertex grounding redirect URIs. No `trade_plan_ready` event or Consumer fill was observed. |
| 2026-10-14 | Deployed Cloud Run job `chrysopoeia-cycle-local` running `chrysopoeia run --max-cycles 1` (image `sha256:0089b841…`), Vertex `gemini-3.5-flash` at `us`, `CHRYSOPOEIA_EVENT_SINK=pubsub:projects/PROJECT_ID/topics/chrysopoeia-events` | Fixed the plan-check tool schema by typing `check_trade_plan`'s `plan` parameter as `ProposalOutput`, so the checked-in Vertex model receives field structure; before the fix every `check_trade_plan` call failed with `plan schema error: citations: Input should be a valid list`, so the trader could never pass a check. After the fix one turn produced an accepted plan: `plan_checks` showed real deterministic reasons (then `passed`), review approved, `trade_plan_ready` and `turn_outcome` were enqueued and acknowledged from the container, and a paper fill was recorded (market 2589812, 1.817 shares at 0.55). Actual estimated model cost $0.1209393; 3 grounded research queries and public market reads only. Two earlier attempts failed closed on transient Vertex `503 UNAVAILABLE` before any turn outcome; one reached the 15 m task timeout. Bounded to one cycle; no orders. |
| 2026-10-15 | `OPENROUTER_API_KEY` sourced from the local `.router_key` (names only inspected; value never printed) and mapped into the environment; `chrysopoeia run --config configs/openrouter.toml --max-cycles 1 --cost-budget 0.60 --interval-seconds 0` with a temporary local journal and no event sink | Made the model provider BYOK for every role: removed the Gemini-only context validation and the forced Vertex context model, and gated the Google Search tool on a Gemini context model. All four roles ran on `openrouter/openai/gpt-4.1-mini` with no GCP calls. Research recorded `unavailable` (`research model does not support grounding`, 0 queries) as designed; the trader returned a structured plan, `check_trade_plan` gave a real deterministic reason (`minimum net edge of 0.05 not met`), and the turn abstained. Actual estimated cost $0.0031220 against a $0.4789824 reserved ceiling; one public market capture; no orders; temporary journal removed. A first attempt with `--cost-budget 0.10` stopped at `cost_budget` before any cycle because the reserved ceiling still includes the 30-query grounding allowance when research cannot run. |
| 2026-10-15 | Local end-to-end paper chain: independent consumer `uv run uvicorn paper_consumer.app:app --host 127.0.0.1 --port 8080` with a temporary `CONSUMER_JOURNAL`; `CHRYSOPOEIA_EVENT_SINK=http://127.0.0.1:8080/push chrysopoeia cycle --config configs/openrouter.toml --snapshot <capture> --draft <draft> --journal <dir>` | Fixed the capture snapshot identity: it hashed `bids`, which `serialize_market_snapshot` and the record keys omit, so `load_capture_snapshot` could never reproduce the stored id and every `cycle --snapshot` failed `invalid snapshot`; the identity now covers only the persisted fields. A seeded draft produced an accepted plan on `openrouter/openai/gpt-4.1-mini`: `plan_checks` passed, review approved, and `trade_plan_ready` (`turn-e6bc9b2d…`) plus `turn_outcome` were published through the sink and acknowledged. The independent consumer recorded a paper fill in its own ledger (market 2589812, 12.0 shares at 0.75, stake 9.0, fee 0.18). No GCP calls; no orders. Estimated model cost ~$0.006 (0.0037208 accepted + 0.0025568 prior attempt); temporary journal and consumer ledger under a temp dir. |
| 2026-10-15 | Local `chrysopoeia run --config configs/openrouter.toml --max-cycles 1 --cost-budget 0.50 --interval-seconds 0` with `OPENROUTER_API_KEY` from `.router_key` (value never printed) and no event sink | Added a BYOK research provider: OpenRouter web search (Exa-backed, `plugins:[{id:"web"}]`) selected when the context model is an OpenRouter model; hits normalize into snapshot-bound external `EvidenceRecord`s, results are bounded and non-https/duplicate/malformed citations dropped, the research model call is reserved and settled in the cost ledger, and `research_allowance` now reserves only the active provider. One cycle reported `research: ok` with 5 cited external sources (fedratecalc.com, axios.com, thebostonreport.com) that the trader cited; it abstained (the proposal exceeded the per-market exposure limit). Actual estimated cost $0.0306796 against a $0.0789824 reserved ceiling; no GCP calls; no orders. |
| 2026-10-15 | Direct local calls to the trader's `analyze_stock_history` and `analyze_crypto_history` tools with a canonical snapshot in ADK state; no model call, platform, keys, or event sink | Yahoo Finance public chart fetched 30 AAPL daily bars; CCXT fetched 30 BTC/USD daily bars from Coinbase public OHLCV. Both returned bounded deterministic indicators (means/returns, SMA/EMA, RSI, stochastic %K/%D, ATR) and registered snapshot-bound evidence IDs for citation. Two public requests; no orders; no GCP. Stooq was not used because its endpoint returned a JavaScript verification page to the non-browser client. |
| 2026-10-16 | Direct trader-tool call to `analyze_polymarket_history` on `btc-updown-5m-1792212300`, plus `chrysopoeia polymarket-eval --journal <empty-local-journal> --event-url https://polymarket.com/event/btc-updown-5m-1792212300 --limit 5` | The tool fetched 10 resolved siblings from Gamma series `btc-up-or-down-5m` (`10684`), reported 40% Up, and registered snapshot-bound evidence. The evaluator loaded five resolved siblings (60% Up); their CLOB Up-price baseline Brier at each window start was 0.247025. No agent forecasts are in the local journal yet, so agent Brier is null. The supplied `1792212300` market itself is active/unresolved. All reads were public, local, and paper-only; no model or platform calls. |
| 2026-10-16 | Local `load_market_snapshot` on the live `btc-updown-5m-<current window>` market (no model, platform, or keys) | Before the fix every Up/Down market was rejected (`requires YES and NO outcomes`), so BTC 5m forecasts could never be recorded. After accepting Up/Down (Up = YES side) a second defect surfaced: capture time was taken before the network fetch, so a fresh book stamped milliseconds later was rejected as `stale`/after `captured_at`. With a 5 s skew allowance and `captured_at` raised to the book time, market 5727085 ("Bitcoin Up or Down - October 16, 7:05AM-7:10AM ET") captured with Up ask 0.79 and 21 levels. Public reads only. |
| 2026-10-16 | Local Vertex `gemini-3.5-flash` `chrysopoeia cycle --market https://polymarket.com/event/btc-updown-5m-<live window>` on 9 consecutive BTC 5m windows, temporary local journal, no event sink or platform | Exposed and fixed: (1) every financial/Polymarket-history tool call failed in real runs because ADK passes `State`, not a `MutableMapping`, so the tools returned "cycle context is unavailable" (unit tests used a dict); (2) model-chosen bar counts below 14 were rejected (now clamped); (3) CCXT Coinbase intermittently timed out loading its product catalogue (timeout raised to 20 s, trader pointed at Bitstamp); (4) abstentions recorded placeholder P(Up)=0.0 (trader now gives a genuine estimate; evaluator excludes 0/1 abstention placeholders); (5) checking an abstain plan returned a misleading "does not match" error. After the fixes the trader called `analyze_crypto_history(bitstamp, BTC/USD, 1m)` and produced reasoned estimates: P(Up)=0.45 vs Up ask 0.40 (edge below the 0.05 net minimum, abstained) and P(Up)=0.15 vs Up ask 0.68 (strong edge for Down, but YES-only so abstained). No bet was possible on these windows. One window hit a transient Vertex 503. ~$1.2 model spend; public reads only; no orders. |

## Two-sided paper verification (2026-10-17)

- Local live capture loaded distinct Up and Down token books for a BTC 5m
  window (Up ask 0.876, Down ask 0.122). These are real independent books, not
  complemented quotes.
- Two local Vertex cycle attempts returned no structured proposal and failed
  closed with no fills. A third local production cycle completed, called the
  CCXT crypto-history tool, and abstained with P(Up)=0.50. Recorded estimated
  cost for the completed turn was $0.17163075; the failed attempts' actual model
  spend was unavailable. No platform operations or real orders were run.
- Independently verified the external v2 boundary with a deliberately synthetic
  NO plan (not a model forecast): Harness captured market 5774405 and emitted a
  v2 NO event; the Consumer subprocess validated it, fetched fresh venue data,
  and recorded a $1 paper fill at Down price 0.49 for token
  `110989905685615221413447094250795581003563021459676813405234267222963102655254`.
  Temporary consumer journal was removed. This is contract/fill verification,
  not evidence of a profitable strategy or an agent-selected bet.
- Offline checks cover NO proposal → plan check → independent review → v2
  event, dual-book capture/reload, real NO depth/edge/exit quotes, token mismatch
  rejection, NO-winning settlement/replay, and retained v1 YES compatibility.

Deployment checks are recorded in [`../../platform/docs/deployment.md`](../../platform/docs/deployment.md).

## Agent-selected BTC paper bet (2026-10-17)

After commit `b5dfb91`, ran at most three local Vertex cycles, stopping at the
first fill. The first cycle returned no structured proposal and recorded a
failed turn. The second produced a reviewed YES/Up plan for
`btc-updown-5m-1792241700` (market `5775008`, 12:55–13:00 UTC): P(Up)=0.75,
stake $5, maximum entry 0.65. Two oversized attempts were rejected by policy
before the trader revised to a passing plan. The independent reviewer approved.
The in-process paper journal recorded 7.8125 Up shares at 0.64, entry fee $0.10,
total cost $5.10. This is an actual agent-selected paper fill, not a seeded draft.
The completed cycle's estimated model cost was $0.0807708. The journal books a
$0.7038528 conservative reservation for the failed first cycle; its actual
provider spend was unavailable. No event sink, platform operations, or real
orders were used. Initial public checks reported pending resolution. A later
Gamma check returned `resolved_yes`; the local journal was settled and replayed
with zero open positions and one winning trade. Settlement proceeds after the
paper simulator's settlement fee were $7.65625, yielding realized paper P&L of
$2.55625 (+50.1% on the $5.10 entry cost), before model costs. The journal books
$0.78462360 in total model costs, including the conservative failed-turn
reservation; this is not a confirmed provider bill. This single winning trade
verifies the local paper lifecycle, not strategy profitability.
Journal: `/var/folders/z8/cpj4kjks381d6vkbf5wdff5h0000gp/T/opencode/btc-paper-bets-z7m6pw9w`.

Next local task: collect a bounded set of forward BTC 5m forecasts and score
them with `polymarket-eval`, reporting Brier, market baseline, coverage, model
failures, and paper P&L separately. Keep platform execution explicit and off.

## Collection preparation (2026-10-18)

Operator approved the raw-event Platform archive and local series-selection
capability, explicitly excluding the 20-window run or any forecasting session.
Platform deployment and one synthetic publish/query passed; evidence and
retention/IAM boundaries are in
[`../../platform/docs/deployment.md#event-archive`](../../platform/docs/deployment.md#event-archive).

`uv run python -` called `discover_markets(series="btc-updown-5m", now=<UTC>)`
once and asserted the result matched the current 300-second clock window.
At `2026-10-18T06:58:37.265645+00:00`, one public Gamma GET returned market
`5798498`, URL `https://polymarket.com/event/btc-updown-5m-1792306500`, closing
at 07:00 UTC. One GET bounded to 5 s / 256 KiB, zero model calls, estimated
cost $0, no journal, paper fill, order, or temporary artifact.

Offline checks: `uv sync --all-groups --all-extras`, all 338 Harness unit tests,
`uv run ruff check .`, `uv run ty check .`,
`uv run chrysopoeia validate --json`, and agent import passed. Eight Platform
contract tests passed. Cadence tests advance a fake clock and verify that a
failed capture waits for the next boundary. CLI tests cover the default 300 s
series cadence and rejection of incompatible intervals. A real-model
`run --series` session remains unverified by explicit operator choice; do not
claim the forward benchmark is complete. See [collection usage](collection.md).

## Config-only operating settings (2026-10-18)

The operator approved removing operating-setting flags and migrating the
deployed job to a bundled two-cycle config, including one bounded two-cycle
paper verification. This does not authorize the BTC benchmark. The earlier
`--series` CLI syntax is historical: current selection is `[venue].series` in
`configs/btc5m.toml`. Other historical commands above retain their original syntax.

Offline gates passed: `uv sync --all-groups --all-extras`, all 341 Harness
tests, `uv run ruff check .`, `uv run ty check .`,
`uv run chrysopoeia validate --json`, agent import, and `uv build`. All four
bundled TOML profiles loaded. Tests cover removed flags, strict config bounds,
profile routing into the loop/cycle, zero budget stopping before external work,
and rejecting external exposure in the journal-owned run loop. Ten Platform
contract tests cover the bundled config and setting-free job arguments.

The Platform verification uses `configs/platform.toml`: at most two cycles,
$1.50 conservative session cost ceiling, $5 daily model budget, $100 paper loss
halt, a 60-minute configured session window bounded externally by the existing
900-second job task timeout, and no task retries. Expected actual completed-cycle
cost is about $0.35; provider billing is not measured. The separate BTC profile
is only validated offline, not executed.

The built amd64 image also passed both default/platform `validate --json`
checks and rejected the removed `--max-cycles` flag with exit 2 before model
work. Registry upload exceeded the initial 120-second build-command timeout
and a separate 600-second push timeout; no job update was applied during these
attempts. The migration's deployed boundary is not verified until the image
pin, job update, and bounded execution evidence are recorded below.

After the final large layer uploaded, the manifest request returned EOF; one
manifest retry succeeded without rebuilding. Image
`sha256:d6c13fc6fcababcae0c62066513b0d55c447af0fb86f460c5176d6589a286840`
was pinned through Pulumi. Only the job image, config environment variable,
and arguments changed; 18 other resources remained unchanged, including the
protected/retained archive. Post-apply preview reported 19 unchanged.

One approved invocation of `platform/run.sh job
--args=run,--journal=/mnt/journal/config-only-20261018-01 --wait` created execution
`chrysopoeia-cycle-local-nr6tj`, which exited successfully with
`stop_reason=max_cycles` and `cycles_run=2`. The first turn filled a $1 paper
plan on market `5315588` at 0.14 (7.142857 shares, $0.02 fee, $1.02 total cost).
Its estimated model cost was $0.17610935. The second turn failed and booked the
conservative $0.7038528 reservation; actual provider spend is unknown. Total
booked model cost was $0.87996215, below the $1.50 session ceiling. The report
showed realized P&L $0 and marked unrealized P&L -$0.11, before model costs.
No win rate or settled profitability claim is supported.

The journal recorded two admitted/finished turns, one fill, and two outbox
acknowledgements. A single date-filtered BigQuery query capped at 100 MiB
confirmed one copy each of `outcome-4c831aa9a771c397bb8ba4e1` (`turn_outcome`)
and `turn-4c831aa9a771c397bb8ba4e1` (`trade_plan_ready`), with matching attributes;
the original synthetic archive row remained present. The failed turn did not
produce an outcome event. Query/storage billing was not measured; incremental
verification cost beyond model work is expected negligible.

The authoritative journal is retained at
`gs://PROJECT_ID-chrs-journals-local/config-only-20261018-01/chrysopoeia.jsonl`.
It contains one open paper position; the finished job is not monitoring it.
No real orders, Consumer deployment, scheduler, or BTC benchmark were run.
This verifies deployed config loading, caps, paper behavior, and event archival;
it does not verify consistent model success or the separate BTC profile's live
forecast quality.

## BTC-only enforcement and blocked benchmark (2026-10-18)

Operator hard requirement: during development BTC 5m Up/Down is the only
automated venue market. `[venue].series` is now required and restricted to
`btc-updown-5m`; the CLI discovery/run path and the trader's discovery tool are
bound to it. `uv run chrysopoeia discover` returned exactly the current window
(market `5818403`, `Bitcoin Up or Down - October 18, 9:50AM-9:55AM ET`), one
public GET, no model calls.

Attempts under the required binding exposed a pre-existing trader failure:

| Run | Windows | Outcome | Booked cost |
| --- | --- | --- | --- |
| Deployed job `chrysopoeia-cycle-local-jj49n` (2-cycle smoke) | `5818529`, `5818549` | both turns failed, no proposal | $1.4077056 (2 × reservation) |
| Local `btc5m` run `~/chrysopoeia-journals/btc5m-20261018T1405` | `5818582` | one turn failed, no proposal; stopped cleanly (`stop_reason=stopped`) | $0.7038528 |

All three failed with `pydantic ValidationError ... ProposalOutput ... input_value=None`
raised at the downstream workflow node, i.e. the trader agent ended without a
structured proposal. No `turn_outcome` or `trade_plan_ready` events were
produced, so nothing from these turns reached the archive. Actual provider spend
is unknown because a failed turn books its full conservative reservation.

A contributing deployment defect was found and fixed: the image installed the
wheel without the lockfile, resolving ADK 2.12.0/pydantic 2.14.1 versus the
verified lock at ADK 2.8.0/pydantic 2.13.4. `platform/build.sh` now exports the
frozen lock and installs it with `--no-deps`; the rebuilt image reports the
locked versions and validates both profiles. The job was repinned and one
`validate --json` execution (`chrysopoeia-cycle-local-7jccr`) succeeded. The
local failure above used the verified lock, so drift is not the sole cause.

The 20-window forward benchmark is therefore **blocked**: further windows would
spend the ceiling without producing forecasts. Fix the trader's missing-output
path (for example, drop redundant discovery/capture tools from the
already-captured cycle or add one bounded retry), verify with two windows, then
rerun the benchmark with a fresh journal. No Brier/coverage/P&L evidence exists
for this sample.

## Missing trader output diagnostics (2026-10-19)

Operator approved diagnostics only, not a new model run, retry, budget change,
or tool change. A failed turn can now carry an optional `failure` object on
its existing `turn_finished` journal record: `error_code`, `message`, and
`model_calls`. The count is the cycle's cost-ledger reservations, including
research/reviewer calls when present, not confirmed provider requests or billing.
Denied calls that never reserve are not counted.

Only recognized Harness cost error codes and allowlisted deterministic reasons
are recorded. Unknown provider codes/messages or missing output produce
`TRADER_OUTPUT_MISSING` with cause unavailable; prompts, provider bodies, and
model text are not copied. This remains a local diagnostic, not a forecast or
published outcome. Existing journals replay without requiring the optional field.
Failure costs, admission, execution policy, cancellation, and no-retry behavior
are unchanged.

Offline fake-model checks exhaust a one-call ceiling through the real ADK loop,
reproduce `ProposalOutput=None`, and assert that replayable failed-turn evidence
contains `MODEL_COST_POLICY_DENIED`, the ceiling reason, and one reserved call.
Separate checks cover empty trader output and rejection of arbitrary provider
text.

One approved local diagnostic cycle ran at 2026-10-19T08:56Z on the default
BTC profile (`max_cycles=1`, no event sink): market capture, Vertex calls, and
the full paper decision completed, the turn **abstained** (not failed), and
$0.21271855 actual estimated model cost was booked under the $5 session budget.
No `failure` field was recorded because the turn did not fail. One public
window, no orders, no event sink, no platform change; the temporary journal is
retained at `~/chrysopoeia-journals/diag-20261019T085634`.

This shows the missing-output failure is intermittent, not deterministic, and
the paid path still works. The new failure branch remains live-unverified
because no failure occurred; the 2026-10-18 cause is still unknown. All 343
offline unit tests, Ruff, ty, config validation, agent import, dependency sync,
and `git diff --check` passed. Do not treat one abstention as forecast-quality
or benchmark evidence; no Brier/coverage/P&L sample exists.
