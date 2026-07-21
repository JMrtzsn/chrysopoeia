# Chrysopoeia Development

The product scope and safety contract are defined in `README.md`. Preserve those
boundaries unless the user explicitly changes them.

Context and memory boundaries are defined in `docs/context-engineering.md`.
The managed RAG and deployment design is defined in `docs/gcp-architecture.md`.
Graph ownership, state, scheduling, and cost gates are defined in
`docs/agent-graphs.md`.

## Stack

- Python 3.10 or later.
- Google Agent Development Kit for Python.
- `uv` for dependency and environment management.
- Gemini through `GOOGLE_API_KEY` by default; other providers may use ADK model connectors.

## Commands

- Install: `uv sync`
- Test: `uv run python -m unittest discover`
- Run CLI: `uv run adk run chrysopoeia`
- Run development UI: `uv run adk web --port 8000`

## Architecture

- Keep the root agent in `chrysopoeia/agent.py` while the application is small.
- Separate trader and reviewer agents because their responsibilities and tool
  permissions differ; keep order execution outside both.
- Use ordinary typed Python functions for discrete tools.
- Use an ADK graph workflow for the deterministic propose, review, risk-check,
  execute, evaluate, and lifecycle sequence.
- Use ADK session state for conversation-scoped data; add persistent storage only when required.
- Store durable agent versions, trading records, metrics, lifecycle events, and
  lessons in Cloud SQL for PostgreSQL.
- Use Agent Platform RAG Engine with its default `RagManagedDb` for vector
  retrieval over documents, research, and validated procedural lessons.
- Use Agent Platform Memory Bank for extracted and consolidated long-term
  memories; do not treat it as authoritative trading storage.
- Keep session state, authoritative trading records, external evidence, and
  curated memory distinct. Never use memory as the source of truth for money or
  lifecycle decisions.
- Give trader and reviewer agents separate histories. Exchange only validated,
  structured proposals and reviews tied to one canonical snapshot ID.
- Generate and consolidate memories after completed cycles or resolutions, not
  on the trading hot path. Persist provenance and invalidate stale lessons.
- Prefer the standard library, then existing ADK features. Do not add frameworks around ADK.
- Configure providers at the agent model boundary. Do not spread provider-specific logic through tools.

## Agent And Tool Rules

- Give every agent a unique, descriptive name, description, and concise instruction.
- Type tool inputs and outputs and write accurate docstrings ADK can expose to the model.
- Treat tool arguments as untrusted input: validate values and bound work before external calls.
- Return safe, actionable tool failures without exposing secrets or internal details.
- Require ADK confirmation before destructive, costly, or externally visible actions.
- Keep deterministic business rules in Python, not prompts.
- Do not use an LLM where ordinary code can produce the correct result.

## Security

- Never commit API keys, credentials, user data, or `.env` files.
- Read secrets from environment variables and fail clearly when required configuration is missing.
- Do not place secrets or sensitive user data in prompts, logs, session state, traces, or tool results.
- Apply authorization at each tool boundary; agent instructions are not a security control.
- Google Search and the ADK web UI are development capabilities, not production trust boundaries.

## Verification

- Run tests and import the agent before considering a change complete.
- Add the smallest test that checks observable behavior for non-trivial tools, routing, or workflow logic.
- Tests must not require live model calls or real credentials unless explicitly marked as integration tests.
