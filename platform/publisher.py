"""Optional Pub/Sub adapter around the harness CLI."""

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from google.api_core.exceptions import GoogleAPIError
from google.cloud.pubsub_v1.publisher.exceptions import (
    FlowControlLimitError,
    PublishToPausedOrderingKeyException,
)


class Publisher(Protocol):
    def publish(self, topic: str, data: bytes, **attrs: str) -> Any: ...


Run = Callable[..., Any]


def _journal(args: Sequence[str]) -> str | None:
    for index, arg in enumerate(args):
        if arg.startswith("--journal="):
            return arg.partition("=")[2] or None
        if arg == "--journal":
            return args[index + 1] if index + 1 < len(args) else None
    return None


def drain(
    topic: str,
    journal: str,
    publisher: Publisher,
    *,
    run: Run = subprocess.run,
) -> int:
    pending = run(
        ["chrysopoeia", "outbox-pending", "--journal", journal],
        capture_output=True,
        text=True,
    )
    if pending.returncode:
        return pending.returncode
    for line in pending.stdout.splitlines():
        try:
            event_id = json.loads(line)["event_id"]
            if not isinstance(event_id, str) or not event_id:
                raise ValueError
            publisher.publish(topic, line.encode(), event_id=event_id).result(timeout=30)
        except (
            GoogleAPIError,
            FlowControlLimitError,
            PublishToPausedOrderingKeyException,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
            TimeoutError,
        ):
            return 1
        ack = run(["chrysopoeia", "outbox-ack", "--journal", journal, event_id])
        if ack.returncode:
            return ack.returncode
    return 0


def main(
    args: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    run: Run = subprocess.run,
    publisher: Publisher | None = None,
) -> int:
    args = list(sys.argv[1:] if args is None else args)
    if environ is None:
        import os

        environ = os.environ
    topic = environ.get("CHRYSOPOEIA_PUBSUB_TOPIC")
    if not topic or not args or args[0] not in {"cycle", "run"}:
        return run(["chrysopoeia", *args]).returncode
    journal = _journal(args)
    if journal is None:
        return 2
    if publisher is None:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
    status = drain(topic, journal, publisher, run=run)
    if status:
        return status
    status = run(["chrysopoeia", *args]).returncode
    if status:
        return status
    return drain(topic, journal, publisher, run=run)


if __name__ == "__main__":
    raise SystemExit(main())
