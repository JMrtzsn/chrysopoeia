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

import base64
import json
import os

import pulumi
import pulumi_gcp as gcp

# Running the platform is explicit. Previews are always allowed, but any real
# apply or destroy requires the operator to opt in for that invocation.
if not pulumi.runtime.is_dry_run() and os.environ.get("CHRYSOPOEIA_RUN_PLATFORM") != "1":
    raise pulumi.RunError(
        "refusing to apply the platform; set CHRYSOPOEIA_RUN_PLATFORM=1 to confirm"
    )

config = pulumi.Config()
project_id = config.require("project_id")
region = config.get("region") or "us-central1"
operator = config.get("operator") or "local"
job_args = config.get_object("job_args") or [
    "run",
    "--journal",
    "/mnt/journal/run",
]
pubsub_topic = config.get("pubsub_topic")
consumer_image_digest = config.get("consumer_image_digest")
consumer_sweep_schedule = config.get("consumer_sweep_schedule") or "* * * * *"
context_history_enabled = config.get_bool("context_history_enabled") or False
observer_image_digest = config.get("observer_image_digest")
observer_invoker_member = config.get("observer_invoker_member")
billing_account_id = config.get("billing_account_id")
budget_amount_usd = config.get("budget_amount_usd")
budget_currency = config.get("budget_currency") or "SEK"
scan_schedule = config.get("scan_schedule")
scan_paused = config.get_bool("scan_paused") or False
if consumer_image_digest and not pubsub_topic:
    pubsub_topic = config.require("pubsub_topic")
if context_history_enabled and not pubsub_topic:
    raise pulumi.RunError("context history requires the configured event archive topic")
if observer_image_digest and not pubsub_topic:
    raise pulumi.RunError("observer requires the configured event archive topic")
if budget_amount_usd and not billing_account_id:
    raise pulumi.RunError("budget_amount_usd requires billing_account_id")
if scan_schedule and not job_args:
    raise pulumi.RunError("scheduled scanning requires job_args")
if observer_image_digest and not observer_invoker_member:
    raise pulumi.RunError("observer requires observer_invoker_member")
if observer_invoker_member in {"allUsers", "allAuthenticatedUsers"}:
    raise pulumi.RunError("observer invoker must be a private identity")

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
            "Job execution identity: Vertex model calls, image reads, and journal "
            "bucket, plus read-only context history."
            if context_history_enabled
            else "Job execution identity: Vertex model calls, image reads, and the journal bucket only."
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
    pubsub_agent = gcp.projects.ServiceIdentity(
        "pubsub-agent",
        gcp.projects.ServiceIdentityArgs(
            project=project_id,
            service="pubsub.googleapis.com",
        ),
        opts=pulumi.ResourceOptions(depends_on=[pubsub_service]),
    )
    pubsub_agent_member = pulumi.Output.concat("serviceAccount:", pubsub_agent.email)
    archive_api = gcp.projects.Service(
        "archive-api",
        gcp.projects.ServiceArgs(
            project=project_id,
            service="bigquery.googleapis.com",
            disable_dependent_services=False,
            disable_on_destroy=False,
        ),
    )
    archive_dataset = gcp.bigquery.Dataset(
        "event-archive",
        gcp.bigquery.DatasetArgs(
            project=project_id,
            dataset_id=f"chrysopoeia_events_{operator.replace('-', '_')}",
            location=region,
            description="Raw event analytics archive; not an authoritative financial ledger.",
            delete_contents_on_destroy=False,
        ),
        opts=pulumi.ResourceOptions(
            depends_on=[archive_api], protect=True, retain_on_delete=True
        ),
    )
    archive_table = gcp.bigquery.Table(
        "raw-events",
        gcp.bigquery.TableArgs(
            project=project_id,
            dataset_id=archive_dataset.dataset_id,
            table_id="raw_events",
            deletion_protection=True,
            schema=json.dumps(
                [
                    {"name": "data", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "attributes", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "message_id", "type": "STRING", "mode": "NULLABLE"},
                    {"name": "publish_time", "type": "TIMESTAMP", "mode": "NULLABLE"},
                    {"name": "subscription_name", "type": "STRING", "mode": "NULLABLE"},
                ]
            ),
            time_partitioning=gcp.bigquery.TableTimePartitioningArgs(
                type="DAY", field="publish_time"
            ),
            require_partition_filter=True,
        ),
        opts=pulumi.ResourceOptions(protect=True, retain_on_delete=True),
    )
    archive_writer = gcp.bigquery.IamMember(
        "archive-writer",
        gcp.bigquery.IamMemberArgs(
            project=project_id,
            dataset_id=archive_dataset.dataset_id,
            table_id=archive_table.table_id,
            role="roles/bigquery.dataEditor",
            member=pubsub_agent_member,
        ),
    )
    archive_subscription = gcp.pubsub.Subscription(
        "event-archive",
        gcp.pubsub.SubscriptionArgs(
            project=project_id,
            name=f"{pubsub_topic}-bigquery",
            topic=topic.id,
            message_retention_duration="2678400s",
            expiration_policy=gcp.pubsub.SubscriptionExpirationPolicyArgs(ttl=""),
            bigquery_config=gcp.pubsub.SubscriptionBigqueryConfigArgs(
                table=pulumi.Output.concat(
                    project_id,
                    ".",
                    archive_dataset.dataset_id,
                    ".",
                    archive_table.table_id,
                ),
                write_metadata=True,
                use_topic_schema=False,
                use_table_schema=False,
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=[archive_writer]),
    )
    pulumi.export("event_archive_table", archive_subscription.bigquery_config.table)
    pulumi.export("event_archive_subscription", archive_subscription.name)

    if context_history_enabled:
        gcp.projects.IAMMember(
            "runner-bigquery-job-user",
            gcp.projects.IAMMemberArgs(
                project=project_id,
                role="roles/bigquery.jobUser",
                member=serviceaccount_member,
            ),
            opts=pulumi.ResourceOptions(depends_on=[archive_api]),
        )
        gcp.bigquery.DatasetIamMember(
            "runner-event-archive-reader",
            gcp.bigquery.DatasetIamMemberArgs(
                project=project_id,
                dataset_id=archive_dataset.dataset_id,
                role="roles/bigquery.dataViewer",
                member=serviceaccount_member,
            ),
            opts=pulumi.ResourceOptions(depends_on=[archive_dataset]),
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
                                name="CHRYSOPOEIA_CONFIG",
                                value="/etc/chrysopoeia-platform.toml",
                            ),
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
                            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                name="CHRYSOPOEIA_CONTEXT_CATALOG",
                                value="/mnt/journal/context_profiles.jsonl",
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
                            *(
                                [
                                    gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                        name="CHRYSOPOEIA_HISTORY_TABLE",
                                        value=pulumi.Output.concat(
                                            project_id,
                                            ".",
                                            archive_dataset.dataset_id,
                                            ".raw_events",
                                        ),
                                    ),
                                    gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                                        name="CHRYSOPOEIA_HISTORY_LOCATION",
                                        value=region,
                                    ),
                                ]
                                if context_history_enabled and pubsub_topic
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

