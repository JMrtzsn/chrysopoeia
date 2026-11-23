# Harness proposals

Only the live-trading direction is approved, and only as design scope, not
permission to submit orders. Everything else here is unapproved.
[`../../.agents-cli-spec.md`](../../.agents-cli-spec.md) and
[`../ROADMAP.md`](../ROADMAP.md) are the sources of truth for scope and order.
Implemented behavior is described in [architecture](architecture.md).

## Approved live-trading direction

- Polymarket first, binary YES-only, a dedicated operator-owned EOA holding at
  most $10 of trading collateral, and the official Python SDK behind an isolated
  adapter.
- The harness still only produces a reviewed, immutable `trade_plan_ready`.
  Independent execution consumers own orders, position monitoring, venue
  reconciliation, and their own ledgers.
- Orders run automatically after deterministic guards and explicit live-mode
  opt-ins; there is no per-order approval. Consumers fail closed when geoblock
  checks are blocked or unavailable and never bypass venue restrictions.
- Prerequisites: bounded hard limits, an idempotent event handoff, startup
  reconciliation, safe retries, and a kill switch. Exit monitoring and
  protection guarantees wait on verified venue/SDK semantics. Position size is
  the hard loss bound.
- Each bounded live verification needs separate operator approval.

## Additional research providers

Candidates: financial/economic data, company records, and category-specific
sources, such as FRED, CoinGecko, and SEC EDGAR (not locked dependencies). Each
provider must normalize and validate results with provenance and needs offline
contract tests plus a bounded live check.

## Trader-requested context profiles

When no profile fits a market, the trader could request one. A context builder
would draft a versioned manifest from existing approved tools only (no code,
new tools, policy, or execution authority), and a separate reviewer plus
deterministic validation would gate it; invalid or rejected profiles fail
closed. Acceptance must prove routing, isolation of tools and history between
market keys, rejection of unregistered tools, safe handling of unknown markets,
and unchanged global risk/accounting. Expanding automation beyond CS2/Dota 2
match winners is a separate approval.

## Second venue

Test portability with a second venue before generalizing beyond binary
prediction markets. Adapters map canonical outcomes to venue instruments. See
the [venue-coupling audit](venue-coupling-audit.md) for what must change first.

## Position management

- Partial reductions and model-proposed changes to an existing exit plan;
  brackets are currently immutable after entry and exits are full closes.
- Partial paper closes need retained entry terms and remaining cost basis; hard
  exit limits stay in deterministic policy.
- Live consumers additionally need venue reconciliation tests and bounded
  verification of the execution boundary.
