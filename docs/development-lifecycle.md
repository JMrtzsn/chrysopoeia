# Development Lifecycle

Chrysopoeia follows the Google Agents CLI lifecycle. Runtime trading-agent
skills are separate from the development skills that guide this process.

## Current Status

The repository is an existing hand-built ADK prototype, not yet managed by
Agents CLI. `.agents-cli-spec.md` is the product-specification source of truth;
runtime authoritative records remain the source of truth for money and lifecycle
decisions. Do not claim that a manifest, A2A surface, deployment infrastructure,
or eval scaffold exists until `agents-cli scaffold enhance .` has been approved
and run.

## Gates

1. **Specify:** keep `.agents-cli-spec.md` aligned with approved product intent,
   safety boundaries, data sources, and measurable success criteria.
2. **Study:** reuse relevant official samples before implementing ambient
   triggers, deep research, RAG, safety plugins, or memory.
3. **Scaffold:** with user approval, enhance the existing project as a prototype.
   Add a deployment target or CI/CD only after those choices are explicit.
4. **Build:** implement vertical slices. The current prototype smoke test is
   `uv run adk run chrysopoeia`; use `agents-cli run` only after approved
   `agents-cli scaffold enhance .`. Use unit tests for deterministic code, not
   LLM wording.
5. **Evaluate:** maintain small behavioral datasets and grade task success, tool
   use, trajectory, grounding, safety, and reviewer independence. Compare scores
   after changes and block deployment on regressions or unmet thresholds.
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
