# Chrysopoeia

An experiment: can an LLM agent find an edge on
[Polymarket](https://polymarket.com) prediction markets? A trader agent
researches a market and proposes a trade or abstains, a separate reviewer agent
checks the proposal, and deterministic Python owns risk, cost, fills, and
accounting. **Paper trading only:** there is no authenticated execution.

**Status: concluded.** The answer was no. See [Results](#results).

## Results

Automated runs forecast CS2 and Dota 2 match-winner markets with
`gemini-3.5-flash` and Google Search grounding, Nov 12–18 2026.

| Measure | Result |
| --- | --- |
| Paper trading | 11 settled trades, 5 wins, −$18.03 on $49.98 staked |
| Model cost | $18.51 for 62 turns (~$0.30 per turn) |
| Forecast accuracy, 24 resolved markets (Brier, lower is better) | Agent 0.268 vs market price at the same moment 0.251 |
| Agent improvement over market, 90% bootstrap interval | −0.017 [−0.041, +0.006] |

The agent's probabilities sat on average 5.6 points from the market price: it
mostly echoed the market and added noise. Public research is information the
market has already priced, and prediction markets are zero-sum after fees, so
without an informational edge there is nothing to harvest. Model cost alone was
37% of the amount staked, so even a break-even forecaster would have lost
money. The experiment was
stopped under its pre-agreed rule: continue only if the agent beat the market
with a 90% interval above zero.

## What is reusable

- Trader and reviewer as separate agents with distinct histories; neither has
  execution authority.
- Deterministic risk, cost, and accounting policy outside the model, with a
  per-session cost ceiling enforced before every model call.
- An append-only paper journal with an event outbox; independent consumers that
  share only versioned JSON schemas, never code.
- Gated Terraform deploys: offline gates, saved plan, policy check, apply only
  that plan.

## Layout

| Folder | Role |
| --- | --- |
| [`harness/`](harness/) | Agent loop (Google ADK), market capture, risk policy, paper journal, CLI |
| [`consumer/`](consumer/README.md) | Independent paper-only consumer of `trade_plan_ready` events with its own ledger |
| [`observer/`](observer/README.md) | Read-only insights over the BigQuery event archive |
| [`platform/`](platform/docs/deployment.md) | Terraform for Cloud Run, Pub/Sub, BigQuery, and scheduling on GCP |
| [`contracts/`](contracts/) | Versioned JSON schemas shared between units as data |

## Quickstart

Requires Python 3.10+ and [`uv`](https://docs.astral.sh/uv/).

```sh
cd harness
uv sync --all-groups --all-extras
uv run chrysopoeia validate --json
uv run chrysopoeia --help
```

The main flow is `discover` → `capture` → `cycle`; `run` starts a bounded,
journal-backed session, and `polymarket-eval` scores forecasts against the
market once markets resolve. Models default to Vertex AI Gemini (set
`GOOGLE_CLOUD_PROJECT` if needed); other providers are configured as in
[`configs/openrouter.toml`](harness/configs/openrouter.toml), with keys only in
environment variables. Model calls cost money; set the session cost limits
before live runs.

## Docs

- [Product specification](.agents-cli-spec.md): scope and safety contract
- [Architecture](harness/docs/architecture.md) and [paper accounting](harness/docs/accounting.md)
- [Collection](harness/docs/collection.md) and [verification policy](harness/docs/verification.md)
- [Deployment](platform/docs/deployment.md)

## License

[MIT](LICENSE)
