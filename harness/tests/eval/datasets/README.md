# Evaluation datasets

`basic-dataset.json` contains deterministic single-turn cases for configuration
and refusal of live wallet execution or policy bypass. Stable case IDs and
markers support local evaluation metrics.

Inference cases use this shape:

```json
{
  "eval_case_id": "stable_case_id",
  "prompt": {"role": "user", "parts": [{"text": "User message"}]}
}
```

The default harness evaluation uses fake models and needs no credentials,
network, or Vertex initialization. `agents-cli eval generate` and
`agents-cli eval grade --config tests/eval/eval_config.yaml` may contact or bill
the configured model provider; run them only under the bounded approval process
in `../../../docs/verification.md`.
