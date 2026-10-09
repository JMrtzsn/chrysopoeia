import unittest
from pathlib import Path


class InfraContractTests(unittest.TestCase):
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
        self.assertIn("disable_on_destroy=True", optional_resources)
        self.assertIn("gcp.pubsub.Topic(", optional_resources)
        self.assertIn("opts=pulumi.ResourceOptions(depends_on=[pubsub_service])", optional_resources)
        self.assertIn("gcp.pubsub.TopicIAMMember(", optional_resources)
        self.assertIn('role="roles/pubsub.publisher"', optional_resources)
        self.assertNotIn('role="roles/pubsub.publisher"', source.split("if pubsub_topic:", 1)[0])


if __name__ == "__main__":
    unittest.main()
