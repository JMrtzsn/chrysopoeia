# Platform Work Unit

GCP deployment: container image build/publish, Pulumi base (bucket, runner
identity, Artifact Registry, on-demand Cloud Run job), and digest pinning. The
sibling `harness/` folder is a separate work unit — agent and deterministic
manager code live there. Platform owns deployment/runtime lifecycle for each.
Ordered platform work lives in `ROADMAP.md`.

## Owned

- `infra/` (Pulumi program + local state dir)
- `Dockerfile` (wheel-install build; no harness source ever copied)
- `build.sh`, `.dockerignore`
- `pyproject.toml` for the Pulumi dev dependency (or `requirements.txt` + venv)

## Off-limits

- `harness/**` (application code; only a released wheel/image is consumed)
- Any import of the harness package: the platform installs `dist/*.whl` and
  calls the image's ENTRYPOINT CLI only.

## Contract consumed from the harness

- Pinned image digest: `pulumi config set image_digest <name@sha256:...>`
  (never `:latest` on a live stack; `:latest` is only a build-tag alias).
- Invocation form: image `ENTRYPOINT ["chrysopoeia", ...]` + args from
  `job_args` Pulumi config for the current on-demand job. The harness owns
  bounded proposal cycles; platform does not drive them.
- A future live-manager entrypoint runs separately from the proposal/review
  runtime. The platform owns its availability, identity, health, and restart
  lifecycle; deterministic manager code and venue adapters ship in the harness
  wheel. The manager process has no ADK/model dependency.
- Journal durability: the volume-mounted bucket behaves as `/mnt/journal`;
  record semantics belong to the harness, not here.

## Verification gates

```sh
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
pulumi preview    # offline evidence gate: 0 pending changes is the pass mark
```

Live apply or job executions need explicit operator approval (per
`docs/deployment.md`), and Cloud Run / Artifact Registry env edits
outside Pulumi are banned: `gcloud beta run jobs update --set-env-vars`
replaces ALL envs and desyncs Pulumi state.
