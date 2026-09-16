"""Chrysopoeia persistent cloud base: one journal bucket and one least-privileged runner identity.

The harness itself is still a local/ephemeral operator-driven CLI. This program
provisions only what sessions need to exist: durable journals and the single
identity allowed to call Vertex AI and read/write that bucket. Per-session
compute lives in infra/script/session.sh and must never be declared persistent
here. Keep this boundary: product code never creates or reads cloud resources.
"""

import pulumi
import pulumi_gcp as gcp

config = pulumi.Config()
project_id = config.require("project_id")
region = config.get("region") or "us-central1"
operator = config.get("operator") or "local"

bucket_name = f"{project_id}-chrysopoeia-{operator}-journals"
account_id = f"chrysopoeia-runner-{operator}"[:30]

bucket = gcp.storage.Bucket(
    "journals",
    project=project_id,
    name=f"{bucket_name}"[:63].rstrip("-"),
    location=region,
    uniform_bucket_level_access=True,
    versioning=gcp.storage.BucketVersioningArgs(enabled=True),
    force_destroy=False,
)

runner = gcp.serviceaccount.Account(
    "runner",
    project=project_id,
    account_id=account_id,
    display_name=f"Chrysopoeia paper-cycle runner ({operator})",
    description="Runs one bounded paper cycle: Vertex model calls plus the journal bucket only.",
)

serviceaccount_member = pulumi.Output.concat("serviceAccount:", runner.email)

gcp.serviceaccount.IAMMember(
    "runner-vertex-user",
    service_account_id=runner.name,
    role="roles/aiplatform.user",
    member=serviceaccount_member,
)

gcp.storage.BucketIAMMember(
    "runner-bucket-admin",
    bucket=bucket.name,
    role="roles/storage.objectAdmin",
    member=serviceaccount_member,
)

pulumi.export("runner_email", runner.email)
pulumi.export("journal_bucket", bucket.url)
pulumi.export(
    "session_hint",
    "infra/script/session.sh <init|run|delete> after networking is configured",
)
