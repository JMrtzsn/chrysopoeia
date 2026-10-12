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

Deployment checks are recorded in [`../../platform/docs/deployment.md`](../../platform/docs/deployment.md).