# Bounded job-trigger queue: operator campaigns enqueue individually scheduled
# HTTP tasks that execute the paper-cycle job with per-task journal args. The
# queue is inert and free when empty; pausing or purging it stops a campaign.
tasks_service = gcp.projects.Service(
    "tasks-service",
    gcp.projects.ServiceArgs(
        project=project_id,
        service="cloudtasks.googleapis.com",
        disable_dependent_services=False,
        disable_on_destroy=False,
    ),
)
trigger = gcp.serviceaccount.Account(
    "job-trigger",
    gcp.serviceaccount.AccountArgs(
        project=project_id,
        account_id=f"chrysopoeia-trigger-{operator}"[:30],
        display_name=f"Chrysopoeia job-trigger queue identity ({operator})",
        description="Executes the paper-cycle job with arg overrides from queued campaign tasks only.",
    ),
)
trigger_member = pulumi.Output.concat("serviceAccount:", trigger.email)
trigger_role = gcp.projects.IAMCustomRole(
    "job-trigger-role",
    gcp.projects.IAMCustomRoleArgs(
        project=project_id,
        role_id=f"chrysopoeia_job_trigger_{operator.replace('-', '_')}"[:64],
        title=f"Chrysopoeia job trigger ({operator})",
        permissions=["run.jobs.run", "run.jobs.runWithOverrides"],
    ),
)
gcp.projects.IAMMember(
    "job-trigger-executor",
    gcp.projects.IAMMemberArgs(
        project=project_id,
        role=trigger_role.name,
        member=trigger_member,
    ),
)
tasks_agent = gcp.projects.ServiceIdentity(
    "tasks-agent",
    gcp.projects.ServiceIdentityArgs(
        project=project_id,
        service="cloudtasks.googleapis.com",
    ),
    opts=pulumi.ResourceOptions(depends_on=[tasks_service]),
)
gcp.serviceaccount.IAMMember(
    "tasks-agent-token-creator",
    gcp.serviceaccount.IAMMemberArgs(
        service_account_id=trigger.name,
        role="roles/iam.serviceAccountTokenCreator",
        member=pulumi.Output.concat("serviceAccount:", tasks_agent.email),
    ),
)
trigger_queue = gcp.cloudtasks.Queue(
    "job-trigger",
    gcp.cloudtasks.QueueArgs(
        project=project_id,
        location=region,
        name=f"chrysopoeia-trigger-{operator}",
    ),
    opts=pulumi.ResourceOptions(depends_on=[tasks_service]),
)
pulumi.export("trigger_queue_name", trigger_queue.name)
pulumi.export("trigger_sa_email", trigger.email)

