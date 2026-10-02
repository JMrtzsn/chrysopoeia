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
10. **Evolve deliberately:** harness-owned autonomous operation, durable storage,
    RAG/memory, managed deployment, publication, and production observability
    each require a demonstrated need, explicit architecture/acceptance criteria,
    deterministic checks, bounded live verification, and approval. The platform
    may launch the harness loop but does not schedule or drive cycles.

The checked-in harness model is Gemini through ADK. The supported bounded live
model verification is the manual Vertex behavior evaluation, explicitly gated
by `RUN_PAPER_CYCLE_EVALUATION=1`, Vertex ADK configuration, project, location,
and ADC. It rejects API-key credentials and makes at most two model calls. Its
reservation ceilings are derived from `chrysopoeia.toml`, not separate operating
guarantees. Paid and network checks remain manual: do not put them in pre-commit,
pre-push, or another automatic hook.

The current development/testing path is `chrysopoeia cycle --snapshot FILE
[--evidence FILE]`. Optional evidence is a hand-authored, bounded local bundle
marked operator-supplied and unverified; no current command creates it.
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

> Paths: all pre-split entries ran from the monorepo root. After the
> 2026-09-27 split, the equivalent commands run from `harness/` and the
> Pulumi commands from `platform/infra/` (see each folder's AGENTS.md).

### Non-Gemini provider proof via OpenRouter (2026-09-27)

- Commands: `uv run chrysopoeia discover --limit 5 --config <temp>`, then
  `uv run chrysopoeia capture 559651 --config <temp> --output <tmp>`, then one
  `uv run chrysopoeia cycle --snapshot <tmp> --config <temp>`. The temp config
  used `[models] adapter = "adk-registry"`, all four roles
  `openrouter/openai/gpt-4o`, and explicit per-model pricing $2.50/$10 per
  million tokens, confirmed against `https://openrouter.ai/api/v1/models`
  before the run.
- Real boundary: ADK `LLMRegistry` to LiteLlm to OpenRouter chat completions
  for `openai/gpt-4o`. Authentication came from the `OPENROUTER_API_KEY`
  environment variable in the operator shell only, never written to files,
  configuration, prompts, state, logs, or journals — the amended auth policy
  (spec, AGENTS.md, README.md) permits provider-standard env-var keys for
  providers without ambient authentication. This proves the non-Gemini
  provider boundary that the 2026-09-15 registry run left unverified.
- Result: terminal `abstained` (`trader_abstained`); trader called once;
  reviewer correctly not invoked on abstention; cost ledger `completed`;
  `actual_estimated_cost_usd` $0.004805 against the $0.06144 reserved ceiling.
- Bounds: one bounded paper cycle, at most two model calls, no journal, no
  venue calls during the cycle. Offline preconditions: full unit suite, ruff,
  `ty`, and `chrysopoeia validate --config <temp> --json` all green before the
  live run.
- Approval: operator approved the bounded run at the $0.06144 worst-case
  estimate.
- Cost: ~$0.005 estimated model cost; no paid cloud services.
- Cleanup: temp config and snapshot lived only in the OS temp directory and
  were deleted after the run; no cloud resources created.


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

### Cloud Run restoration after failed VM pivot (2026-09-27)

- Decision: the managed deployment shape is **container-first Cloud Run jobs**
  (per-execution billing, hard per-task cost ceiling, no boot script, no SSH
  ever into any machine). The intermediate Debian VM + boot-script attempt is
  recorded as abandoned; `infra/boot.sh` and the source `BucketObject` are
  deleted, and the ephemeral VM and its shape resources were destroyed in the
  Pulumi stack (`local-dev`).
- Live commands: `pulumi refresh`, `pulumi up` (8 programs-declared base
  resources + one `cloudrunv2.Job` with the gcsfuse journal volume), restore
  of the deleted Artifact Registry repository + rebuilt image
  `harness@sha256:70d1d9bfc65784ba9dd30a0bc53d0c90f0b17238fea7451d34683dd1a0285f42`
  (a `gcloud beta run jobs update --set-env-vars` call that replaced job envs
  was identified as the root cause of earlier local failure and is banned in
  favor of Pulumi-only mutation), plus three bounded executions:
  1. `cycle` against the cached capture (idempotent admission no-op — 0
     journal lines, as designed, exit 0);
  2. `book` (zero model calls, exit 0);
  3. `cycle` against a **fresh capture** (paper_cycle live price 0.037):
     journal gained a third line, a new `turn_admitted` with new
     `turn-b2e624f15ac71801235a4720` (12:22:35 UTC, 2026-09-27).
- Real boundary: the harness path from Vertex access to journal append ran
  inside the Pulumi-declared Cloud Run job with ambient runner-SA identity;
  session opened in the durable bucket; honest abstention (no evidence
  bundle) on the true market; the container image is the only application
  artifact deployed.
- Findings: `job_args` are currently operator-configured from the stack
  (`["cycle", ..., "--config", "/mnt/journal/vertex.toml", ...]` with the
  Vertex-native config staged on the bucket), a tradeoff to revisit when the
  checked-in default alias config decision is made. `gcloud beta run jobs
  update --set-env-vars` replaces ALL env vars, so it must not be used
  alongside Pulumi-managed envs. Stdout `book_report`/`paper_cycle_result`
  lines remained invisible through `gcloud logging read` filters again
  (durable journal is authoritative).
- Approval: bounded executions pre-approved (~$0.005 total; image rebuild
  free); result-based exit 0. Cleanup: nothing remains beyond the temp dirs
  listed above; job object stack fenced via `goog-pulumi-provisioned` labels
  in all Pulumi-provisioned resources.
- Cleanup: one durable bucket (`PROJECT_ID-chrs-journals-local`)
  remains deliberately for the next bounded session; no other paid state.

### Monorepo split into harness and platform work units (2026-09-27)

- Structural change only: `git mv` of the python package, tests, config, hooks
  into `harness/` and the Pulumi program plus Docker artifacts into
  `platform/`; no behavior change beyond two app-internal path resolutions
  (config lookup now prefers the `CHRYSOPOEIA_CONFIG` env override before the
  repo default, needed because the wheel-installed CLI has no repo layout).
- Ownership fences: `harness/AGENTS.md` and `platform/AGENTS.md` now define
  each unit's owned files, off-limits side, and gates (harness never runs
  gcloud/pulumi; platform never imports the harness and consumes only the
  image; `gcloud beta run jobs update --set-env-vars` is banned alongside
  Pulumi-managed envs).
