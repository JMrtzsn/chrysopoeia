# Development Lifecycle

## Current Status

Chrysopoeia is a local runtime-neutral core harness currently integrated through
ADK and Agents CLI, with an A2A surface, in-memory ADK sessions, deterministic
tests/evaluations, and no deployment target or CI/CD runner.
`.agents-cli-spec.md` is the product-scope source of truth. Canonical records and
deterministic policy—not runtime state, prompts, or memory—remain the source of
truth for paper decisions.

The optional sibling workspace references `../harness/README.md` and
`../harness/architectures/` supplied the Level 1 turn, Level 2 harness, Level 3
meta-harness, and ownership vocabulary used here. They are design provenance
only, may not resolve from GitHub, and are not a source, build, import, or runtime
dependency; `.agents-cli-spec.md` contains Chrysopoeia's normative rules.

## Harness-first Gates

1. **Specify:** keep the product spec, current implementation, non-goals, and
   measurable acceptance aligned. Do not describe future platform behavior as
   current. Every architecture change must declare who owns the model loop,
   context assembly, tool implementation/authorization, retries, cancellation,
   persistence, and terminal status, including any ownership moved between ADK
   and the deterministic core.
2. **Build a local vertical slice:** preserve role isolation and implement the
   smallest path from validated configuration and canonical venue data through
   deterministic policy, paper execution, and audit.
3. **Contract-test adapters:** test model configuration through the current ADK
   runtime edge and venue adapters against canonical success/failure fixtures.
   Market-data tests must require no execution credentials and must not imply
   execution authority.
4. **Verify offline:** default checks must make no network/model/Vertex calls and
   need no credentials. This mandatory pre-commit gate is necessary but is not
   sufficient for an externally observable feature addition or change:

   ```sh
   agents-cli lint
   uv run python -m unittest discover
   uv run python -c "import chrysopoeia.agent"
   ```

5. **Evaluate behavior offline:** keep small datasets for task success, role/tool
   boundaries, canonical grounding, abstention/rejection, safety, and model-cost
   settlement. The project-owned paper-cycle harness runs offline as part of the
   canonical suite.
6. **Verify the changed real boundary live:** every externally observable
   feature addition or change must pass the offline gate first and then the
   smallest bounded live path through the boundary it changes. This applies to
   external-service CLI behavior, venue adapters/data schemas, model/provider
   configuration, callbacks/cost accounting, structured outputs, workflows,
   A2A/serving endpoints, deployment/infrastructure, persistence, and any future
   approved authenticated effect. Current venue checks use read-only public
   data; current model checks use bounded paper cycles. Authenticated live
   exchange execution remains prohibited.
7. **Control and record the live run:** obtain human approval before incurring
   cost or external effects. Estimate cost before the run; bound calls, elapsed
   time, and data; use least privilege and ambient authentication (ADC for
   Vertex) rather than copied keys; and sanitize retained evidence. Record the
   exact command, result, and actual or best-known cost when applicable. Clean
   up or disable temporary services and resources afterward.
8. **Resolve failures:** a live failure blocks completion and any commit
   recommendation; fix it and rerun both affected gates. If environment access,
   IAM, or a vendor outage prevents the run, report the feature as incomplete.
   Do not waive the gate or label the feature verified.
9. **Apply narrow exceptions:** pure documentation, internal refactors with no
   observable behavior change, and test-only tooling do not require a live run;
   verify the no-behavior-change claim offline. Configuration-only changes that
   affect runtime or provider behavior are not exempt.
10. **Evolve the platform later:** durable storage, scheduling, RAG/memory,
    managed deployment, publication, and production observability each require a
    demonstrated need, explicit architecture/acceptance criteria, deterministic
    checks, bounded live verification, and approval.

The checked-in harness model is Gemini through ADK. The supported bounded live
model verification is the manual Vertex behavior evaluation, explicitly gated
by `RUN_PAPER_CYCLE_EVALUATION=1`, Vertex ADK configuration, project, location,
and ADC. It rejects API-key credentials and makes at most two model calls. Its
reservation ceilings are derived from `chrysopoeia.toml`, not separate operating
guarantees. Paid and network checks remain manual: do not put them in pre-commit,
pre-push, or another automatic hook.

The operator path is `chrysopoeia cycle --snapshot FILE [--evidence FILE]`.
Optional evidence is a hand-authored or future-adapter-produced, bounded local
bundle marked operator-supplied and unverified; no current command creates it.
Validation makes no network or model calls. Cycle reads one bounded capture
locally, then makes at most one trader and one reviewer model call. It does not
fetch market data. Current exposure defaults to zero for this first-cycle
in-memory command; nonzero current exposure must be supplied explicitly with
`--market-exposure` and `--total-exposure`.

The bounded discovery venue check runs `chrysopoeia discover --limit 1`, then
passes the returned `capture` market ID to `chrysopoeia capture MARKET`. It is a
manual public read-only check bounded to three Gamma requests and one Gamma plus
one CLOB capture request. Discovery samples at most 75 records in three 25-record
pages. Every request has a five-second timeout and 256 KiB response limit; the
check makes no model calls and has zero model cost.

OpenCode and official Claude Code remain external engineering harnesses for
development and review, not model providers or inner trading steps. Neither is
imported or a product dependency. Product integration of either would create
Level 3/meta-harness scope and requires explicit design.

## Release Evidence

A local harness release records:

- deterministic test, lint, import, and offline evaluation results;
- model/agent/prompt/workflow/policy/tool and adapter versions where applicable;
- adapter/configuration contract-test results and unresolved failures;
- for each externally observable feature change, sanitized bounded-live evidence
  containing the exact command, result, real boundary exercised, call/time/data
  bounds, approval, cost estimate and actual or best-known cost when applicable,
  authentication posture, and cleanup outcome.

