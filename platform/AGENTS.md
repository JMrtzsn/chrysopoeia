# Platform Work Unit

GCP deployment: container image build/publish, Pulumi base (bucket, runner
identity, Artifact Registry, on-demand Cloud Run job), digest pinning, and the
optional independent consumer service/subscription/scheduler. Sibling work units
own application behavior; Harness owns event contracts.
Ordered platform work lives in `ROADMAP.md`.

## Owned

- `infra/` (Pulumi program + local state dir)
- `Dockerfile` (wheel-install build; no harness source ever copied)
- `build.sh`, `.dockerignore`
- `run.sh` (the explicit, operator-gated way to apply the stack or execute the job)
- `pyproject.toml` for the Pulumi dev dependency (or `requirements.txt` + venv)

## Off-limits

- `harness/**`, `consumer/**` (application code; only pinned images are consumed)
- Any import of the harness package: the platform installs `dist/*.whl` and
  calls the image's ENTRYPOINT CLI only.

## Contract consumed from the harness

- Pinned image digest: `pulumi config set image_digest <name@sha256:...>`
  (never `:latest` on a live stack; `:latest` is only a build-tag alias).
- Invocation form: image `ENTRYPOINT ["chrysopoeia", ...]` + args from
  `job_args` Pulumi config for the current on-demand job. The harness owns
  bounded proposal cycles; platform does not drive them.
- Operating settings are Harness-owned TOML, not CLI flags. Bundle
  `harness/configs/platform.toml` with the wheel, set `CHRYSOPOEIA_CONFIG` to
  `/etc/chrysopoeia-platform.toml`, and pass only command/journal invocation
  inputs. Rebuild and pin the image when that profile changes.
- Optional Pub/Sub configuration sets the Harness-owned event sink on the plain
  CLI image. Harness publishes from its journal outbox; Platform keeps only the
  topic and IAM. Future consumers own their identities, effects, and ledgers.
- Journal durability: the volume-mounted bucket behaves as `/mnt/journal`;
  record semantics belong to the harness, not here.
- Consumer resources exist only when both `consumer_image_digest` and
  `pubsub_topic` are configured. Its dedicated identity can access only its
  separate ledger bucket; a separate OIDC identity invokes the private service.
- Observer resources exist only when `observer_image_digest` is configured; it
  also requires `pubsub_topic` and a private `observer_invoker_member` (never
  `allUsers`/`allAuthenticatedUsers`). Its dedicated identity has only
  `roles/bigquery.jobUser` and archive-dataset `roles/bigquery.dataViewer`; it
  has no storage, publishing, or Vertex access.

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

Running the platform is deliberate and off by default. Prefer
`platform/run.sh {deploy|job}`, which refuses unless `CHRYSOPOEIA_RUN_PLATFORM=1`
is set, and the Pulumi program itself refuses any real apply without it too.
Preview (`pulumi preview`) is always allowed and needs neither.
