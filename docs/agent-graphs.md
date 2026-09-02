# Agent Graphs

## Current Harness Graph

The current graph is one explicit, bounded core workflow integrated through the
ADK runtime adapter. It does not schedule itself, scan markets, manage agent
lifecycles, or persist durable records.

```text
START (operator already configured and captured one market)
  -> prepare canonical snapshot evidence
  -> trader
       abstain -> record no-fill decision -> report -> evaluate -> END
       trade -> validate proposal identity/citations
             -> reviewer
             -> validate review identity/citations
             -> deterministic risk and depth/fee quote
                  blocked -> record reason -> report -> evaluate -> END
                  allowed -> local paper fill -> report -> evaluate -> END
```

Configuration and capture precede the workflow in the root coordinator:

```text
configuration -> Polymarket market-data adapter -> canonical snapshot
              -> current harness graph
```

The workflow processes one binary market. The trader and reviewer are
single-turn, role-isolated LLM agents. Abstention terminates before reviewer
invocation. Paper execution consumes the captured YES ask depth, computes VWAP
and the explicit paper fee assumption, and rejects insufficient depth without a
partial fill.

## Ownership

| Concern | Owner |
| --- | --- |
| Model reasoning, proposal/abstention | Trader LLM through the configured agent-runtime adapter |
| Independent proposal critique | Reviewer LLM through the configured agent-runtime adapter |
| Configuration and input validation | Deterministic Python |
| Snapshot/evidence identity and citation resolution | Deterministic Python |
| Canonical workflow transitions | Runtime-neutral deterministic contracts |
| Risk, exposure, quote, fee, fill, and cost gates | Deterministic Python |
| Terminal report and evaluation assertions | Deterministic Python |

LLM output is validated structured data. An LLM cannot choose arbitrary nodes,
grant permissions, weaken limits, or invoke paper execution directly. Search
results are unverified context and cannot become citations until deterministic
normalization adds them to the evidence set.

## Current State And Cost Contract

The core state contract contains validated operating configuration, one canonical
snapshot, its evidence record, proposal/review when applicable, deterministic
decision, optional simulated fill, report, and model-cost ledger. The current ADK
adapter carries these values in in-memory session state. Snapshot and market IDs
must remain consistent across every record.

Model callbacks reserve a bounded estimated cost before each call, reject calls
outside policy, settle actual token usage, and fail closed when settlement is
invalid. Cost exhaustion skips reasoning; it never weakens trading policy.

ADK `Agent`, `Workflow`, callbacks, ToolContext/session state, and Agents
CLI/A2A/eval tooling are current runtime-edge details. The Python layout still
mixes some deterministic orchestration/domain behavior into `agent.py`; moving
that behavior to runtime-neutral functions is the next internal-boundary
refactor. Do not introduce an abstract runtime interface until a second concrete
runtime is required.

## Future Platform Graphs

The following graphs are retained as future design, not current behavior. They
require durable authoritative records, idempotent triggers, explicit operating
approval, and contract-tested adapter/configuration choices before implementation.

### Scheduled Decision Graph

```text
idempotent trigger -> deterministic scan/opportunity gate
  -> capture canonical snapshot -> bounded harness decision graph
  -> durable audit/reconciliation
```

A scheduler may emit triggers but must contain no trading logic or invoke an LLM
directly. Cheap scans and cooldown/model-call budgets gate expensive reasoning.
Duplicate triggers must not duplicate records or fills; graph versions remain
fixed for active cycles.

### Lifecycle Graph

```text
load authoritative metrics -> minimum-sample eligibility
  -> optional reviewer analysis -> deterministic promote/pause/retire decision
  -> optional validated successor version
```

Lifecycle automation requires durable versioned metrics and thresholds.
Reviewer analysis may explain but never make or override the state transition.

### Learning Graph

```text
completed/resolved records -> extract candidate lesson
  -> validate provenance and resolution -> consolidate/invalidate
  -> optional RAG/Memory publication
```

Learning runs outside the trading path. Only resolved outcomes may produce
validated strategy lessons; unresolved cycles may produce observations. Memory
cannot alter authoritative records, policy, or lifecycle state.

### Authenticated Execution Graph

```text
approved immutable request -> freshness/authorization/risk recheck
  -> explicit confirmation -> isolated authenticated execution adapter
  -> reconcile -> independent review -> deterministic stop handling
```

This graph is not implemented. It must never research or invent a trade and must
have least-privilege IAM, hard limits, a kill switch, idempotency, and safe
reconciliation before retry. A market-data adapter cannot activate it.

## Future Reliability And Observability

When durable graphs exist, record unique trigger/cycle IDs, graph and policy
versions, node status/attempts, immutable input/output references, routes,
latency, bounded retries, model/token cost, and source provenance. Resume from
persisted node output rather than reconstructed conversation text. Do not retry
an execution result unless reconciliation proves no order or fill occurred.
