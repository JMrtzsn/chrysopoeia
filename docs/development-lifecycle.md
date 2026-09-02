# Development Lifecycle

## Current Status

Chrysopoeia is a local runtime-neutral core harness currently integrated through
ADK and Agents CLI, with an A2A surface, in-memory ADK sessions, deterministic
tests/evaluations, and no deployment target or CI/CD runner.
`.agents-cli-spec.md` is the product-scope source of truth. Canonical records and
deterministic policy—not runtime state, prompts, or memory—remain the source of
truth for paper decisions.

## Harness-first Gates

1. **Specify:** keep the product spec, current implementation, non-goals, and
   measurable acceptance aligned. Do not describe future platform behavior as
   current.
2. **Build a local vertical slice:** preserve role isolation and implement the
   smallest path from validated configuration and canonical venue data through
   deterministic policy, paper execution, and audit.
3. **Contract-test adapters:** test model configuration through the current ADK
   runtime edge and venue adapters against canonical success/failure fixtures.
   Market-data tests must require no execution credentials and must not imply
   execution authority.
4. **Verify offline:** default checks must make no network/model/Vertex calls and
   need no credentials:

   ```sh
   agents-cli lint
   uv run python -m unittest discover
   uv run python -c "import chrysopoeia.agent"
   ```

5. **Evaluate behavior:** keep small datasets for task success, role/tool
   boundaries, canonical grounding, abstention/rejection, safety, and model-cost
   settlement. The project-owned paper-cycle harness runs offline as part of the
   canonical suite.
6. **Run paid/live-model evaluation only with explicit approval:** model-backed
   generation, Agents CLI grading that may initialize Vertex services, and the
   manual Vertex paper-cycle evaluation are potential cloud/billing operations.
   Operators own API enablement, ADC, quota, and billing; the harness never runs
   `gcloud` or changes infrastructure. Do not run these for offline verification.
7. **Evolve the platform later:** durable storage, scheduling, RAG/memory,
   managed deployment, publication, and production observability each require a
   demonstrated need, explicit architecture/acceptance criteria, deterministic
   checks, and approval.

The manual Vertex behavior evaluation remains explicitly gated by
`RUN_PAPER_CYCLE_EVALUATION=1`, Vertex ADK configuration, project, and location.
It rejects API-key credentials for that path and makes at most two model calls.
Its reservation ceilings are derived from `chrysopoeia.toml`, not separate
operating guarantees.

## Release Evidence

A local harness release records:

- deterministic test, lint, import, and offline evaluation results;
- model/agent/prompt/workflow/policy/tool and adapter versions where applicable;
- adapter/configuration contract-test results and unresolved failures;
- explicit approval and cost evidence for any paid behavior evaluation.

A future managed release additionally records deployment target, runtime
identity, required services, migration/recovery plan, observability/privacy
settings, and rollback procedure. Production logs default to metadata only and
never include secrets, private user data, or hidden reasoning.
