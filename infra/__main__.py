"""Chrysopoeia cloud base: versioned journal bucket, least-privileged runner
identity, Artifact Registry repository, and one Cloud Run job that executes
one harnessed paper cycle per invocation.

There is no boot script anywhere in this program: the container image built
from the repository `Dockerfile` is the entire runtime; executions are
requested by the operator with

    gcloud beta run jobs execute chrysopoeia-paper-cycle --region <region>

and every execution bills only its own vCPU seconds (zero idle cost). The
journal bucket is mounted into the container at /mnt/journal through a
Cloud Run GCS volume, so journals persist across executions without a
database. Multi-tenant or public deployment remains out of scope pending an
explicit Level 3 design.
"""

import pulumi
import pulumi_gcp as gcp

config = pulumi.Config()
project_id = config.require("project_id")
region = config.get("region") or "us-central1"
operator = config.get("operator") or "local"
job_args = config.get_object("job_args") or [
    "cycle",
    "--snapshot",
    "/mnt/journal/snapshot.json",
    "--journal",
    "/mnt/journal",
]

bucket = gcp.storage.Bucket(
    "journals",
    gcp.storage.BucketArgs(
        project=project_id,
        name=project_id.lower()[:22] + "-chrs-journals-" + operator.lower()[:8],
        location=region,
        force_destroy=False,
        uniform_bucket_level_access=True,
        versioning=gcp.storage.BucketVersioningArgs(enabled=True),
    ),
)

runner = gcp.serviceaccount.Account(
    "runner",
    gcp.serviceaccount.AccountArgs(
        project=project_id,
        account_id=f"chrysopoeia-runner-{operator}"[:30],
        display_name=f"Chrysopoeia paper-cycle runner ({operator})",
        description=(
            "Job execution identity: Vertex model calls, image reads, and the "
            "journal bucket only."
        ),
    ),
)

serviceaccount_member = pulumi.Output.concat("serviceAccount:", runner.email)

gcp.serviceaccount.IAMMember(
    "runner-vertex-user",
    gcp.serviceaccount.IAMMemberArgs(
        service_account_id=runner.name,
        role="roles/aiplatform.user",
        member=serviceaccount_member,
    ),
)

gcp.storage.BucketIAMMember(
    "runner-bucket-admin",
    gcp.storage.BucketIAMMemberArgs(
        bucket=bucket.name,
        role="roles/storage.objectAdmin",
        member=serviceaccount_member,
    ),
)

repository = gcp.artifactregistry.Repository(
    "images",
    gcp.artifactregistry.RepositoryArgs(
        project=project_id,
        location=region,
        repository_id="chrysopoeia",
        format="DOCKER",
    ),
)

gcp.artifactregistry.RepositoryIamMember(
    "runner-image-reader",
    gcp.artifactregistry.RepositoryIamMemberArgs(
        project=project_id,
        location=repository.location,
        repository=repository.name,
        role="roles/artifactregistry.reader",
        member=serviceaccount_member,
    ),
)

image = pulumi.Output.concat(
    repository.location,
    "-docker.pkg.dev/",
    repository.project,
    "/",
    repository.name,
    "/harness:latest",
)

paper_cycle_job = gcp.cloudrunv2.Job(
    "paper-cycle",
    gcp.cloudrunv2.JobArgs(
        project=project_id,
        location=region,
        name=f"chrysopoeia-cycle-{operator}",
        launch_stage="BETA",
        deletion_protection=False,
        template=gcp.cloudrunv2.JobTemplateArgs(
            task_count=1,
            template=gcp.cloudrunv2.JobTemplateTemplateArgs(
                max_retries=0,
                timeout="900s",
                service_account=runner.email,
                containers=[
                    gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                        name="chrysopoeia",
                        image=image,
                        commands=["uv"],
                        args=["run", "chrysopoeia", *job_args],
                        envs=[
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="GOOGLE_GENAI_USE_VERTEXAI",
                                value="TRUE",
                            ),
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="GOOGLE_CLOUD_PROJECT",
                                value=project_id,
                            ),
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="GOOGLE_CLOUD_LOCATION",
                                value=region,
                            ),
                        ],
                        resources=(
                            gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                                limits={"memory": "512Mi", "cpu": "1"},
                            )
                        ),
                        volume_mounts=[
                            gcp.cloudrunv2.JobTemplateTemplateContainerVolumeMountArgs(
                                name="journal",
                                mount_path="/mnt/journal",
                            ),
                        ],
                    )
                ],
                volumes=[
                    gcp.cloudrunv2.JobTemplateTemplateVolumeArgs(
                        name="journal",
                        gcs=gcp.cloudrunv2.JobTemplateTemplateVolumeGcsArgs(
                            bucket=bucket.name,
                            read_only=False,
                        ),
                    )
                ],
            ),
        ),
    ),
)

pulumi.export("runner_email", runner.email)
pulumi.export("journal_bucket", bucket.url)
pulumi.export("journal_bucket_name", bucket.name)
pulumi.export("image", image)
pulumi.export("job_name", paper_cycle_job.name)
