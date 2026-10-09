# Platform Work Unit

GCP deployment: container image build/publish, Pulumi base (bucket, runner
identity, Artifact Registry, on-demand Cloud Run job), digest pinning, and future
deployment/trigger adapters. The sibling `harness/` folder is a separate work
unit and owns application code and event contracts.
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
- The optional Pub/Sub adapter invokes `outbox-pending`/`outbox-ack` around
  journal-backed `cycle`/`run` CLI commands and never imports Harness code or
  parses its journal. Future event consumers deploy independently and own their
  identities, effects, and ledgers.
- Journal durability: the volume-mounted bucket behaves as `/mnt/journal`;
  record semantics belong to the harness, not here.

## Verification gates

The file-backed `local-dev` stack contains no secure configuration. Keep
credentials and other secrets out of it; its empty passphrase is only for this
local verification stack, not production stacks.

```sh
uv venv platform/infra/.venv
uv pip install --python platform/infra/.venv/bin/python -r platform/infra/requirements.txt
source platform/infra/.venv/bin/activate
PULUMI_CONFIG_PASSPHRASE='' \
  pulumi -C platform/infra preview --stack local-dev    # 0 pending changes passes
```

Live apply or job executions need explicit operator approval (per
`docs/deployment.md`), and Cloud Run / Artifact Registry env edits
outside Pulumi are banned: `gcloud beta run jobs update --set-env-vars`
replaces ALL envs and desyncs Pulumi state.
