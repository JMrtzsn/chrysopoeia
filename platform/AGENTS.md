# Platform Work Unit

GCP deployment: container image build/publish, Terraform base (bucket, runner
identity, Artifact Registry, on-demand Cloud Run job), digest pinning, and the
optional independent consumer service/subscription/scheduler. Sibling work units
own application behavior; Harness owns event contracts.

## Owned

- `infra-tf/` (Terraform root, offline gates, plan policy; state in the
  versioned GCS bucket `PROJECT_ID-chrs-tfstate-local`)
- `Dockerfile` (wheel-install build; no harness source ever copied)
- `build.sh`, `.dockerignore`
- `run.sh` (the explicit, operator-gated way to apply the stack or execute the job)

## Off-limits

- `harness/**`, `consumer/**` (application code; only pinned images are consumed)
- Any import of the harness package: the platform installs `dist/*.whl` and
  calls the image's ENTRYPOINT CLI only.

## Contract consumed from the harness

- Pinned image digest: `image_digest = "<name@sha256:...>"` in the
  operator-local `infra-tf/terraform.tfvars`
  (never `:latest` on a live stack; `:latest` is only a build-tag alias).
- Invocation form: image `ENTRYPOINT ["chrysopoeia", ...]` + args from
  the `job_args` Terraform variable for the current on-demand job. The harness owns
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
- Scheduled esports scanning exists only when `scan_schedule` is set (cron in
  UTC): a Cloud Scheduler job POSTs one executions-create call for the
  `chrysopoeia-scan-<operator>` workflow, which runs one paper-cycle execution
  with a per-tick journal override. The workflow's runtime identity is the
  existing least-privilege trigger identity (`run.jobs.run` +
  `runWithOverrides` only); the scheduler needs that identity to satisfy
  `workflows.invoker` plus a scheduler-agent token-creator grant on it.
  `scan_paused` pauses the schedule; `consumer_sweep_paused` pauses the
  consumer sweep; `projection_refresh_paused` disables the `open_positions`
  scheduled query. Workflows executes-create
  accepts OAuth2 access tokens only, and its `time.format(sys.now())` returns
  the per-tick journal key.
- Optional `billing_account_id` with `budget_amount_usd` (+ `budget_currency`,
  default SEK) deploys the native monthly billing budget for the configured
  project: whole-amount thresholds at 50/90/100%, default billing-account
  recipients. The billing account currency must match the amount's currency.
- Optional `health_alert_email` deploys log-based metrics over known failure
  signatures (consumer service ERROR logs, cycle task 900-second timeouts,
  scheduler 5xx attempts), an email notification channel, one threshold alert
  per metric, and a Cloud Monitoring health dashboard. Alerts key on error
  events, not absent ticks: overnight silence is by design because no ticks
  are scheduled then.

## Verification gates

```sh
platform/infra-tf/gates.sh    # offline: fmt, validate, protections, policy, tflint, trivy
platform/run.sh drift         # read-only plan; exit 0 = no drift, 2 = drift
```

Live apply or job executions need explicit operator approval (per
`docs/deployment.md`). Never change cloud resources outside Terraform:
`gcloud beta run jobs update --set-env-vars` replaces ALL envs and creates
drift.

Running the platform is deliberate and off by default.
`CHRYSOPOEIA_RUN_PLATFORM=1 platform/run.sh deploy` runs the gates, saves a
plan, checks it with conftest, and applies only that saved plan.
`platform/run.sh {deploy|job|enqueue}` refuses without
`CHRYSOPOEIA_RUN_PLATFORM=1`; `drift` is read-only and always allowed.
