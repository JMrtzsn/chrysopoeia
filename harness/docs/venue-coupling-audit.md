# Venue-coupling audit

Read-only audit (harness roadmap Next item 1, operator-approved 2026-11-13). No
code changes. Every place the venue leaks past an adapter, with file:line
evidence and a change-cost tier:

- **Config-only** — a new market family inside Polymarket.
- **Adapter-only** — a second venue adapter, no contract or core change.
- **Cross-unit** — touches the event schemas, the core, or another work unit
  (needs coordinated operator approval before any fix).

## Ranked findings

### C1. `validate_polymarket_event_url` lives in the venue-neutral core (cross-unit)

- `harness/chrysopoeia/trading.py:16-39` — the Polymarket event-URL validator is
  defined in the core `trading.py`, not the adapter.
- `trading.py:217` — `MarketSnapshot.__post_init__` calls it on every rich
  snapshot, so **no non-Polymarket venue can construct a `MarketSnapshot`
  without editing core code**. This is the single hardest coupling: a second
  venue cannot reuse the canonical snapshot type as-is.
- Callers beyond the adapter: `context.py:6,34`, `context_profiles.py:13,262`.
- Change cost: rename/move to a venue-supplied validator injected at the
  snapshot/adapter boundary. Mechanical, but every snapshot path, its tests,
  and the schema semantics of `snapshot.source_url` (currently "must be a
  polymarket.com event URL") are affected.

### C2. YES-first outcome semantics baked into the core snapshot (cross-unit)

- `trading.py:229` (snapshot identity) and the `MarketSnapshot.yes_token_id`
  field name; `polymarket.py:36-37,828` map tokens[0] → YES ("first outcome is
  the YES side").
- `contracts/trade_plan_ready.v1/v2.schema.json:17` — `outcome` enum
  `["YES","NO"]`; v2 description states "YES means Yes/Up; NO means No/Down".
- `consumer/paper_consumer/market.py:120` — `selected_outcome = "YES" if
  token_index == 0 else "NO"`, and `:138` resolves against the same first-token
  convention.
- Change cost: a venue whose outcome labels/ordering don't match the
  YES-first convention needs either adapter-side relabeling (cheap, lossy) or
  a new schema version with venue-neutral outcome identity (cross-unit).

### C3. Context identity is Polymarket-shaped and persisted in archived events (cross-unit)

- `harness/chrysopoeia/context.py:27-54` — routing hardwires the
  `btc-updown-5m` slug grammar, the generic crypto updown grammar, and
  `polymarket:series:*` / `polymarket:event:*` scope keys; the fallback keys any
  Polymarket slug under the `polymarket.event` profile.
- `context_profiles.py:455-461` — profile routing matches the
  `polymarket:event:` scope prefix and `polymarket.event` profile id.
- The values are durable data: `contracts/turn_outcome.v3/v4.schema.json:127-154`
  persist `context.scope_key`/`profile_id`, and the Observer groups insights by
  them (`observer` v1 aggregates are profile-scoped). A second venue would
  produce `polymarket:*`-like keys or fail routing; learned contexts cannot
  transfer across venues today (per-venue namespaces — already recorded as
  deferred roadmap work requiring a coordinated schema tag).
- Change cost: any namespace change is a new schema version plus Observer-side
  grouping compatibility. Deferred until a second venue is approved.

### C4. `market_id` pattern encodes Polymarket numeric IDs (cross-unit)

- `contracts/trade_plan_ready.v1/v2.schema.json:14` — `market_id` pattern
  `^[1-9][0-9]{0,99}$` matches Polymarket's numeric Gamma IDs specifically.
  A venue with alphanumeric market IDs cannot emit a v1/v2 plan.
- Change cost: new schema version only when a second venue exists.

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

Change cost: a second venue means these call sites go through a config-selected
adapter object instead of direct imports. Mechanical but wide; per the design
rules, the abstraction waits for the second concrete use case.

### B2. Consumer adapter (adapter-only)

- `consumer/paper_consumer/market.py:94-177` — the `Polymarket` class
  implements the venue-neutral `Market` interface; Gamma
  `closed`/`outcomePrices` resolution semantics (`:125-138`), CLOB book fetch
  and staleness (`:153-166`), `polymarket-` quote identity prefix (`:169`).
- `consumer/paper_consumer/app.py:19,122` — hardwires `Polymarket()` into the
  app; `:88` filters on `trade_plan_ready` (venue-neutral).
- Change cost: implement another `Market` and select it in `app.py`.
  Acceptable.

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

## Acceptable to keep as-is

The adapter itself, the esports slug/question grammar, `polymarket_evaluation`
(CLOB baseline scoring), the closed config gates, and the consumer's
`Polymarket` class. One venue, one implementation, no speculative abstraction.

## Not acceptable to keep if a second venue is approved

C1 (core URL validation inside `MarketSnapshot`), C2 (YES-first outcome
semantics in core + contract), C3 (context namespace in archived events), C4
(`market_id` pattern in `trade_plan_ready`). Each is cross-unit and needs
coordinated operator approval before any fix; C3 additionally touches the
Observer's grouping keys.
