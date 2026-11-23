# Chrysopoeia

An LLM trading-agent harness that forecasts public
[Polymarket](https://polymarket.com) markets and paper-trades them under
operator-set limits. A trader agent proposes or abstains, a separate reviewer
agent checks the proposal, and deterministic Python owns risk, cost, fills, and
accounting. **Paper only:** there is no authenticated execution.

Current automation forecasts CS2 and Dota 2 match-winner markets. The platform
profile paper-trades them; the other bundled profiles are scored-only, so
forecasts are recorded and scored but policy blocks every fill.

## Layout

| Folder | Role |
| --- | --- |
| [`harness/`](harness/) | Agent loop (Google ADK), market capture, risk policy, paper journal, CLI |
| [`consumer/`](consumer/README.md) | Independent paper-only consumer of `trade_plan_ready` events with its own ledger |
| [`observer/`](observer/README.md) | Read-only insights over the BigQuery event archive |
| [`platform/`](platform/docs/deployment.md) | Terraform for Cloud Run, Pub/Sub, BigQuery, and scheduling on GCP |
| [`contracts/`](contracts/) | Versioned JSON schemas shared between units as data |

Units communicate only via events (one Pub/Sub topic with an outbox and
idempotent consumers) and never import each other's code.

## Quickstart

Requires Python 3.10+ and [`uv`](https://docs.astral.sh/uv/).

```sh
cd harness
uv sync --all-groups --all-extras
uv run chrysopoeia validate --json
uv run chrysopoeia --help
```

The main flow is `discover` → `capture` → `cycle`; `run` starts a bounded,
journal-backed session, and `polymarket-eval` computes Brier scores once markets
resolve.

Models default to Vertex AI Gemini (uses your ambient Google project; set
`GOOGLE_CLOUD_PROJECT` if needed). To use another provider, see
[`configs/openrouter.toml`](harness/configs/openrouter.toml) and supply the key
only via its standard environment variable, such as `OPENROUTER_API_KEY`. All
operating limits live in TOML config, not flags. Model calls cost money, so set
the session cost limits before live runs.

## Docs

- [Product specification](.agents-cli-spec.md): scope and safety contract
- [Architecture](harness/docs/architecture.md) and [paper accounting](harness/docs/accounting.md)
- [Collection](harness/docs/collection.md) and [verification](harness/docs/verification.md)
- [Deployment](platform/docs/deployment.md)
- Roadmaps: [harness](harness/ROADMAP.md), [platform](platform/ROADMAP.md),
  [observer](observer/ROADMAP.md), [consumer](consumer/ROADMAP.md)
