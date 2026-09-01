# Development Lifecycle

Chrysopoeia follows the Google Agents CLI lifecycle. Runtime trading-agent
skills are separate from the development skills that guide this process.

## Current Status

The repository is an Agents CLI prototype with `agents-cli-manifest.yaml`, an
A2A surface, and an eval scaffold. The manifest intentionally selects no
deployment target or CI/CD runner. `.agents-cli-spec.md` is the
product-specification source of truth; runtime authoritative records remain the
source of truth for money and lifecycle decisions.

## Gates

1. **Specify:** keep `.agents-cli-spec.md` aligned with approved product intent,
   safety boundaries, data sources, and measurable success criteria.
2. **Study:** reuse relevant official samples before implementing ambient
   triggers, deep research, RAG, safety plugins, or memory.
3. **Scaffold:** keep the prototype manifest current. Add a deployment target or
   CI/CD only after those choices are explicit.
4. **Build:** implement vertical slices. Run `agents-cli lint`,
   `uv run python -m unittest discover`, and import the agent for local canonical
   verification with `uv run python -c "import chrysopoeia.agent"`. Use unit
   tests for deterministic code, not LLM wording.
5. **Evaluate:** maintain small behavioral datasets. `agents-cli eval generate`
   invokes the agent and model; `agents-cli eval grade --config
   tests/eval/eval_config.yaml` runs the current deterministic metrics, though
   the CLI may initialize Vertex services. Compare scores after changes and
   block deployment on regressions or unmet thresholds.
6. **Deploy:** only after deterministic checks and behavioral evaluation pass,
   and only with explicit approval. Choose Agent Runtime, Cloud Run, or GKE based
   on measured requirements rather than scaffolding all three.
7. **Publish:** optionally register the deployed agent with Gemini Enterprise;
   this is not required for local or scheduled operation.
8. **Observe:** enable Cloud Trace. Add prompt-response logging or BigQuery Agent
   Analytics only when their audit value justifies privacy and storage cost.

## Verification Evidence

Every release candidate records:

- deterministic test and import results
- agent eval dataset and per-metric scores
- model, agent, prompt, graph, policy, tool, and skill versions
- unresolved failures and comparison with the previous result
- deployment target, approval, runtime identity, and rollback procedure

Production traces and logs default to metadata-only. Never log secrets, private
user data, hidden reasoning, or unrestricted prompt and response content.
