# Harness Work Unit

Loop internals: paper-cycle core, agents, accounting, CLI, and the host
runtime adapter. This is application code — infrastructure lives in the
sibling `platform/` folder and is a different work unit.
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
- Journal path/record format is here; the platform only selects *where* it
  lives (`/mnt/journal`), not what it contains.

## Local verification gates (all from this folder, pre-commit enforced)

```sh
uv sync --all-groups --all-extras
uv run python -m unittest discover
uv run ruff check .
uv run ty check .
uv run chrysopoeia validate --json
```
