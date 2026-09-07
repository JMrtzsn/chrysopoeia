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

The manual Vertex behavior evaluation remains explicitly gated by
`RUN_PAPER_CYCLE_EVALUATION=1`, Vertex ADK configuration, project, and location.
It rejects API-key credentials for that path and makes at most two model calls.
Its reservation ceilings are derived from `chrysopoeia.toml`, not separate
operating guarantees. Paid and network checks remain manual: do not put them in
pre-commit, pre-push, or another automatic hook.

OpenCode remains an external engineering harness for orchestrating development
and review, not a model provider or inner trading step. Product integration with
OpenCode would create a meta-harness and requires separate explicit scope.

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
