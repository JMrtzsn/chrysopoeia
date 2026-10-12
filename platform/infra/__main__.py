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
pubsub_topic = config.get("pubsub_topic")
consumer_image_digest = config.get("consumer_image_digest")
consumer_sweep_schedule = config.get("consumer_sweep_schedule") or "* * * * *"
if consumer_image_digest and not pubsub_topic:
    pubsub_topic = config.require("pubsub_topic")

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

if pubsub_topic:
    pubsub_service = gcp.projects.Service(
        "pubsub-service",
        gcp.projects.ServiceArgs(
            project=project_id,
            service="pubsub.googleapis.com",
            disable_dependent_services=False,
            disable_on_destroy=False,
        ),
    )
    topic = gcp.pubsub.Topic(
        "trade-plans",
        gcp.pubsub.TopicArgs(project=project_id, name=pubsub_topic),
        opts=pulumi.ResourceOptions(depends_on=[pubsub_service]),
    )
    gcp.pubsub.TopicIAMMember(
        "runner-publisher",
        gcp.pubsub.TopicIAMMemberArgs(
            project=project_id,
            topic=topic.name,
            role="roles/pubsub.publisher",
            member=serviceaccount_member,
        ),
    )

gcp.projects.IAMMember(
    "runner-vertex-user",
    gcp.projects.IAMMemberArgs(
        project=project_id,
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

run_service = gcp.projects.Service(
    "run-service",
    gcp.projects.ServiceArgs(
        project=project_id,
        service="run.googleapis.com",
        disable_dependent_services=False,
        disable_on_destroy=True,
    ),
)

artifact_services = gcp.projects.Service(
    "artifact-services",
    gcp.projects.ServiceArgs(
        project=project_id,
        service="artifactregistry.googleapis.com",
        disable_dependent_services=False,
        disable_on_destroy=True,
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
    opts=pulumi.ResourceOptions(depends_on=[run_service, artifact_services]),
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

digest = config.get("image_digest")
if digest:
    image = digest
else:
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
        launch_stage="GA",
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
                        args=job_args,
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
                            *(
                                [
                                    gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                        name="CHRYSOPOEIA_EVENT_SINK",
                                        value=pulumi.Output.concat(
                                            "pubsub:projects/", project_id, "/topics/", topic.name
                                        ),
                                    ),
                                ]
                                if pubsub_topic
                                else []
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

if consumer_image_digest and pubsub_topic:
    scheduler_service = gcp.projects.Service(
        "scheduler-service",
        gcp.projects.ServiceArgs(
            project=project_id,
            service="cloudscheduler.googleapis.com",
            disable_dependent_services=False,
            disable_on_destroy=False,
        ),
    )
    consumer_bucket = gcp.storage.Bucket(
        "consumer-ledger",
        gcp.storage.BucketArgs(
            project=project_id,
            name=project_id.lower()[:20] + "-chrs-consumer-" + operator.lower()[:8],
            location=region,
            force_destroy=False,
            uniform_bucket_level_access=True,
            versioning=gcp.storage.BucketVersioningArgs(enabled=True),
        ),
    )
    consumer = gcp.serviceaccount.Account(
        "consumer",
        gcp.serviceaccount.AccountArgs(
            project=project_id,
            account_id=f"chrysopoeia-consumer-{operator}"[:30],
            display_name=f"Chrysopoeia paper consumer ({operator})",
        ),
    )
    consumer_member = pulumi.Output.concat("serviceAccount:", consumer.email)
    gcp.storage.BucketIAMMember(
        "consumer-ledger-writer",
        gcp.storage.BucketIAMMemberArgs(
            bucket=consumer_bucket.name,
            role="roles/storage.objectAdmin",
            member=consumer_member,
        ),
    )
    consumer_service = gcp.cloudrunv2.Service(
        "paper-consumer",
        gcp.cloudrunv2.ServiceArgs(
            project=project_id,
            location=region,
            name=f"chrysopoeia-consumer-{operator}",
            ingress="INGRESS_TRAFFIC_ALL",
            deletion_protection=False,
            template=gcp.cloudrunv2.ServiceTemplateArgs(
                service_account=consumer.email,
                max_instance_request_concurrency=1,
                scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
                    min_instance_count=0,
                    max_instance_count=1,
                ),
                containers=[
                    gcp.cloudrunv2.ServiceTemplateContainerArgs(
                        image=consumer_image_digest,
                        envs=[
                            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="CONSUMER_JOURNAL", value="/mnt/consumer/ledger.jsonl"
                            )
                        ],
                        volume_mounts=[
                            gcp.cloudrunv2.ServiceTemplateContainerVolumeMountArgs(
                                name="consumer-ledger", mount_path="/mnt/consumer"
                            )
                        ],
                    )
                ],
                volumes=[
                    gcp.cloudrunv2.ServiceTemplateVolumeArgs(
                        name="consumer-ledger",
                        gcs=gcp.cloudrunv2.ServiceTemplateVolumeGcsArgs(
                            bucket=consumer_bucket.name, read_only=False
                        ),
                    )
                ],
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=[run_service]),
    )
    invoker = gcp.serviceaccount.Account(
        "consumer-invoker",
        gcp.serviceaccount.AccountArgs(
            project=project_id,
            account_id=f"chrysopoeia-invoker-{operator}"[:30],
            display_name=f"Chrysopoeia consumer invoker ({operator})",
        ),
    )
    pubsub_agent = gcp.projects.ServiceIdentity(
        "pubsub-agent",
        gcp.projects.ServiceIdentityArgs(
            project=project_id,
            service="pubsub.googleapis.com",
        ),
        opts=pulumi.ResourceOptions(depends_on=[pubsub_service]),
    )
    pubsub_agent_member = pulumi.Output.concat(
        "serviceAccount:", pubsub_agent.email
    )
    invoker_member = pulumi.Output.concat("serviceAccount:", invoker.email)
    token_creator = gcp.serviceaccount.IAMMember(
        "pubsub-invoker-token-creator",
        gcp.serviceaccount.IAMMemberArgs(
            service_account_id=invoker.name,
            role="roles/iam.serviceAccountTokenCreator",
            member=pubsub_agent_member,
        ),
    )
    run_invoker = gcp.cloudrunv2.ServiceIamMember(
        "consumer-invoker",
        gcp.cloudrunv2.ServiceIamMemberArgs(
            project=project_id,
            location=region,
            name=consumer_service.name,
            role="roles/run.invoker",
            member=invoker_member,
        ),
    )
    dead_letter_topic = gcp.pubsub.Topic(
        "consumer-dead-letter",
        gcp.pubsub.TopicArgs(project=project_id, name=f"{pubsub_topic}-dead-letter"),
        opts=pulumi.ResourceOptions(depends_on=[pubsub_service]),
    )
    dead_letter_publisher = gcp.pubsub.TopicIAMMember(
        "consumer-dead-letter-publisher",
        gcp.pubsub.TopicIAMMemberArgs(
            project=project_id,
            topic=dead_letter_topic.name,
            role="roles/pubsub.publisher",
            member=pubsub_agent_member,
        ),
    )
    consumer_subscription = gcp.pubsub.Subscription(
        "paper-consumer",
        gcp.pubsub.SubscriptionArgs(
            project=project_id,
            topic=topic.id,
            ack_deadline_seconds=60,
            message_retention_duration="604800s",
            filter='attributes.record_type = "trade_plan_ready"',
            push_config=gcp.pubsub.SubscriptionPushConfigArgs(
                push_endpoint=pulumi.Output.concat(consumer_service.uri, "/push"),
                oidc_token=gcp.pubsub.SubscriptionPushConfigOidcTokenArgs(
                    service_account_email=invoker.email,
                    audience=consumer_service.uri,
                ),
            ),
            retry_policy=gcp.pubsub.SubscriptionRetryPolicyArgs(
                minimum_backoff="10s", maximum_backoff="600s"
            ),
            dead_letter_policy=gcp.pubsub.SubscriptionDeadLetterPolicyArgs(
                dead_letter_topic=dead_letter_topic.id, max_delivery_attempts=10
            ),
        ),
        opts=pulumi.ResourceOptions(
            depends_on=[
                pubsub_service,
                pubsub_agent,
                token_creator,
                consumer_service,
                run_invoker,
                dead_letter_publisher,
            ]
        ),
    )
    gcp.pubsub.SubscriptionIAMMember(
        "consumer-dead-letter-subscriber",
        gcp.pubsub.SubscriptionIAMMemberArgs(
            project=project_id,
            subscription=consumer_subscription.name,
            role="roles/pubsub.subscriber",
            member=pubsub_agent_member,
        ),
    )
    dead_letter_subscription = gcp.pubsub.Subscription(
        "consumer-dead-letter-retention",
        gcp.pubsub.SubscriptionArgs(
            project=project_id,
            topic=dead_letter_topic.id,
            message_retention_duration="604800s",
            expiration_policy=gcp.pubsub.SubscriptionExpirationPolicyArgs(ttl="2678400s"),
        ),
    )
    consumer_sweep_job = gcp.cloudscheduler.Job(
        "consumer-sweep",
        gcp.cloudscheduler.JobArgs(
            project=project_id,
            region=region,
            schedule=consumer_sweep_schedule,
            time_zone="Etc/UTC",
            http_target=gcp.cloudscheduler.JobHttpTargetArgs(
                uri=pulumi.Output.concat(consumer_service.uri, "/sweep"),
                http_method="POST",
                oidc_token=gcp.cloudscheduler.JobHttpTargetOidcTokenArgs(
                    service_account_email=invoker.email,
                    audience=consumer_service.uri,
                ),
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=[scheduler_service]),
    )
    pulumi.export("consumer_service_url", consumer_service.uri)
    pulumi.export("consumer_ledger_bucket_name", consumer_bucket.name)
    pulumi.export("consumer_subscription_name", consumer_subscription.name)
    pulumi.export("consumer_dead_letter_topic_name", dead_letter_topic.name)
    pulumi.export(
        "consumer_dead_letter_subscription_name", dead_letter_subscription.name
    )
    pulumi.export("consumer_sweep_job_name", consumer_sweep_job.name)

pulumi.export("runner_email", runner.email)
pulumi.export("journal_bucket", bucket.url)
pulumi.export("journal_bucket_name", bucket.name)
pulumi.export("image", image)
pulumi.export("job_name", paper_cycle_job.name)
