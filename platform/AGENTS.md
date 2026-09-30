# Platform Work Unit

GCP deployment: container image build/publish, Pulumi base (bucket, runner
identity, Artifact Registry, Cloud Run job), and digest pinning. The sibling
`harness/` folder is a separate work unit — application loop code lives there.
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
  `job_args` Pulumi config. The platform launches the selected harness
  entrypoint; loop ownership remains in the harness.
- Journal durability: the volume-mounted bucket behaves as `/mnt/journal`;
  record semantics belong to the harness, not here.

## Verification gates

```sh
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
pulumi preview    # offline evidence gate: 0 pending changes is the pass mark
```

Live apply or job executions need explicit operator approval (per
`docs/development-lifecycle.md`), and Cloud Run / Artifact Registry env edits
outside Pulumi are banned: `gcloud beta run jobs update --set-env-vars`
replaces ALL envs and desyncs Pulumi state.
