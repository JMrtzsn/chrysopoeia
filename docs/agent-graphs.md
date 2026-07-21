# Agent Graphs

ADK `Workflow` graphs own execution order and routing. A scheduler only creates
idempotent triggers; it never contains trading logic and never invokes an LLM
directly.

## Graphs

Keep three graphs separate because they run at different times and have
different failure semantics.

### DAC Boundaries

Use two independent decision-action cycles (DACs):

1. **Research DAC:** discover -> research -> propose -> paper trade -> evaluate
   agents and strategies. Evaluation may approve an immutable proposal for the
   execution DAC, but this DAC cannot perform live execution.
2. **Execution DAC:** consume only an approved execution request, revalidate its
   snapshot and expiry, apply a deterministic risk check, execute through the
   isolated boundary, reconcile the result, and run an independent post-trade
   review.

The execution DAC never researches or invents a trade. Its post-execution
review checks authorization, expected versus actual price and size, fees,
policy compliance, and reconciliation. A failed review pauses further
execution when a deterministic stop condition is met; an LLM cannot weaken a
limit or authorize a retry. Live execution remains outside the initial scope
and must retain hard limits and a kill switch.

### Decision Graph

Runs from a user command or scheduled trigger.

```text
START
  -> claim_trigger
  -> load_configuration
  -> scan_markets
  -> opportunity_gate
       no_change -> record_heartbeat -> END
       candidate -> capture_snapshot
                 -> retrieve_context
                 -> run_traders
                 -> proposal_gate
                      no_trade -> persist_no_trade -> report -> END
                      proposed -> run_reviewers
                                -> review_gate
                                     rejected -> persist_rejection -> report -> END
                                     approved -> risk_check
                                                -> risk_gate
                                                     blocked -> persist_block -> report -> END
                                                     allowed -> paper_execute
                                                              -> reconcile
                                                              -> persist_cycle
                                                              -> report
                                                              -> enqueue_learning
                                                              -> END
```

`scan_markets`, all gates, snapshotting, risk, execution, reconciliation, and
persistence are ordinary Python functions. Only `retrieve_context`,
`run_traders`, and `run_reviewers` can incur model or vector-retrieval cost.

### Lifecycle Graph

Runs daily or after a hard policy violation.

```text
START
  -> load_agent_metrics
  -> eligibility_gate
       insufficient_sample -> record_defer -> END
       eligible -> reviewer_evaluation
                -> deterministic_lifecycle_rules
                -> persist_promote_pause_retire
                -> successor_gate
                     none -> report -> END
                     needed -> propose_successor
                             -> validate_new_version
                             -> activate_paper_version
                             -> report
                             -> END
```

Reviewer evaluation supplies analysis. Deterministic lifecycle rules make the
decision from authoritative metrics and versioned thresholds.

### Learning Graph

Runs after a completed cycle or market resolution. It is asynchronous and may
be retried without blocking the decision graph.

```text
START
  -> claim_learning_trigger
  -> load_immutable_sources
  -> extraction_gate
       nothing_eligible -> END
       eligible -> extract_candidate_lessons
                -> validate_provenance
                -> consolidate_memories
                -> update_memory_bank
                -> update_rag_corpus
                -> record_learning_cycle
                -> END
```

Only resolved outcomes can create validated strategy lessons. Completed but
unresolved cycles can create observations.

## Scheduled Cost Gates

Use different cadences for cheap checks and expensive reasoning:

| Trigger | Default cadence | LLM by default |
| --- | --- | --- |
| Market scan | Every 5 minutes | No |
| Decision reasoning | At most hourly and only after `opportunity_gate` | Yes |
| Position review | Hourly when an open position changed materially | Yes |
| Lifecycle evaluation | Daily or immediately after hard violation | Sometimes |
| Memory consolidation | After completion or resolution | Yes |

The deterministic opportunity gate opens when at least one configured event is
true:

- A market enters the eligible watchlist or discovery scope.
- Best executable price moves by the configured threshold since the last
  evaluated snapshot.
- Spread, depth, or time-to-resolution crosses a configured threshold.
- New approved evidence exists since the last evaluation.
- An open position requires review.
- The maximum reasoning interval has elapsed for an eligible market.

Cooldowns and a per-day model-call budget prevent repeated reasoning over the
same unchanged market. Budget exhaustion records a skip; it never weakens risk
rules.

## State Contract

Each graph invocation carries a small typed envelope:

```text
trigger_id
trigger_type
graph_name
graph_version
cycle_id
session_id (optional for scheduled work)
market_ids
snapshot_id (after capture)
trader_version_ids
reviewer_version_ids
policy_version_id
started_at
```

Large documents, order books, transcripts, and model outputs are persisted and
passed between nodes by immutable record ID. Do not copy them through ADK
session state.

Node outputs are validated structured models. Routes are finite enums such as
`NO_CHANGE`, `CANDIDATE`, `NO_TRADE`, `PROPOSED`, `REJECTED`, `APPROVED`,
`BLOCKED`, and `ALLOWED`; an LLM never chooses arbitrary node names.

## Reliability

- `trigger_id` is unique. `claim_trigger` atomically ignores duplicates.
- Every external side effect uses an idempotency key derived from the cycle and
  node name.
- Persist node status as `pending`, `running`, `succeeded`, or `failed` with
  attempt count and timestamps.
- Retry reads, RAG retrieval, and model calls with bounded backoff.
- Do not automatically retry an execution result unless reconciliation proves
  no order or fill was created.
- Resume from persisted node output, not from reconstructed conversation text.
- A graph version is immutable for active cycles. New routing or prompts create
  a new version; old cycles finish on their original version.
- One market may have only one active decision cycle per policy version unless
  explicit parallel strategy evaluation is configured.

## Scheduling And Deployment

Locally, a small process or manual command can emit triggers. On GCP, use Cloud
Scheduler to invoke an authenticated Agent Platform or application endpoint.
The endpoint writes the trigger first and then runs the graph.

Schedules are configuration data:

- `enabled`
- cadence
- market scope
- reasoning cooldown
- daily model-call and token budgets
- graph version

`Pause all trading` disables decision triggers and prevents execution nodes from
starting. Scanning and reconciliation may continue so the system can report
state safely.

## Observability

Record per node:

- latency, retries, route, and error class
- model, prompt, input, output, and token counts where applicable
- RAG query, filters, result IDs, and retrieval scores
- estimated and actual API cost
- source and destination record IDs

Reports aggregate skips by reason so cost gates can be tuned without guessing.
