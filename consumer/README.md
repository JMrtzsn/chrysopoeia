# Paper consumer

This independent FastAPI service accepts authenticated Pub/Sub push requests at
`POST /push` and authenticated Scheduler requests at `POST /sweep`. Authentication
is enforced by Cloud Run IAM. The service validates the Harness-owned v1 schema,
fetches bounded public metadata/books, independently checks risk and depth, and
records paper-only outcomes in its own append-only journal.

Configuration is through `CONSUMER_JOURNAL`, `CONSUMER_BANKROLL`,
`CONSUMER_MAXIMUM_STAKE`, `CONSUMER_MAXIMUM_MARKET_EXPOSURE`,
`CONSUMER_MAXIMUM_TOTAL_EXPOSURE`, `CONSUMER_MAXIMUM_LOSS`,
`CONSUMER_MINIMUM_EDGE`, and `CONSUMER_FEE_RATE`. Defaults are paper bankroll
1000, stake 10, market 1%, total 10%, cumulative loss 100, edge 5%, and 2% paper
fees.

No model, credentials, signing, order, or live-execution code exists here.
