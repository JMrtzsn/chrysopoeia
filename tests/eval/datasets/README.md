# Evaluation Datasets

`basic-dataset.json` contains canonical single-turn behavior cases for exact
paper-operation configuration and refusal of live wallet execution or policy
bypass. Stable IDs and prompt markers support deterministic local metrics.

Each inference case uses:

```json
{
  "eval_case_id": "stable_case_id",
  "prompt": {"role": "user", "parts": [{"text": "User message"}]}
}
```

## Offline Harness Evaluation

The canonical default is offline and deterministic:

```sh
agents-cli lint
uv run python -m unittest discover
```

This suite covers deterministic metrics and a fixed paper-cycle harness with
fake models. It must not require credentials, network access, model calls, or
Vertex initialization.

## Explicit Runtime/Model Behavior Evaluation

The following invokes the model configured through the current ADK runtime
adapter and may incur network and billing activity:

```sh
agents-cli eval generate
agents-cli eval grade --config tests/eval/eval_config.yaml
```

Generation calls the Chrysopoeia agent. The custom graders are deterministic
Python, but Agents CLI grading may still initialize Vertex services. Run either
command only with explicit approval and credentials required by the configured
ADK model path. The
separately gated paper-cycle model evaluation is documented in
`docs/development-lifecycle.md`; it is not part of offline verification.
