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
- `configs/` (complete, validated operator profiles; no setting-flag overrides)
- `pyproject.toml`, `uv.lock`
- `.githooks/` (offline gates)
- `agents-cli-manifest.yaml` (Agents CLI prototype surface; spec-rooted)

## Off-limits

- `platform/**` (GCP deployment shape; needs operator approval to touch)
- Any provisioning or mutation of cloud resources: no `gcloud`, `pulumi`, or
  infrastructure SDK calls. Data-plane publishing to a configured event sink is
  allowed (rule from `../platform/docs/deployment.md`).

## Contract published to the platform

- Container image built from the harness wheel (`uv build`) — one per code
  change; the platform consumes the resulting image digest pin via Pulumi.
- CLI contract: `chrysopoeia <command>` reading `--journal /mnt/journal` and
  `--config` from the env override `CHRYSOPOEIA_CONFIG` or repo default.
- Session capital/limits/cadence and risk limits come only from required
  `[session]`/`[risk]` config sections. Venue selection and public discovery
  limits come from `[venue]`; CLI setting overrides are not supported. Keep
  `--config`, `--journal`, target/input/output flags, JSON formatting, and
  `--stop-file` as invocation controls. The Platform profile is bundled beside
  the wheel and selected as `/etc/chrysopoeia-platform.toml`.
- The checked-in model is `gemini-3.5-flash`. Vertex calls use the `us` model
  endpoint; this is independent of the platform's Cloud Run resource region.
- The paper journal path/record format, optional outbox, and direct event
  publishing are here; platform selects *where* the journal lives
  (`/mnt/journal`) and configures the sink. It never parses the journal or
  imports Harness modules.

## Local verification gates (all from this folder, pre-commit enforced)

```sh
uv sync --all-groups --all-extras
uv run python -m unittest discover
uv run ruff check .
uv run ty check .
uv run chrysopoeia validate --json
```
