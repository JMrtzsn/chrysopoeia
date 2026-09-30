# Agent Graphs

## Current Harness Graph

The current graph is one explicit, bounded core workflow integrated through the
ADK runtime adapter. It does not yet loop or scan markets, manage agent
lifecycles, or recover unfinished turns.

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

This graph is a Level 1 turn inside the current Level 2 specialized harness:

| Concept | Current graph mapping | Status |
| --- | --- | --- |
| Session | Operator configuration plus ADK conversation state | In memory; not durable or recoverable |
| Turn | One requested paper cycle or operator action | Explicitly triggered and bounded |
| Step | One trader or reviewer model request/response | ADK owns each inner model loop |
| Action | Snapshot/context query or deterministic validation, policy, quote/fill, and finalization | Harness-controlled; finalization is not a model tool |
| Observation | Canonical snapshot, proposal/review record, decision, fill/no-fill, cost, and report | Recorded for current audit/evaluation, not a durable event log |

Trader and reviewer steps reason and propose. Harness actions select evidence,
validate and authorize, execute the local paper effect, and record observations;
the graph is not an unrestricted model/tool loop.

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

The reviewer provides model-based critique, not human approval or an approval
control plane. Its approval is still only input to deterministic policy.

## Current State And Cost Contract

The core state contract contains validated operating configuration, one canonical
snapshot, its evidence record, proposal/review when applicable, deterministic
decision, optional simulated fill, report, and model-cost ledger. The current ADK
adapter carries these values in in-memory session state. Snapshot and market IDs
must remain consistent across every record.

Model callbacks reserve a bounded estimated cost before each call, reject calls
outside policy, settle actual token usage, and fail closed when settlement is
invalid. Cost exhaustion skips reasoning; it never weakens trading policy.

Deterministic paper-cycle contracts, evidence, and finalization are in
`chrysopoeia/paper_cycle.py`; trading, risk, and fills are in
`chrysopoeia/trading.py`; and `chrysopoeia/agent.py` owns ADK runtime composition,
wrappers, tools, and workflow construction. ADK `Agent`, `Workflow`, callbacks,
ToolContext/session state, and Agents CLI/A2A/eval tooling remain runtime-edge
details. Cost callbacks in `chrysopoeia/cost.py` remain ADK-edge, and agent
wrappers bridge ADK Context to the core, so isolation is not complete. Do not
introduce an abstract runtime interface until a second concrete runtime is
required.

## Future Harness Graphs

The following graphs are retained as future design, not current behavior. They
require durable authoritative records, idempotent turn admission, explicit
operating approval, and contract-tested adapter/configuration choices before
implementation. Looping, cancellation, deadlines, and recovery are Level 2
operational evolution owned by this same harness. A platform may launch the
harness entrypoint but does not drive cycles. A Level 3 meta-harness exists only
when a control plane coordinates multiple independent harnesses and explicitly
divides session, context, tool, and terminal-state ownership with them.

### Bounded Autonomous Decision Graph

```text
session capital + target win rate + window + hard limits
  -> stop/deadline check -> discover and select a market
  -> capture canonical snapshot -> bounded harness decision graph
  -> mark/settle -> durable audit/recovery -> repeat or halt
  -> end-of-window achieved-versus-target win-rate and net-P&L report
```

The harness discovers and selects markets without operator ideas or picks, owns
cadence, and enforces the trading-window deadline, maximum cycles, cost budget,
loss halt, and a kill switch or stop signal. Cheap scans and cooldown/model-call
budgets gate expensive reasoning. Recovery and idempotent admission must prevent
duplicate records or fills; graph versions remain fixed for active cycles. At
the deadline it reports settled winning trades divided by settled trades against
the target; the target never weakens risk limits or makes abstention invalid.

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
