# Paper consumer

Independent, paper-only FastAPI service. It never signs, orders, or holds
credentials or models.

- `POST /push` takes authenticated Pub/Sub pushes; `POST /sweep` takes
  authenticated Scheduler requests (exits/settlement). Cloud Run IAM enforces
  authentication.
- It validates the Harness-owned `trade_plan_ready` v1/v2 schemas, reads bounded
  public Polymarket metadata/books, checks risk and depth itself, and writes
  paper outcomes to its own append-only journal.
- The subscription filters for `trade_plan_ready`; other record types are
  acknowledged without journal writes.
- Delivery is at-least-once: the same `event_id` never fills twice, and failures
  after ten attempts go to the dead-letter queue. See the event-driven
  architecture table in [`../README.md`](../README.md).
- With `CHRYSOPOEIA_EVENT_TOPIC` set, each durable lifecycle record is published
  as `consumer_outcome` v1
  ([schema](../contracts/consumer_outcome.v1.schema.json)), journal-derived and
  at-least-once with stable event IDs and journaled acknowledgements. The
  Consumer ledger stays the financial authority; the topic is an analytics copy.

## Configuration

| Variable | Default |
| --- | --- |
| `CONSUMER_JOURNAL` | — |
| `CONSUMER_BANKROLL` | 1000 |
| `CONSUMER_MAXIMUM_STAKE` | 10 |
| `CONSUMER_MAXIMUM_MARKET_EXPOSURE` | 1% |
| `CONSUMER_MAXIMUM_TOTAL_EXPOSURE` | 10% |
| `CONSUMER_MAXIMUM_LOSS` | 100 (cumulative) |
| `CONSUMER_MINIMUM_EDGE` | 5% |
| `CONSUMER_FEE_RATE` | 2% |
| `CHRYSOPOEIA_EVENT_TOPIC` | unset (no publishing) |

## Run locally

```sh
uv sync
CONSUMER_JOURNAL=/tmp/consumer/ledger.jsonl \
  uv run uvicorn paper_consumer.app:app --host 127.0.0.1 --port 8080 --workers 1
```

In another shell:

```sh
cd ../harness
CHRYSOPOEIA_EVENT_SINK=http://127.0.0.1:8080/push \
  uv run chrysopoeia cycle --journal /tmp/harness-journal --snapshot snapshot.json

# Or post an existing event from consumer/:
cd ../consumer
uv run python scripts/send_event.py event.json   # POST /push, prints HTTP status
uv run python scripts/send_event.py --sweep      # POST /sweep (exits/settlement)
cat /tmp/consumer/ledger.jsonl
```

- `event.json` is a `trade_plan_ready`
  [v1](../contracts/trade_plan_ready.v1.schema.json) (YES-only) or
  [v2](../contracts/trade_plan_ready.v2.schema.json) (YES/NO) event. In v2,
  `probability` is the selected token's win probability.
- `event_id` must be `turn-` plus the first 24 hex chars of SHA-256 over compact
  JSON `[snapshot_id, market_id]`. The script checks this and wraps the event in
  a real Pub/Sub push envelope.
- The adapter checks that `outcome` matches `instrument_id`, then buys and later
  sells that token's book. Settlement pays when the held token wins (quote
  `resolution=YES` means that token won).
- Local runs are unauthenticated; bind to `127.0.0.1` only. Public Gamma/CLOB
  reads are real; fills are paper.
- `204`: durable fill, terminal rejection, or ignored non-`trade_plan_ready`
  event. `503`: retryable ledger or outbox failure. A position with an
  unreadable quote is logged at ERROR and retried next sweep without failing
  the sweep.

## Adding a market provider

Implement the `Market` protocol in `paper_consumer/core.py`:
`load(market_id, token_id, now) -> Quote`. Normalize the venue response into
`Quote` (executable book, freshness timestamp, resolution) before any risk
check, and follow `PublicMarketTests` for bounded, strict parsing. Only
Polymarket exists; `app.py` selects it directly.
