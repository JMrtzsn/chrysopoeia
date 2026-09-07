# Chrysopoeia Development

The product scope and safety contract are defined in `README.md`. Preserve those
boundaries unless the user explicitly changes them.

Context and evidence boundaries are defined in `docs/context-engineering.md`.
The optional managed deployment profile is defined in
`docs/gcp-architecture.md`. Current graph ownership, state, and cost gates plus
future graph prerequisites are defined in `docs/agent-graphs.md`.
The product specification is `.agents-cli-spec.md`; development and release
gates are defined in `docs/development-lifecycle.md`.

## Stack

- Python 3.10 or later.
- Google Agent Development Kit for Python as the current agent-runtime adapter.
- `uv` for dependency and environment management.
- Gemini through `GOOGLE_API_KEY` by default; configure alternatives only through
  connectors supplied by the selected runtime adapter (ADK today).

## Commands

- Install: `uv sync`
- Test: `uv run python -m unittest discover`
- Run CLI: `uv run adk run chrysopoeia`
- Run development UI: `uv run adk web --port 8000`

## Architecture

- Keep core canonical snapshots/evidence, proposals/reviews, risk/cost policy,
  paper quote/fill, workflow transitions, and audit/evaluation requirements
  runtime-neutral.
- Keep the root agent in `chrysopoeia/agent.py` while the application is small.
- Treat ADK `Agent`, `Workflow`, callbacks, ToolContext/session state, and Agents
  CLI/A2A/eval tooling as current runtime-edge integration details. The current
  Python layout is not fully isolated; the next internal-boundary refactor is to
  move deterministic orchestration/domain behavior out of `agent.py`.
- Separate trader and reviewer agents because their responsibilities and tool
  permissions differ; keep order execution outside both.
- Use ordinary typed Python functions for discrete tools.
- Use the current ADK adapter to integrate the bounded core workflow and hold
  conversation-scoped state; add persistent storage only when required.
- Treat Cloud SQL, RAG Engine, and Memory Bank as future platform options, not
  local harness requirements. If adopted, keep Cloud SQL authoritative and RAG
  or memory non-authoritative.
- Keep session state, authoritative trading records, external evidence, and
  curated memory distinct. Never use memory as the source of truth for money or
  lifecycle decisions.
- Give trader and reviewer agents separate histories. Exchange only validated,
  structured proposals and reviews tied to one canonical snapshot ID.
- If memory is later added, generate it after completed cycles or resolutions,
  persist provenance, and invalidate stale lessons; never put it on the trading
  hot path.
- Prefer the standard library, then current runtime features. Do not add a
  runtime abstraction until a second concrete runtime is required.
- Configure a model through the selected agent-runtime adapter. The current ADK
  adapter supplies model connectors. Do not build a parallel model-provider
  framework or spread provider-specific logic through tools.
- Keep venue market-data and paper-execution capabilities separate. Market-data
  configuration must never grant authenticated execution authority.
- Normalize venue adapter output into canonical domain values before agents or
  policy consume it. Use direct configured adapters now; add external plugin
  discovery only for a real separately packaged adapter.
- Keep authenticated execution out of the current harness. Any future live
  venue adapter must be isolated behind confirmation, IAM, hard limits, a kill
  switch, and reconciliation.

### Harness Ownership Rules

- Preserve the conceptual `Session -> Turn -> Step -> Action` hierarchy: the
  current session is local/in-memory, a turn is one paper cycle or operator
  action, and a step is one model request/response.
- Keep model decision, permission, and execution distinct. Apply authorization
  at the exact effect boundary.
- ADK owns the current inner model loop and runtime context mechanics;
  deterministic Chrysopoeia core contracts own money, policy, paper execution,
  and terminal outcomes.
- Do not call Chrysopoeia a meta-harness until a second independent harness and
  a coordinating control plane exist. Scheduling, persistence, or managed
  deployment of this harness alone remains Level 2.
- Treat the sibling `../harness` workspace as optional design provenance only;
  never import it or add a build/runtime dependency on it.

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
- Agent instructions are not a security or authorization control.
- Google Search and the ADK web UI are development capabilities, not production trust boundaries.

## Verification

- Run tests and import the agent before considering a change complete.
- Add the smallest test that checks observable behavior for non-trivial tools, routing, or workflow logic.
- Tests must not require live model calls or real credentials unless explicitly marked as integration tests.
