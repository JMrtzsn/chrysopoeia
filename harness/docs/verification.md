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

Model runs used ambient Vertex ADC unless noted, with operator approval for cost
or external effects and temporary local files removed. Costs are estimated model
cost. Rows are condensed; full run details are in git history.

| Date | What was verified | Result |
| --- | --- | --- |
| 2026-10-30 | `turn_outcome` v4 reserved-cost acceptance: CS2 capture, one cycle publishing to Pub/Sub, one Observer query | Pass. Abstained; $0.180846 actual of $1.43376 reserved; archive and Observer returned the exact actual/reserved values. 386 Harness + 10 Observer tests passed. |
| 2026-10-26 | Esports pilot: CS2/Dota 2 capture and cycles with research | Pass after fix. Grounded research pushed input past the 8192 ceiling (`MODEL_COST_USAGE_INVALID`); reservation now uses the policy input ceiling and esports raises it to 32768. Retries must recapture (journal idempotency). ~$2–3; no orders. |
| 2026-10-26 | Liquidity-aware sizing (`plan_capacity`, `check_risk`), offline | Pass (381 tests). Public-book live check and image redeploy pending. |
| 2026-10-23 | Self-learning rollout steps 1–2: image with `[history]`/`[context_learning]`, one two-cycle deployed run | Pass. $0.1255 actual, one paper fill; history aggregate cited; 20-outcome learning gate correctly stayed closed. |
| 2026-10-23 | Bounded thinking (2048) and 3072 output ceiling for context-profile agents | Pass. Learning cycle abstained at $0.0366 actual; curator/reviewer created a profile pinned by `turn_outcome` v3. 376 tests. |
| 2026-10-22/23 | Context-profile pipeline live: archive publish, history IAM, BTC cycle, profile creation | Pass after fixes (profile agents hit MAX_TOKENS from thinking; history query double backticks). ~$0.10; synthetic rows retained as labeled evidence. |
| 2026-10-22 | Context-profile loop, offline | Pass (374 tests). `[context_learning]` disabled by default pending live check. |
| 2026-10-21 | `turn_outcome` v3, `consumer_outcome` v1, bounded BigQuery query, offline | Pass (Harness 365, Consumer 38, Platform 12 tests). |
| 2026-09-15 | `discover` and `capture` on public Gamma/CLOB | Pass. ≤3 pages/75 records, 5 s / 256 KiB caps; no model cost. |
| 2026-09-15 | `cycle` on a captured market, then identical repeat | Pass. Abstained (~$0.0023); repeat made no call or records. |
| 2026-09-15 | ~13 seeded one-cycle paper runs | Pass. Abstain, review, rejection, fill, and preemption paths observed; ~$0.03. |
| 2026-09-15 | `settle` from public resolution | Pass. Market 20 settled `resolved_no`; ambiguous markets refused. |
| 2026-09-15 | `mark` on an open position | Pass. Failed capture wrote no mark. |
| 2026-09-27 | OpenRouter via ADK registry: `discover`, `capture`, `cycle` | Pass. Abstained, $0.0048. |
| 2026-09-30 | Recovery of an unfinished turn, then repeat | Pass. Prior turn abandoned before model calls; ~$0.0022. |
| 2026-09-30 | Two-cycle `run` with stop file | Pass. Two abstentions (~$0.0045); stop file and changed target refused. |
| 2026-10-05 | Paper `evaluate_exits` on a public snapshot | Pass. Time-triggered close from captured bids; $0. |
| 2026-10-06 | Vertex smoke with `gemini-flash-latest` at `us-central1` | Fail (404, unsupported pair); superseded below. |
| 2026-10-06 | Vertex `gemini-3.5-flash` diagnostic cycle | Fail/inconclusive (`TypeError`); no order. |
| 2026-10-06 | Two Vertex `gemini-3.5-flash` tool-integration cycles | Pass. Abstain and fail-closed `rejected`; ~$0.028. |
| 2026-10-07 | Synthetic plan through CLI `consume` | Fail closed (stale book); retried below. |
| 2026-10-07 | Same `consume` workflow retry | Pass. Filled from fresh quote; duplicate consume made no write. $0. |
| 2026-10-08 | OpenRouter `gpt-4.1-mini` in-memory cycle | Pass. Approved; $0.0017. |
| 2026-10-08 | Platform `drain()` against a temporary Pub/Sub topic | Pass. One publish/ack; temporary resources deleted; ~$0. |
| 2026-10-12 | Direct HTTP publishing into a local Consumer | Pass. Outbox acked; Consumer filled from its own quote. Earlier attempts found `--draft`/`--context`, project, and reviewer-reason bugs (≤$0.28). |
| 2026-10-12 | Vertex cycle with the previously crashing draft | Pass. Rejected by review; $0.046. |
| 2026-10-12 | `events.publish()` to a temporary Pub/Sub topic | Pass. Payload and `event_id` matched; resources deleted; ~$0. |
| 2026-10-12 | Vertex cycle, outcome into local Consumer | Pass. Plan-check rejection; Consumer ignored outcome (204). $0.059. |
| 2026-10-14 | `plan_inputs` and discovery fixes, OpenRouter runs | Pass. 5/5 turns reached real edge checks; discovery ordered by 24h volume. ~$0.03–0.05/run. |
| 2026-10-14 | Vertex Google Search research, four turns | Pass. Research `ok`, evidence cited; all abstained. $0.34. |
| 2026-10-14 | Deployed job after plan-check schema fix | Pass. Accepted plan, events acked, paper fill; $0.12. Two earlier attempts hit transient Vertex 503. |
| 2026-10-15 | BYOK OpenRouter for all roles | Pass. Research `unavailable` as designed; abstained; $0.0031. |
| 2026-10-15 | Local end-to-end paper chain into independent Consumer (snapshot identity fix) | Pass. Accepted plan published; Consumer filled in its own ledger; ~$0.006. |
| 2026-10-15 | OpenRouter web-search research provider | Pass. 5 cited sources; abstained; $0.031. |
| 2026-10-15 | `analyze_stock_history` / `analyze_crypto_history` tools | Pass. Yahoo and CCXT bars returned bounded indicators. |
| 2026-10-16 | `analyze_polymarket_history` and `polymarket-eval` on BTC 5m | Pass. Baseline Brier 0.247; no agent forecasts yet. |
| 2026-10-16 | Up/Down market capture | Pass after fixes (Up/Down acceptance, 5 s capture skew). |
| 2026-10-16 | Nine BTC 5m Vertex cycles | Pass after five tool fixes (ADK `State`, bar clamp, CCXT timeout, abstention probability, abstain check). Abstained; ~$1.2. |

