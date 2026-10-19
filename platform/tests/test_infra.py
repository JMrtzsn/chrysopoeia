import re
import unittest
from pathlib import Path


class InfraContractTests(unittest.TestCase):
    def test_job_uses_bundled_operating_config_without_setting_flags(self) -> None:
        root = Path(__file__).parents[1]
        source = root.joinpath("infra", "__main__.py").read_text()
        dockerfile = root.joinpath("Dockerfile").read_text()
        build = root.joinpath("build.sh").read_text()
        stack = root.joinpath("infra", "Pulumi.local-dev.yaml").read_text()

        self.assertIn('name="CHRYSOPOEIA_CONFIG"', source)
        self.assertIn('value="/etc/chrysopoeia-platform.toml"', source)
        self.assertIn("COPY .build/platform.toml /etc/chrysopoeia-platform.toml", dockerfile)
        self.assertIn('"$HARNESS_DIR/configs/platform.toml"', build)
        self.assertIn("validate --config /etc/chrysopoeia-platform.toml --json", build)
        self.assertIn('["run","--journal","/mnt/journal/run"]', stack)
        self.assertNotIn("--max-cycles", stack)

    def test_image_installs_the_locked_dependency_set(self) -> None:
        root = Path(__file__).parents[1]
        dockerfile = root.joinpath("Dockerfile").read_text()
        build = root.joinpath("build.sh").read_text()

        self.assertIn("uv export --frozen", build)
        self.assertIn("--no-emit-project", build)
        self.assertIn("COPY .build/requirements.txt", dockerfile)
        self.assertIn("pip install --no-cache-dir --no-deps -r", dockerfile)
        self.assertIn("pip install --no-cache-dir --no-deps /tmp/harness/*.whl", dockerfile)
        self.assertNotIn("pip install --no-cache-dir /tmp/harness/*.whl", dockerfile)
        # The dependency layer must stay before wheel/config copies, or every
        # code change rebuilds and re-pushes the whole dependency layer.
        self.assertLess(
            dockerfile.index("COPY .build/requirements.txt"),
            dockerfile.index("COPY .build/*.whl"),
        )
        self.assertLess(
            dockerfile.index("RUN pip install --no-cache-dir --no-deps -r"),
            dockerfile.index("COPY .build/*.whl"),
        )
        for path in (
            "/etc/chrysopoeia.toml",
            "/etc/chrysopoeia-platform.toml",
        ):
            self.assertLess(
                dockerfile.index("RUN pip install --no-cache-dir --no-deps -r"),
                dockerfile.index(path),
            )

    def test_archive_storage_is_protected_and_retained_independently_of_runtime(self) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()
        dataset = source.split("    archive_dataset =", 1)[1].split(
            "    archive_table =", 1
        )[0]
        table = source.split("    archive_table =", 1)[1].split(
            "    archive_writer =", 1
        )[0]

        for storage in (dataset, table):
            self.assertIn("protect=True", storage)
            self.assertIn("retain_on_delete=True", storage)
        self.assertIn("delete_contents_on_destroy=False", dataset)
        self.assertIn("deletion_protection=True", table)

    def test_event_archive_preserves_raw_data_and_metadata_without_filtering(
        self,
    ) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()
        archive = source.split("    archive_api =", 1)[1].split(
            "\ngcp.projects.IAMMember(", 1
        )[0]

        self.assertIn("gcp.bigquery.Dataset(", archive)
        self.assertIn("gcp.bigquery.Table(", archive)
        self.assertIn("deletion_protection=True", archive)
        self.assertIn("delete_contents_on_destroy=False", archive)
        for field in (
            "data",
            "attributes",
            "message_id",
            "publish_time",
            "subscription_name",
        ):
            self.assertIn(f'"name": "{field}"', archive)
        self.assertIn('field="publish_time"', archive)
        self.assertIn("require_partition_filter=True", archive)
        self.assertIn("gcp.bigquery.IamMember(", archive)
        self.assertIn('role="roles/bigquery.dataEditor"', archive)
        self.assertIn("write_metadata=True", archive)
        self.assertIn("use_topic_schema=False", archive)
        self.assertIn("use_table_schema=False", archive)
        self.assertIn('SubscriptionExpirationPolicyArgs(ttl="")', archive)
        self.assertIn('message_retention_duration="2678400s"', archive)
        self.assertIn("depends_on=[archive_writer]", archive)
        self.assertNotRegex(archive, r"(?m)^\s+filter=")
        self.assertNotIn("expiration_ms", archive)

    def test_cloud_run_job_uses_observed_ga_launch_stage(self) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()

        self.assertIn('launch_stage="GA"', source)

    def test_pubsub_resources_are_optional_and_topic_scoped(self) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()
        optional_resources = source.split("if pubsub_topic:", 1)[1].split(
            "gcp.projects.IAMMember(", 1
        )[0]

        self.assertIn('pubsub_topic = config.get("pubsub_topic")', source)
        self.assertIn("if pubsub_topic:", source)
        self.assertNotIn(
            'service="pubsub.googleapis.com"', source.split("if pubsub_topic:", 1)[0]
        )
        self.assertIn("gcp.projects.Service(", optional_resources)
        self.assertIn('service="pubsub.googleapis.com"', optional_resources)
        # Removing the optional integration must never disable the shared, pre-existing APIs.
        self.assertIn("disable_on_destroy=False", optional_resources)
        self.assertNotIn(
            "disable_on_destroy=True",
            source.split("if consumer_image_digest and pubsub_topic:", 1)[1].split(
                "gcp.storage.Bucket(", 1
            )[0],
        )
        self.assertIn("gcp.pubsub.Topic(", optional_resources)
        self.assertIn("opts=pulumi.ResourceOptions(depends_on=[pubsub_service])", optional_resources)
        self.assertIn("gcp.pubsub.TopicIAMMember(", optional_resources)
        self.assertIn('role="roles/pubsub.publisher"', optional_resources)
        self.assertNotIn('role="roles/pubsub.publisher"', source.split("if pubsub_topic:", 1)[0])
        self.assertIn('name="CHRYSOPOEIA_EVENT_SINK"', source)
        self.assertIn('"pubsub:projects/", project_id, "/topics/", topic.name', source)
        self.assertNotIn("CHRYSOPOEIA_PUBSUB_OUTBOX", source)
        self.assertNotIn("CHRYSOPOEIA_PUBSUB_TOPIC", source)

    def test_image_runs_harness_cli_without_platform_publisher(self) -> None:
        root = Path(__file__).parents[1]
        dockerfile = root.joinpath("Dockerfile").read_text()

        self.assertIn('ENTRYPOINT ["chrysopoeia"]', dockerfile)
        self.assertFalse(root.joinpath("publisher.py").exists())
        self.assertFalse(root.joinpath("tests", "test_publisher.py").exists())

    def test_consumer_resources_require_both_digest_and_topic(self) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()
        requirements = Path(__file__).parents[1].joinpath("infra", "requirements.txt").read_text()
        local_config = Path(__file__).parents[1].joinpath(
            "infra", "Pulumi.local-dev.yaml"
        ).read_text()
        resources = source.split("if consumer_image_digest and pubsub_topic:", 1)[1]

        self.assertIn('consumer_image_digest = config.get("consumer_image_digest")', source)
        self.assertIn("if consumer_image_digest and not pubsub_topic:", source)
        self.assertIn('pubsub_topic = config.require("pubsub_topic")', source)
        self.assertIn("if consumer_image_digest and pubsub_topic:", source)
        self.assertIn("gcp.cloudrunv2.Service(", resources)
        self.assertIn("min_instance_count=0", resources)
        self.assertEqual(resources.count("max_instance_count=1"), 1)
        self.assertIn("max_instance_request_concurrency=1", resources)
        self.assertNotIn("ServiceScalingArgs", resources)
        self.assertIn("gcp.pubsub.Subscription(", resources)
        self.assertIn('filter=\'attributes.record_type = "trade_plan_ready"\'', resources)
        self.assertIn("gcp.cloudscheduler.Job(", resources)
        self.assertIn(
            'consumer_sweep_schedule = config.get("consumer_sweep_schedule") or "* * * * *"',
            source,
        )
        self.assertIn("schedule=consumer_sweep_schedule", resources)
        self.assertIn('role="roles/storage.objectAdmin"', resources)
        self.assertIn('role="roles/run.invoker"', resources)
        self.assertIn('service="cloudscheduler.googleapis.com"', resources)
        self.assertIn("dead_letter_policy=", resources)
        self.assertIn("retry_policy=", resources)
        self.assertIn("pulumi-gcp>=8.41,<9", requirements)
        self.assertNotIn("consumer_image_digest", local_config)
        self.assertIn("chrysopoeia-infra:pubsub_topic: chrysopoeia-events", local_config)

    def test_push_subscription_waits_for_apis_identities_service_and_grants(self) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()
        resources = source.split("if consumer_image_digest and pubsub_topic:", 1)[1]
        subscription = resources.split("consumer_subscription =", 1)[1].split(
            "gcp.pubsub.SubscriptionIAMMember(", 1
        )[0]

        self.assertIn("token_creator = gcp.serviceaccount.IAMMember(", resources)
        self.assertIn("run_invoker = gcp.cloudrunv2.ServiceIamMember(", resources)
        self.assertIn("dead_letter_publisher = gcp.pubsub.TopicIAMMember(", resources)
        self.assertIn("opts=pulumi.ResourceOptions(", subscription)
        dependencies = subscription.split("depends_on=[", 1)[1].split("]", 1)[0]
        self.assertEqual(
            set(re.findall(r"\b[a-z_]+\b", dependencies)),
            {
                "pubsub_service",
                "pubsub_agent",
                "token_creator",
                "consumer_service",
                "run_invoker",
                "dead_letter_publisher",
            },
        )

    def test_consumer_outputs_are_conditional_and_use_resource_values(self) -> None:
        source = Path(__file__).parents[1].joinpath("infra", "__main__.py").read_text()
        before, resources = source.split("if consumer_image_digest and pubsub_topic:", 1)
        conditional, after = resources.split('\npulumi.export("runner_email"', 1)

        self.assertIn("dead_letter_subscription = gcp.pubsub.Subscription(", conditional)
        self.assertIn("consumer_sweep_job = gcp.cloudscheduler.Job(", conditional)
        expected_exports = {
            "consumer_service_url": "consumer_service.uri",
            "consumer_ledger_bucket_name": "consumer_bucket.name",
            "consumer_subscription_name": "consumer_subscription.name",
            "consumer_dead_letter_topic_name": "dead_letter_topic.name",
            "consumer_dead_letter_subscription_name": "dead_letter_subscription.name",
            "consumer_sweep_job_name": "consumer_sweep_job.name",
        }
        for name, value in expected_exports.items():
            export = rf'pulumi\.export\(\s*"{name}",\s*{re.escape(value)}\s*\)'
            self.assertRegex(conditional, export)
            self.assertNotRegex(before, export)
            self.assertNotRegex(after, export)

    def test_consumer_docs_state_single_writer_ceiling_and_unexercised_paths(self) -> None:
        docs = Path(__file__).parents[1].joinpath("docs", "deployment.md").read_text()

        self.assertIn("GCS FUSE", docs)
        self.assertIn("revision rollover", docs)
        self.assertIn("single-writer", docs)
        self.assertIn("consumer_sweep_schedule", docs)
        self.assertIn("future cron", docs)
        self.assertIn("manually trigger exactly one sweep", docs)
        self.assertIn("concurrent\nrevision-rollover writers were not exercised", docs)


if __name__ == "__main__":
    unittest.main()
