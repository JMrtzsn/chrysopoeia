# Paper consumer

This independent FastAPI service accepts authenticated Pub/Sub push requests at
`POST /push` and authenticated Scheduler requests at `POST /sweep`. Authentication
is enforced by Cloud Run IAM. The service validates the Harness-owned v1 schema,
fetches bounded public metadata/books, independently checks risk and depth, and
records paper-only outcomes in its own append-only journal.

It is an idempotent consumer under at-least-once delivery: redeliveries with
the same `event_id` never repeat a fill, and failures after ten attempts land in
the dead-letter queue. See the event-driven architecture table in
`../README.md`.

Configuration is through `CONSUMER_JOURNAL`, `CONSUMER_BANKROLL`,
`CONSUMER_MAXIMUM_STAKE`, `CONSUMER_MAXIMUM_MARKET_EXPOSURE`,
`CONSUMER_MAXIMUM_TOTAL_EXPOSURE`, `CONSUMER_MAXIMUM_LOSS`,
`CONSUMER_MINIMUM_EDGE`, and `CONSUMER_FEE_RATE`. Defaults are paper bankroll
1000, stake 10, market 1%, total 10%, cumulative loss 100, edge 5%, and 2% paper
fees.

No model, credentials, signing, order, or live-execution code exists here.

## Run locally

For manual debugging and trying market adapters against real public data:

```sh
uv sync
CONSUMER_JOURNAL=/tmp/consumer/ledger.jsonl \
  uv run uvicorn paper_consumer.app:app --host 127.0.0.1 --port 8080 --workers 1
```

In another shell:

```sh
uv run python scripts/send_event.py event.json   # POST /push, prints HTTP status
uv run python scripts/send_event.py --sweep      # POST /sweep (exits/settlement)
cat /tmp/consumer/ledger.jsonl
```

`event.json` is a `trade_plan_ready` v1 event
(`../contracts/trade_plan_ready.v1.schema.json`). Its `event_id` must be
`turn-` + the first 24 hex chars of SHA-256 over compact JSON
`[snapshot_id, market_id]`; the script checks this and wraps the event in the
real Pub/Sub push envelope.

- Local runs have no authentication; bind to `127.0.0.1` only.
- The service makes real public Polymarket Gamma/CLOB reads. Fills are paper only.
- `204` means a durable fill or terminal rejection; `503` means retryable failure.

## Adding a market provider

A provider implements the `Market` protocol in `paper_consumer/core.py`:
`load(market_id, token_id, now) -> Quote`. Normalize the venue's response into
`Quote` (executable book, freshness timestamp, resolution) before any risk check
sees it, and follow the `PublicMarketTests` pattern for bounded, strict parsing.
Only Polymarket exists today; `app.py` selects it directly.
