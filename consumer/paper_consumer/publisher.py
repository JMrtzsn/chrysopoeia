import json
import re

from google.cloud import pubsub_v1


class PubSubOutcomePublisher:
    def __init__(self, topic: str) -> None:
        if re.fullmatch(r"projects/[A-Za-z0-9._:-]+/topics/[A-Za-z0-9._~-]+", topic) is None:
            raise ValueError("outcome topic must be a fully qualified Pub/Sub topic")
        self.client = pubsub_v1.PublisherClient()
        self.topic = topic

    def publish(self, event: dict[str, object]) -> None:
        data = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        self.client.publish(
            self.topic,
            data,
            record_type="consumer_outcome",
            schema_version="1",
        ).result(timeout=10)
