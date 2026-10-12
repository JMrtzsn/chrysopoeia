"""Optional direct event delivery backed by the journal outbox."""

import base64
import json
import os
import warnings
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen as open_url

SINK_ENV = "CHRYSOPOEIA_EVENT_SINK"
TIMEOUT = 30


class _Response(Protocol):
    status: int

    def __enter__(self) -> "_Response": ...

    def __exit__(self, *_: object) -> None: ...


def validate_sink(value: str) -> str:
    """Return a valid sink or raise without exposing its value."""
    if value.startswith("pubsub:projects/"):
        parts = value.removeprefix("pubsub:").split("/")
        if len(parts) == 4 and parts[0] == "projects" and parts[2] == "topics" and all(parts):
            return value
    parsed = urlparse(value)
    if (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and parsed.port is not None
        and parsed.path == "/push"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        return value
    raise ValueError(f"invalid {SINK_ENV}")


def configured_sink() -> str | None:
    """Read and validate the optional event sink."""
    value = os.environ.get(SINK_ENV, "").strip()
    return validate_sink(value) if value else None


def _canonical(event: dict) -> bytes:
    return json.dumps(event, sort_keys=True, separators=(",", ":")).encode()


def publish(
    sink: str,
    event: dict,
    *,
    publisher: object | None = None,
    urlopen: Callable[..., _Response] = open_url,
) -> None:
    """Publish one canonical event and wait for confirmed delivery."""
    validate_sink(sink)
    event_id = str(event["event_id"])
    body = _canonical(event)
    if sink.startswith("pubsub:"):
        if publisher is None:
            from google.cloud import pubsub_v1

            publisher = pubsub_v1.PublisherClient()
        publisher.publish(  # type: ignore[attr-defined]
            sink.removeprefix("pubsub:"), body, event_id=event_id
        ).result(timeout=TIMEOUT)
        return
    now = datetime.now(timezone.utc).isoformat()
    message_id = "local-" + event_id
    envelope = {
        "message": {
            "attributes": {"event_id": event_id},
            "data": base64.b64encode(body).decode(),
            "messageId": message_id,
            "message_id": message_id,
            "publishTime": now,
            "publish_time": now,
        },
        "subscription": "projects/local/subscriptions/local",
        "deliveryAttempt": 1,
    }
    request = Request(
        sink,
        data=_canonical(envelope),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError("event delivery failed")
    except Exception as exc:
        raise RuntimeError("event delivery failed") from exc


def drain(
    journal: Path,
    sink: str,
    *,
    sender: Callable[[str, dict], None] | None = None,
) -> None:
    """Publish pending events oldest-first, stopping safely on failure."""
    from chrysopoeia.accounting import acknowledge_event, pending_events

    sender = sender or publish
    for event in pending_events(journal):
        try:
            sender(sink, event)
        except Exception:
            warnings.warn("event delivery failed; event remains pending", stacklevel=2)
            return
        acknowledge_event(journal, str(event["event_id"]))