## Two-sided paper verification (2026-10-17)

- Live capture loaded independent Up and Down books for a BTC 5m window.
- Two cycles failed closed with no proposal; a third abstained at P(Up)=0.50
  ($0.17).
- A deliberately synthetic NO plan produced a v2 event; the Consumer validated
  it and recorded a $1 paper fill at Down 0.49. This verifies contract and fill,
  not strategy.
- Offline checks cover the NO path, dual-book capture, NO quotes, token mismatch
  rejection, NO settlement/replay, and v1 YES compatibility.

Deployment checks are recorded in [`../../platform/docs/deployment.md`](../../platform/docs/deployment.md).

## Agent-selected BTC paper bet (2026-10-17)

Within three bounded local cycles, the second produced a reviewer-approved
YES/Up plan (P(Up)=0.75, $5 stake) after policy rejected two oversized attempts.
The paper journal filled 7.8125 shares at 0.64 ($5.10 total). The market
resolved YES; realized paper P&L was $2.55625 before model costs. Booked model
costs were $0.7846, including a conservative failed-turn reservation. This
verifies the local paper lifecycle, not profitability.

## Collection preparation (2026-10-18)

The operator approved the Platform raw-event archive and series selection, but
not a forecasting session. Archive evidence is in
[`../../platform/docs/deployment.md#event-archive`](../../platform/docs/deployment.md#event-archive).
One public GET confirmed series discovery returns the current 300-second BTC
window. Offline: 338 Harness and 8 Platform tests passed. A real-model series
session remains unverified; see [collection usage](collection.md).

## Config-only operating settings (2026-10-18)

Operating-setting flags were removed; selection is `[venue].series` in the
bundled TOML (older commands above keep their original syntax). Offline gates
passed (341 tests, `uv build`). `configs/platform.toml` bounds the deployed job
to two cycles, a $1.50 session ceiling, $5 daily model budget, $100 paper loss
halt, 900-second task timeout, and no retries.

One deployed two-cycle run exited at `max_cycles`: one $1 paper fill and one
failed turn, $0.880 booked (under $1.50). Both events reached BigQuery. The
journal is retained at
`gs://PROJECT_ID-chrs-journals-local/config-only-20261018-01/chrysopoeia.jsonl`
with one unmonitored open position. This does not verify consistent model
success or BTC forecast quality.

## BTC-only enforcement and blocked benchmark (2026-10-18)

`[venue].series` was required and restricted to `btc-updown-5m`. One deployed
two-cycle smoke and one local run all failed with `ProposalOutput=None` (no
structured proposal, $2.11 booked as reservations). Image dependency drift was
found and fixed (the image now installs the frozen lock), but the local failure
used the verified lock, so drift was not the sole cause. The 20-window benchmark
was blocked pending a fix; no Brier/coverage/P&L evidence exists for it.

## Missing trader output diagnostics (2026-10-19)

A failed turn can carry an optional `failure` object on `turn_finished`:
`error_code`, `message`, and `model_calls` (cost-ledger reservations, not
provider requests). Only recognized Harness codes and allowlisted reasons are
recorded; otherwise `TRADER_OUTPUT_MISSING`. Prompts, provider bodies, and model
text are never copied. Existing journals replay unchanged; failure costs and
no-retry behavior are unchanged.

Offline fake-model checks reproduce `ProposalOutput=None` and assert the
recorded failure. One live diagnostic cycle abstained ($0.213), so the failure
is intermittent and the failure branch remains live-unverified (343 tests).

## Research switch and cost reduction (2026-10-19)

`[research] enabled` (default `true`) is disabled in `configs/btc5m.toml` and
`configs/platform.toml`; the trader keeps its OHLCV tool. One bounded cycle with
research off abstained at $0.0443 versus $0.2127 with research on (about 79%
lower; grounding was about 72% of that cost). The deployed job was repinned and
a no-model `validate --json` confirmed `research={'enabled': False}`.

## BTC window baseline and forecast offset (2026-10-19)

Each BTC cycle attaches a deterministic baseline evidence record (window open,
last price, delta bps, seconds remaining, 1-minute volatility, normal-approx
P(Up)); it is evidence, never instruction. `[venue].forecast_offset_seconds`
(120 in BTC profiles) is the minimum elapsed window time before forecasting,
not an exact schedule. Offline coverage passed (354 tests). Two live cycles
($0.026, $0.050) found and fixed a stale-price bug; the second attached a
correct baseline. No multi-window run has been scored since.
