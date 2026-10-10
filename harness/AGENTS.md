# Harness Work Unit

Paper-cycle core, agents, paper accounting, deterministic policy, and the host
runtime adapter live here. The harness owns the `trade_plan_ready` event contract,
shared schema data under `../contracts/`, and producer. Local `consume` remains a
development consumer only. The deployed paper consumer in `../consumer/` owns
its effects and ledger; deployment adapters live in sibling `platform/`.
Ordered harness work lives in `ROADMAP.md`.
The current and proposed harness architecture map lives in
`docs/architecture.md`; update it when a major boundary or flow changes.
Unapproved future ideas are consolidated in `docs/proposals.md`.

## Owned

- `chrysopoeia/` (runtime-neutral core + ADK adapter)
- `tests/`
- `chrysopoeia.toml` (checked-in operator configuration authority)
- `pyproject.toml`, `uv.lock`
- `.githooks/` (offline gates)
- `agents-cli-manifest.yaml` (Agents CLI prototype surface; spec-rooted)

## Off-limits

- `platform/**` (GCP deployment shape; needs operator approval to touch)
- Any `gcloud`, `pulumi`, or GCP-SDK invocation from application code (the
  harness never provisions or mutates cloud resources; rule from
  `../platform/docs/deployment.md`)

## Contract published to the platform

- Container image built from the harness wheel (`uv build`) — one per code
  change; the platform consumes the resulting image digest pin via Pulumi.
- CLI contract: `chrysopoeia <command>` reading `--journal /mnt/journal` and
  `--config` from the env override `CHRYSOPOEIA_CONFIG` or repo default.
- The checked-in model is `gemini-3.5-flash`. Vertex calls use the `us` model
  endpoint; this is independent of the platform's Cloud Run resource region.
- The paper journal path/record format and optional outbox are here; platform
  selects *where* it lives (`/mnt/journal`), not what it contains. Platform may
  use only the `outbox-pending`/`outbox-ack` CLI contract to publish through
  Pub/Sub. It never parses the journal or imports Harness modules.

## Local verification gates (all from this folder, pre-commit enforced)

```sh
uv sync --all-groups --all-extras
uv run python -m unittest discover
uv run ruff check .
uv run ty check .
uv run chrysopoeia validate --json
```