# Read-only archive Observer: private by IAM, no ledger, storage, or publishing.
if observer_image_digest and pubsub_topic:
    observer = gcp.serviceaccount.Account(
        "observer",
        gcp.serviceaccount.AccountArgs(
            project=project_id,
            account_id=f"chrysopoeia-observer-{operator}"[:30],
            display_name=f"Chrysopoeia archive observer ({operator})",
            description="Runs read-only queries against the event archive only.",
        ),
    )
    observer_member = pulumi.Output.concat("serviceAccount:", observer.email)
    gcp.projects.IAMMember(
        "observer-bigquery-job-user",
        gcp.projects.IAMMemberArgs(
            project=project_id,
            role="roles/bigquery.jobUser",
            member=observer_member,
        ),
        opts=pulumi.ResourceOptions(depends_on=[archive_api]),
    )
    gcp.bigquery.DatasetIamMember(
        "observer-event-archive-reader",
        gcp.bigquery.DatasetIamMemberArgs(
            project=project_id,
            dataset_id=archive_dataset.dataset_id,
            role="roles/bigquery.dataViewer",
            member=observer_member,
        ),
        opts=pulumi.ResourceOptions(depends_on=[archive_dataset]),
    )
    observer_service = gcp.cloudrunv2.Service(
        "observer-service",
        gcp.cloudrunv2.ServiceArgs(
            project=project_id,
            location=region,
            name=f"chrysopoeia-observer-{operator}",
            ingress="INGRESS_TRAFFIC_ALL",
            deletion_protection=False,
            template=gcp.cloudrunv2.ServiceTemplateArgs(
                service_account=observer.email,
                max_instance_request_concurrency=1,
                scaling=gcp.cloudrunv2.ServiceTemplateScalingArgs(
                    min_instance_count=0,
                    max_instance_count=1,
                ),
                containers=[
                    gcp.cloudrunv2.ServiceTemplateContainerArgs(
                        image=observer_image_digest,
                        envs=[
                            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="GOOGLE_CLOUD_PROJECT", value=project_id
                            ),
                            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="OBSERVER_ARCHIVE_TABLE",
                                value=pulumi.Output.concat(
                                    project_id, ".", archive_dataset.dataset_id, ".raw_events"
                                ),
                            ),
                            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="OBSERVER_BIGQUERY_LOCATION", value=region
                            ),
                        ],
                    )
                ],
            ),
        ),
        opts=pulumi.ResourceOptions(depends_on=[run_service]),
    )
    gcp.cloudrunv2.ServiceIamMember(
        "observer-invoker",
        gcp.cloudrunv2.ServiceIamMemberArgs(
            project=project_id,
            location=region,
            name=observer_service.name,
            role="roles/run.invoker",
            member=observer_invoker_member,
        ),
    )
    pulumi.export("observer_service_url", observer_service.uri)
    pulumi.export("observer_runtime_email", observer.email)

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
    gcp.pubsub.TopicIAMMember(
        "consumer-outcome-publisher",
        gcp.pubsub.TopicIAMMemberArgs(
            project=project_id,
            topic=topic.name,
            role="roles/pubsub.publisher",
            member=consumer_member,
        ),
    )
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
                            ),
                            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                                name="CHRYSOPOEIA_EVENT_TOPIC",
                                value=pulumi.Output.concat(
                                    "projects/", project_id, "/topics/", topic.name
                                ),
                            ),
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

# Item 8(a): native billing budget on the project (billing-domain alert only).
if budget_amount_usd:
    budgets_service = gcp.projects.Service(
        "billing-budgets-service",
        gcp.projects.ServiceArgs(
            project=project_id,
            service="billingbudgets.googleapis.com",
            disable_dependent_services=False,
            disable_on_destroy=False,
        ),
    )
    project_number = gcp.organizations.get_project(project_id=project_id).number
    gcp.billing.Budget(
        "spend-budget",
        gcp.billing.BudgetArgs(
            billing_account=billing_account_id,
            display_name=f"Chrysopoeia spend budget ({operator})",
            budget_filter=gcp.billing.BudgetBudgetFilterArgs(
                projects=[f"projects/{project_number}"],
            ),
            amount=gcp.billing.BudgetAmountArgs(
                specified_amount=gcp.billing.BudgetAmountSpecifiedAmountArgs(
                    currency_code=budget_currency,
                    units=budget_amount_usd,
                ),
            ),
            threshold_rules=[
                gcp.billing.BudgetThresholdRuleArgs(
                    threshold_percent=0.5, spend_basis="CURRENT_SPEND"
                ),
                gcp.billing.BudgetThresholdRuleArgs(
                    threshold_percent=0.9, spend_basis="CURRENT_SPEND"
                ),
                gcp.billing.BudgetThresholdRuleArgs(
                    threshold_percent=1.0, spend_basis="CURRENT_SPEND"
                ),
            ],
        ),
        opts=pulumi.ResourceOptions(depends_on=[budgets_service]),
    )

