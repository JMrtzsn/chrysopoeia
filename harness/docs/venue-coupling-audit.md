# Venue-coupling audit

Where Polymarket leaks past the adapter, with file:line evidence (at audit
time) and a change-cost tier:

- **Config-only** — a new market family inside Polymarket.
- **Adapter-only** — a second venue adapter, no contract or core change.
- **Cross-unit** — touches the event schemas, the core, or another work unit
  (needs coordinated operator approval before any fix).

## Ranked findings

### C1. `validate_polymarket_event_url` lives in the venue-neutral core (cross-unit)

- `harness/chrysopoeia/trading.py:16-39` — the Polymarket event-URL validator is
  defined in the core `trading.py`, not the adapter.
- `trading.py:217` — `MarketSnapshot.__post_init__` calls it on every rich
  snapshot, so **no other venue can construct a `MarketSnapshot` without
  editing core code**. This is the hardest coupling.
- Callers beyond the adapter: `context.py:6,34`, `context_profiles.py:13,262`.
- Fix: inject a venue-supplied validator at the snapshot/adapter boundary.
  Mechanical, but touches every snapshot path, its tests, and the
  `snapshot.source_url` semantics ("must be a polymarket.com event URL").

### C2. YES-first outcome semantics baked into the core snapshot (cross-unit)

- `trading.py:229` (snapshot identity) and the `MarketSnapshot.yes_token_id`
  field name; `polymarket.py:36-37,828` map tokens[0] → YES ("first outcome is
  the YES side").
- `contracts/trade_plan_ready.v1/v2.schema.json:17` — `outcome` enum
  `["YES","NO"]`; v2 description states "YES means Yes/Up; NO means No/Down".
- `consumer/paper_consumer/market.py:120` — `selected_outcome = "YES" if
  token_index == 0 else "NO"`, and `:138` resolves against the same first-token
  convention.
- Fix: adapter-side relabeling (cheap, lossy) or a new schema version with
  venue-neutral outcome identity (cross-unit).

### C3. Context identity is Polymarket-shaped and persisted in archived events (cross-unit)

- `harness/chrysopoeia/context.py:27-54` — routing hardwires the
  `btc-updown-5m` slug grammar, the generic crypto updown grammar, and
  `polymarket:series:*` / `polymarket:event:*` scope keys; the fallback keys any
  Polymarket slug under the `polymarket.event` profile.
- `context_profiles.py:455-461` — profile routing matches the
  `polymarket:event:` scope prefix and `polymarket.event` profile id.
- The values are durable data: `contracts/turn_outcome.v3/v4.schema.json:127-154`
  persist `context.scope_key`/`profile_id`, and the Observer groups insights by
  them. A second venue would produce `polymarket:*`-like keys or fail routing,
  and learned contexts cannot transfer across venues (per-venue namespaces are
  deferred roadmap work needing a coordinated schema tag).
- Fix: a new schema version plus Observer grouping compatibility. Deferred
  until a second venue is approved.

### C4. `market_id` pattern encodes Polymarket numeric IDs (cross-unit)

- `contracts/trade_plan_ready.v1/v2.schema.json:14` — `market_id` pattern
  `^[1-9][0-9]{0,99}$` matches Polymarket's numeric Gamma IDs specifically.
  A venue with alphanumeric market IDs cannot emit a v1/v2 plan.
- Fix: a new schema version, only once a second venue exists.

### B1. Adapter call sites are wired directly into core flows (adapter-only)

Every importer of `chrysopoeia.polymarket` outside the adapter:

- `loop.py:14,161,188` — discovery and snapshot loading in the paper loop.
- `operations.py:23-27,60,289,342,419` — capture/cycle/load plumbing, including
  `load_market_resolution` defaults in three signatures.
- `agent.py:27-31,181-200,248-249,732` — trader tools (`discover`, `load`,
  `analyze_polymarket_history` → `load_series_history`).
- `cli.py:25-26` — also imports the adapter's private `_fetch` as
  `polymarket_fetch` and passes it through every command (`:499-827`).
- `polymarket_evaluation.py:9-14,111,123` — Polymarket-specific scoring by
  definition (CLOB baseline vs Brier); acceptable permanently.

Fix: route these through a config-selected adapter object. Mechanical but
wide; the abstraction waits for a second concrete venue.

### B2. Consumer adapter (adapter-only)

- `consumer/paper_consumer/market.py:94-177` — the `Polymarket` class
  implements the venue-neutral `Market` interface; Gamma
  `closed`/`outcomePrices` resolution semantics (`:125-138`), CLOB book fetch
  and staleness (`:153-166`), `polymarket-` quote identity prefix (`:169`).
- `consumer/paper_consumer/app.py:19,122` — hardwires `Polymarket()` into the
  app; `:88` filters on `trade_plan_ready` (venue-neutral).
- Fix: implement another `Market` and select it in `app.py`.

### A1. Closed config enumerations (config-only)

- `harness/chrysopoeia/configuration.py:302-321` — `adapter != "polymarket"`
  and `markets != "esports-match-winner"` raise; the keys exist, the value sets
  are closed gates.
- `polymarket.py:362-365` — discovery enforces the same
  `esports-match-winner` family and a 1–20 limit.
- A new market family is a config/schema-of-one change (these gates plus the
  slug grammar below); a new venue is adapter-only.

### A2. Esports slug grammar and YES-first mapping inside the adapter (config-only / acceptable)

- `polymarket.py:32-33` — `ESPORTS_MATCH_SLUG` regex
  `(cs2|dota2)-<team>-<team>-YYYY-MM-DD` and `ESPORTS_QUESTION_PREFIXES`
  ("Counter-Strike: ", "Dota 2: "); enforced at `:334-351`.
- `polymarket.py:21-23,144-165` — Gamma/CLOB hosts and URL grammar.
- `polymarket.py:480-483,519-528,658-663` — `outcomePrices` ≥0.999 dominant
  resolution and YES-first mapping.
- `polymarket.py:362-406` — discovery limits, 30-day horizon, 10-minute start
  lead, volume24hr ordering, `gameStartTime` read.
- All adapter-internal by design. Acceptable.

## Verdict

- Keep as-is: the adapter, esports slug/question grammar,
  `polymarket_evaluation`, the closed config gates, and the consumer's
  `Polymarket` class. One venue, one implementation.
- Must fix before a second venue: C1–C4. Each is cross-unit and needs
  coordinated operator approval; C3 also touches Observer grouping keys.
