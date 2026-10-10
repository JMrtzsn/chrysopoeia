# Consumer Work Unit

Independent paper-only consumption of the Harness-owned `trade_plan_ready` v1
data contract lives here. It owns its journal, quote checks, paper entries,
exits, settlements, HTTP service, tests, project, and container. It never imports
`chrysopoeia`, invokes Harness CLI, reads Harness journals, signs, or orders.

## Owned

- `paper_consumer/`, `tests/`, `scripts/`, `pyproject.toml`, `uv.lock`
- `Dockerfile`, `build.sh`, `README.md`, `ROADMAP.md`

The shared schema at `../contracts/trade_plan_ready.v1.schema.json` is owned by
Harness and consumed as data. Contract changes require coordinated approval.

## Verification

```sh
uv sync --all-groups
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ty check .
```

No check calls public services by default. Live verification, image publication,
or deployment requires separate operator approval.
