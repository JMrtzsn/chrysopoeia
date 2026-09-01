# Evaluation Datasets

`basic-dataset.json` contains two canonical single-turn inference cases: exact
paper-operation configuration without starting a cycle, and refusal of live
wallet execution or policy bypass. Stable IDs and exact prompt markers let the
local deterministic metrics dispatch even if a metric instance omits
`eval_case_id`.

Each inference case uses the canonical shape:

```json
{
  "eval_case_id": "stable_case_id",
  "prompt": {"role": "user", "parts": [{"text": "User message"}]}
}
```

Run the local project checks with `agents-cli lint` and
`uv run python -m unittest discover`. When explicitly approved, inference and
grading use:

```sh
agents-cli eval generate
agents-cli eval grade --config tests/eval/eval_config.yaml
```

Generation invokes the Chrysopoeia agent and its configured model. The custom
metrics are deterministic local Python and use no grader model, but Agents CLI
grading may still initialize Vertex services. Treat both commands as potential
cloud interaction and do not run them for offline-only verification.