A future managed release additionally records deployment target, runtime
identity, required services, migration/recovery plan, observability/privacy
settings, and rollback procedure. Production logs default to metadata only and
never include secrets, private user data, or hidden reasoning.

## Recorded Live Verification

### Bounded market discovery (2026-09-15)

- Commands: `uv run chrysopoeia discover --limit 1` then
  `uv run chrysopoeia capture 559651 --output <local file>`
- Real boundary: public Polymarket Gamma and CLOB read-only endpoints.
- Bounds: discovery 1 candidate (under the 75-record/three-page sample limit,
  bounded to the documented per-check Gamma requests); capture one Gamma plus
  one CLOB request with five-second timeout and 256 KiB limit. No model calls.
- Result: discovery returned candidate market 559651 ("Xi Jinping out before
  2027?"); capture returned a validated 2,723-byte canonical snapshot with
  order book, 0.02 fee provenance (`paper-assumption:flat-2pct-v1`),
  resolution rules, token ID, and source URL. Both commands exited 0.
- Approval: operator approved the read-only network check.
- Cost: zero model cost; no paid services used.
- Authentication: none required; public endpoints.
- Cleanup: temporary output retained only in `os_tmpdir`; no services created.
- Offline preconditions: 135 unit tests passed before the live check.

### Journaled paper cycle (2026-09-15)

- Commands: one `uv run chrysopoeia cycle --snapshot <captured market 559651>
  --config <temp config> --journal <temp dir>`, then one identical re-run for
  the admission idempotency proof.
- Real boundary: Gemini 2.5 Flash on Vertex AI with ambient ADC (project
  PROJECT_ID, us-central1); no copied keys. The project's Agent
  Platform API had to be enabled first (zero-cost prerequisite) and the
  configured default `gemini-flash-latest` alias proved unavailable on Vertex,
  so the temp config used the `gemini-2.5-flash` alias with the configured
  $1/$3 pricing left as a conservative ceiling.
- Result: first cycle abstained after exactly one trader call (estimated
  $0.00226 against a $0.022528 reserved ceiling); journal recorded
  `session_opened` and `turn_admitted`; `book_after` appeared in the report.
  The re-run abstained again (estimated $0.00215) and added no journal
  records — repeat turn admission was a no-op (2 lines stayed 2 lines).
- Bounds: two cycles, at most one trader call each; reviewer never invoked;
  no venue network activity during the cycles.
- Approval: operator approved the bounded live model run.
- Cost: ~$0.0044 total estimated model cost.
- Cleanup: temporary config and journal live only in the OS temp directory;
  no cloud resources created beyond the API enablement.

### Full trade-route paper cycle (2026-09-15)

- Setup: seeded rich snapshot (same real market 559651 questions/rules,
  canonical identity recomputed: price 0.005, one million-share YES ask) plus a
  hand-authored snapshot-bound evidence bundle (provenance
  `operator-supplied-unverified`, four public-URL external records). The spec
  explicitly admits seeded local cycles; the allocation was pure paper.
- Real boundary: Gemini 2.5 Flash on Vertex AI (ADC only), ~13 one-cycle runs.
- Observed route progression across runs:
  1. canonical-snapshot-only cycles abstain five times (~$0.002 each) even at a
     seeded 0.02 price — the trader correctly refuses without citable evidence;
  2. with evidence, the trader proposed and the reviewer ran and was consulted
     (first non-abstain route: `reviewer_called: true`); the deterministic
     policy rejected on the 5-point minimum net edge;
  3. next run the policy rejected on the 1% per-market exposure cap;
  4. with the operator raising the limit to 20% (a documented operator flag),
     the cycle **filled**: 24,000 shares @ VWAP 0.005, $120 gross, $2.40 fee,
     and the journal recorded the position (book: open exposure $122.40,
     bankroll-now $877.60, unrealized −$2.40 fee float);
  5. an immediate re-run of the same cycle was refused **before any model
     call** ("market has an open journal position"), proving same-market
     preemption live.
- Result: abstain → review → deterministic reject (edge, then exposure) →
  review-approved fill → journal record → duplicate-turn preemption all
  observed against the real model boundary.
- Bounds: ~13 cycles, ≤2 calls each, no reviewer call on abstentions.
- Approval: operator approved the bounded live model runs.
- Cost: ~$0.03 total estimated model cost across the progression.
- Cleanup: seeded snapshots, evidence bundles, and journals live only in the OS
  temp directory; one journal intentionally left open (paper only).

### Resolution capture and settlement (2026-09-15)

- Commands: one direct `load_market_resolution("20")` read, one bounded
  settlement replay exercise, plus one `chrysopoeia settle` CLI refusal and one
  earlier `settle` run against the live unresolved market 559651 (correctly
  refused before any book change).
- Real boundary: public Polymarket Gamma read-only; no model calls.
- Adapter schema findings from live data, now covered by offline contract
  tests: `outcomePrices` is a JSON-encoded string in the Gamma market detail
  response; gamma holds settled prices at ~0.000001/~0.999999 rather than
  exactly 1/0; open markets are refused with "has not resolved yet"; closed
  markets without a dominant outcome are refused.
- Result: real resolved market 20 normalized to `resolved_no`; a paper
  position on that market settled through the deterministic book against the
  venue fact (realized −$122.40, full loss including fee), and the unresolved
  real market was refused without affecting its journal.
- Bounds: three Gamma reads total (two unresolved market ids, one resolved).
- Approval: operator approved the read-only venue checks.
- Cost: zero model cost; no paid services.
- Authentication: none required; public endpoints.
- Cleanup: nothing created beyond temp journal directories.
