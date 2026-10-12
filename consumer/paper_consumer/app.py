import base64
import binascii
import json
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response

from paper_consumer.core import Config, Consumer, Market, TransientFailure, load_validator
from paper_consumer.market import Polymarket

MAX_EVENT_BYTES = 256 * 1024


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError("JSON constants are prohibited")


def parse_push(value: object) -> object:
    if not isinstance(value, dict) or set(value) - {"message", "subscription", "deliveryAttempt"}:
        raise ValueError("invalid push envelope")
    message = value.get("message")
    if not isinstance(message, dict) or set(message) - {
        "data",
        "messageId",
        "message_id",
        "publishTime",
        "publish_time",
        "attributes",
        "orderingKey",
    }:
        raise ValueError("invalid push envelope")
    data = message.get("data")
    if not isinstance(data, str) or len(data) > MAX_EVENT_BYTES * 2:
        raise ValueError("invalid push data")
    try:
        body = base64.b64decode(data, validate=True)
        if len(body) > MAX_EVENT_BYTES:
            raise ValueError("event is too large")
        return json.loads(body, object_pairs_hook=_pairs, parse_constant=_constant)
    except (binascii.Error, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise ValueError("invalid push data") from None


def create_app(
    config: Config,
    market: Market,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FastAPI:
    app = FastAPI()
    consumer = Consumer(config, market, load_validator())

    @app.post("/push")
    async def push(request: Request) -> Response:
        try:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_EVENT_BYTES * 3:
                    return Response(status_code=400)
            envelope = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
            event = parse_push(envelope)
        except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
            return Response(status_code=400)
        payload_type = event.get("record_type") if isinstance(event, dict) else None
        if payload_type not in {None, "trade_plan_ready"}:
            return Response(status_code=204)
        try:
            consumer.consume(event, clock())
        except TransientFailure:
            return Response(status_code=503)
        return Response(status_code=204)

    @app.post("/sweep")
    def sweep() -> Response:
        try:
            consumer.sweep(clock())
        except TransientFailure:
            return Response(status_code=503)
        return Response(status_code=204)

    return app


def _config() -> Config:
    return Config(
        journal=Path(os.environ.get("CONSUMER_JOURNAL", "/mnt/consumer/ledger.jsonl")),
        bankroll=float(os.environ.get("CONSUMER_BANKROLL", "1000")),
        maximum_stake=float(os.environ.get("CONSUMER_MAXIMUM_STAKE", "10")),
        maximum_market_exposure=float(os.environ.get("CONSUMER_MAXIMUM_MARKET_EXPOSURE", "0.01")),
        maximum_total_exposure=float(os.environ.get("CONSUMER_MAXIMUM_TOTAL_EXPOSURE", "0.10")),
        minimum_edge=float(os.environ.get("CONSUMER_MINIMUM_EDGE", "0.05")),
        fee_rate=float(os.environ.get("CONSUMER_FEE_RATE", "0.02")),
        maximum_loss=float(os.environ.get("CONSUMER_MAXIMUM_LOSS", "100")),
    )


app = create_app(_config(), Polymarket())
