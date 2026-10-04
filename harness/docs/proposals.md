# Harness Proposals

These are options for later milestones, not approved work. Refine and implement
one proposal at a time; `../../.agents-cli-spec.md` and `../ROADMAP.md` remain
the scope and ordering sources of truth.

## Research tools

Give the trader bounded, read-only research tools for markets available through
configured venues. Candidate capabilities: web search, financial/economic data,
company records, and category-specific sources when needed. Search, FRED,
CoinGecko, and SEC EDGAR are candidate providers, not locked dependencies.

Normalize and validate results with provenance before the trader/reviewer can
cite them. Decide provider scope, whether the evidence includes source metadata
only or bounded observations too, and per-cycle call/cost limits before building.
Each shipped provider needs offline contract tests and a bounded live check.

## Binary outcome sides

Allow a proposal to select either outcome of a binary market. Keep the output
about canonical outcomes, not venue tokens; let each adapter map the outcome to
its venue representation. Apply the same citation, review, risk, fee, depth,
exposure, and settlement controls to either side. Polymarket is the first
adapter, not the domain model.

## Trade intent and terms

For the first working version, target public binary prediction markets through
the existing Polymarket adapter. Proposals should select a canonical outcome
and state its estimated probability, stake, acceptable entry price, supported
timing terms, and citations. The adapter maps the outcome to a venue instrument;
the harness validates terms and records actual fill price and time. Don't expose
venue token IDs or order semantics the paper executor cannot honor.

Decide whether entry intent also carries exit conditions and which are advisory
thesis versus enforceable harness limits. Validate price bounds against
executable prices at fill. Use a second venue to test portability before
generalizing beyond binary prediction markets.

## Position management

Support reviewed close and partial-reduction decisions against a fresh snapshot.
The trader proposes; the reviewer approves or rejects; deterministic policy
quotes the exit, calculates realized P&L, and updates the journal. Resolution
remains the terminal path for positions held to resolution.

Define retained entry terms, close triggers, and remaining cost basis for partial
closes. Hard exit limits belong to deterministic harness policy. Acceptance
needs replayable accounting tests and bounded public-price verification with
paper accounting only.