- Offline verification: 175 unit tests (one new, for the config env override),
  ruff, `ty`, and `chrysopoeia validate --json` all green from `harness/`;
  `pulumi preview` from `platform/infra/` converged to 0 pending changes and
  `pulumi up` no-ops — the pure-move commit did not disturb any resource.
- Live: the wheel-built image
  (`harness@sha256:98e7c3c100e1bfff4d45dd71a0e60fdac888f8ed2035d729a14b27766b99a317`,
  validated offline inside the container first) pushed and pinned in Pulumi
  config; job invocation form updated to the image ENTRYPOINT
  (`args=[cycle ...]` without the wrapper), and one live execution completed
  successfully against the journal bucket.
- Cost: execution vCPU-seconds under one cent; nothing else created.

### Book marking (2026-09-15)

- Command: `chrysopoeia mark --journal <temp dir>` over the open live-verified
  paper session (one open position on market 559651).
- Real boundary: public Gamma sector policy and one CLOB book capture (the
  standard capture path). First attempt failed on a transient book fetch and
  the retry succeeded; failures leave no mark record (offline tested).
- Result: fresh venue mark 0.038 recorded against the entry price 0.005;
  unrealized P&L +$789.60 in the journal and report.
- Bounds: one capture (one Gamma + one CLOB read-only request). Approval:
  operator pre-approved the read-only venue checks. Cost: zero model cost.
  Authentication: none required. Cleanup: temp dir only.

### Pluggable model registry run (2026-09-15)

- Command: one `uv run chrysopoeia cycle ... --config <registry config>
  --journal <temp dir>` using `[models] adapter = "adk-registry"` and explicit
  per-model `[cost.models]` pricing.
- Real boundary: ADK `LLMRegistry` model resolution (the registry path now
  used instead of the hard-coded `Gemini()` constructor) and the per-model
  cost gate; Gemini 2.5 Flash on Vertex AI with ambient ADC, no copied keys.
- Result: the cycle abstained after one trader call; estimated cost
  $0.0008508 reserved against a $0.0100352 ceiling computed from the
  configured per-model pricing ($0.30/$2.50 per M tokens) rather than the
  legacy flat prices ($1/$3); the cost ledger completed cleanly.
- Bounds: one cycle, at most two calls; reviewer not invoked.
- Scope note: non-Gemini providers (ollama/claude/gpt/openai prefixes via
  LiteLlm) are offline-tested; a bounded live run against one of those needs
  `google-adk[extensions]` and provider credentials or a local backend, so
  that boundary remains not verified. Claude Pro/Code credentials are banned
  from this harness by the safety contract regardless.
- Cleanup: temp dir only.

### Cloud Run container deployment (2026-09-18)