# Item 8(b): scheduled opportunity scanning. Cloud Scheduler invokes the
# workflow, which computes a fresh minute-keyed journal name per tick and
# requests one paper-cycle job execution with args overridden per execution.
# The workflow runtime identity is the existing least-privilege trigger
# identity (run.jobs.run and runWithOverrides only). The schedule is created
# paused unless scan_paused is set; enabling it is an explicit config change.
if scan_schedule:
    workflows_service = gcp.projects.Service(
        "workflows-service",
        gcp.projects.ServiceArgs(
            project=project_id,
            service="workflows.googleapis.com",
            disable_dependent_services=False,
            disable_on_destroy=False,
        ),
    )
    scan_workflow_name = f"chrysopoeia-scan-{operator}"
    scheduler_agent_member = pulumi.Output.concat(
        "serviceAccount:service-",
        str(gcp.organizations.get_project(project_id=project_id).number),
        "@gcp-sa-cloudscheduler.iam.gserviceaccount.com",
    )
    gcp.serviceaccount.IAMMember(
        "scan-scheduler-token-creator",
        gcp.serviceaccount.IAMMemberArgs(
            service_account_id=trigger.name,
            role="roles/iam.serviceAccountTokenCreator",
            member=scheduler_agent_member,
        ),
    )
    scan_source = pulumi.Output.concat(
        "main:\n"
        "  steps:\n"
        "    - init:\n"
        "        assign:\n"
        "          - stamp: ${time.format(sys.now())}\n"
        "    - run:\n"
        "        call: googleapis.run.v2.projects.locations.jobs.run\n"
        "        args:\n"
        "          name: \"projects/",
        project_id,
        "/locations/",
        region,
        "/jobs/chrysopoeia-cycle-",
        operator,
        """"\n
          body:
            overrides:
              containerOverrides:
                - args:
                    - run
                    - --journal
                    - ${"/mnt/journal/esports-" + stamp}
          connector_params:
            skip_polling: True
        result: accepted
    - done:
        return: ${accepted.name}
""",
    )
    scan_workflow = gcp.workflows.Workflow(
        "scan-workflow",
        gcp.workflows.WorkflowArgs(
            project=project_id,
            region=region,
            name=scan_workflow_name,
            service_account=trigger.email,
            source_contents=scan_source,
        ),
        opts=pulumi.ResourceOptions(depends_on=[workflows_service]),
    )
    gcp.projects.IAMMember(
        "scan-workflow-invoker",
        gcp.projects.IAMMemberArgs(
            project=project_id,
            role="roles/workflows.invoker",
            member=trigger_member,
        ),
    )
    scan_schedule_job = gcp.cloudscheduler.Job(
        "cycle-scan",
        gcp.cloudscheduler.JobArgs(
            project=project_id,
            region=region,
            name=f"chrysopoeia-scan-{operator}",
            schedule=scan_schedule,
            time_zone="Etc/UTC",
            paused=scan_paused,
            attempt_deadline="120s",
            http_target=gcp.cloudscheduler.JobHttpTargetArgs(
                # Workflows executes.create accepts OAuth2 access tokens only;
                # the documented scheduler integration uses one (not OIDC).
                uri=pulumi.Output.concat(
                    "https://workflowexecutions.googleapis.com/v1/projects/",
                    project_id,
                    "/locations/",
                    region,
                    "/workflows/",
                    scan_workflow_name,
                    "/executions",
                ),
                http_method="POST",
                headers={
                    "Content-Type": "application/octet-stream",
                    "User-Agent": "Google-Cloud-Scheduler",
                },
                body=base64.b64encode(b'{"argument": "{}"}').decode(),
                oauth_token=gcp.cloudscheduler.JobHttpTargetOauthTokenArgs(
                    service_account_email=trigger.email,
                    scope="https://www.googleapis.com/auth/cloud-platform",
                ),
            ),
        ),
        opts=pulumi.ResourceOptions(
            depends_on=[workflows_service, scan_workflow]
        ),
    )
    pulumi.export("scan_schedule_name", scan_schedule_job.name)
    pulumi.export("scan_workflow_name", scan_workflow.name)

pulumi.export("runner_email", runner.email)
pulumi.export("journal_bucket", bucket.url)
pulumi.export("journal_bucket_name", bucket.name)
pulumi.export("image", image)
pulumi.export("job_name", paper_cycle_job.name)
