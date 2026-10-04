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

Deployment checks are recorded in [`../../platform/docs/deployment.md`](../../platform/docs/deployment.md).