- Live commands: `pulumi up` (8 resources: journal bucket, runner SA with
  project-level `roles/aiplatform.user`, bucket objectAdmin, Artifact Registry
  repository and reader binding, API enablement, one Cloud Run job); one
  `docker build --platform linux/amd64` plus local container offline gate
  (`chrysopoeia validate --json` inside the image); one
  `docker push`; snapshot upload to the journal bucket; two Cloud Run job
  executions — one `cycle` (chrysopoeia-cycle-local-m76zd) and one `book`
  (chrysopoeia-cycle-local-pdswd); machine config reset to the `cycle`
  default afterwards.
- Real boundary: the deployed container ran the real harness path — Vertex
  model access was attempted live; the first execution failed on the known
  `gemini-flash-latest` alias (Gemini-API-only), resolved by staging a
  Vertex-native `vertex.toml` (the bounded prior live config) on the journal
  bucket and configuring the job args to include `--config /mnt/journal/vertex.toml`.
- Result: execution m76zd SUCCEEDED (exit 0) — journal in the bucket gained
  `session_opened` and `turn_admitted`; execution pdswd SUCCEEDED — the
  `book` report ran against the mounted journal (gcsfuse mount confirmed live
  in the job logs). No executions place (or assume) authenticated venue
  authority; no keys are ever copied.
- Scope: per-tenant projects are the chosen eventual shape for Level 3; the
  current single-operator stack is one tenant.
- Approval: operator approved base apply, image push, and the two bounded
  executions. Cost: accumulatively less than USD 0.02 in irreducible Cloud Run
  billables; image repository storage cents per month; no extra paid services.
- Findings: job stdout report lines were not visible in Cloud Logging via
  `gcloud logging read` filters (container-runtime lines only) — the
  authoritative durable record is the journal in the versioned bucket, which
  is the design intent. `gcloud beta run jobs executions logs read` crashed
  locally (gcloud bug, TypeError) while filtering.
- Cleanup: `job_args` reset; tofu/terraform remnants deleted; one durable
  bucket (`PROJECT_ID-chrs-journals-local`) remains deliberately for
  the next bounded session; nothing else created.

### Turn-level recovery (2026-09-30)

- Setup: fresh temp journal with an open session and one planted
  admitted-but-unfinished turn (`turn-planted…`, market 999999); one public
  capture of market 559651.
- Commands: one `uv run chrysopoeia cycle --snapshot <capture> --config <temp
  config> --journal <temp dir>`, then one identical re-run.
- Real boundary: journal recovery before admission plus Gemini 2.5 Flash on
  Vertex AI with ambient ADC (project PROJECT_ID, us-central1); no
  copied keys.
- Result: the first cycle wrote `turn_finished abandoned` for the planted turn
  before admitting its own, abstained after one trader call, and wrote exactly
  one `turn_finished abstained`. The re-run printed the prior outcome, made no
  model call, and added no records (5 lines stayed 5); `book` reported zero
  open turns. An earlier attempt without Vertex environment variables failed
  at model construction and was journaled `failed`, exercising the
  error-path finalization live.
- Bounds: one paid cycle, one trader call; reviewer not invoked.
- Approval: operator approved the local bounded run. Cost: ~$0.0022 estimated.
- Cleanup: temp config, capture, and journals live only in the OS temp
  directory.

### Bounded autonomous trading loop (2026-09-30)

- Command: `uv run chrysopoeia run --journal <temp dir> --config <temp config>
  --bankroll 1000 --maximum-loss 100 --target-win-rate 0.6 --window-minutes 5
  --max-cycles 2 --cost-budget 0.1 --interval-seconds 5 --stop-file <temp>`,
  then a resume with the stop file present and a resume with a different
  target.
- Real boundary: live public Polymarket discovery and capture selected by the
  harness (markets 559651 and 560317, no operator pick) and Gemini 2.5 Flash
  on Vertex AI with ambient ADC (project PROJECT_ID, us-central1).
- Result: two cycles, both abstained after one trader call each; journal holds
  exactly one `turn_admitted`/`turn_finished` pair per market with per-turn
  model cost; report `stop_reason: max_cycles`, `win_rate: null` with no
  settlements, model cost $0.004459, net P&L -$0.004459. Resume with the stop
  file stopped before any model call (`stop_reason: stopped`, original
  `window_end` kept); resume with a different target was refused with no
  records added.
- Bounds: max 2 cycles, 5-minute window, $0.10 session cost cap.
- Approval: operator approved the local bounded run. Cost: ~$0.0045.
- Cleanup: temp config, stop file, and journal only in the OS temp directory.
