# Observer Work Unit

Independent read-only insight over the Platform-managed BigQuery event archive
lives here. The observer consumes Harness and Consumer event schemas as data. It
never imports their packages, reads their journals, provisions infrastructure,
publishes events, signs, or orders. The archive is an analytics copy, never a
financial ledger or an authority for risk, fills, balances, or lifecycle.

## Owned

- `observer/`, `tests/`, `pyproject.toml`, `uv.lock`
- `Dockerfile`, `.dockerignore`, `build.sh` (build-only; publishing is separate)
- `README.md`

## Boundaries

- v1 queries BigQuery at read time and retains no projection or authoritative
  store. Results are bounded aggregates, not raw event content.
- Use ambient authentication and a read-only identity. Keep table identifiers
  validated, partition filters mandatory, query bytes capped, and errors safe.
- Event-schema changes belong to their owning work units and require separate
  coordinated approval. Platform deployment and IAM changes are not included.

## Verification

```sh
uv sync --all-groups
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ty check .
```

No check calls live services by default. Live BigQuery verification, image
publication, or deployment requires separate operator approval.
