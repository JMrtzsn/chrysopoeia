"""Post one trade_plan_ready event to a locally running paper consumer.

Usage:
    python scripts/send_event.py event.json [--url http://127.0.0.1:8080]
    python scripts/send_event.py --sweep [--url http://127.0.0.1:8080]
"""

import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def event_id(snapshot_id: str, market_id: str) -> str:
    identity = json.dumps([snapshot_id, market_id], separators=(",", ":"))
    return "turn-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def envelope(event: dict[str, object]) -> dict[str, object]:
    """Wrap an event exactly like a real Pub/Sub push request body."""
    now = datetime.now(timezone.utc).isoformat()
    message_id = "local-" + str(event["event_id"])
    return {
        "message": {
            "attributes": {"event_id": str(event["event_id"])},
            "data": base64.b64encode(json.dumps(event, sort_keys=True).encode()).decode(),
            "messageId": message_id,
            "message_id": message_id,
            "publishTime": now,
            "publish_time": now,
        },
        "subscription": "projects/local/subscriptions/local",
        "deliveryAttempt": 1,
    }


def post(url: str, body: dict[str, object] | None) -> int:
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data or b"", method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=30) as response:
            return response.status
    except HTTPError as exc:
        return exc.code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("event", nargs="?", type=Path, help="trade_plan_ready JSON file")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--sweep", action="store_true", help="trigger one exit sweep")
    args = parser.parse_args(argv)
    if args.sweep:
        status = post(args.url + "/sweep", None)
    else:
        if args.event is None:
            parser.error("an event file or --sweep is required")
        event = json.loads(args.event.read_text())
        expected = event_id(str(event["snapshot_id"]), str(event["market_id"]))
        if event.get("event_id") != expected:
            print(f"event_id must be {expected}", file=sys.stderr)
            return 2
        status = post(args.url + "/push", envelope(event))
    print(status)
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
