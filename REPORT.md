# Engineering Report - Assignment 1

## 1. Architecture

IncidentZero is a small, framework-free runtime built around a strict boundary between proposal and execution. The Groq client and scripted client implement the model interface. The model can interpret observations, write a plan, and propose one local tool call. It never directly changes the simulator. The `AgentController` owns the operational state machine and is the authority for validation, approval, evidence requirements, budgets, retries, loop detection, and terminal status.

The simulator is accessed only through `ToolRegistry`. Registry validation uses the tool definitions and JSON Schema, so unknown tools, missing fields, wrong types, extra fields, and invalid enum values are rejected before reaching the environment. Every accepted observation or action returns a status, world version, evidence ID, and optional data. `AgentState` preserves this information independently from the chat message list. It records the current plan and revision, evidence IDs, recent results, world version, approval denials, stale events, verification evidence, and budget usage.

The planner validates a structured plan with at least two steps. Its fallback plan is deliberately conservative: gather evidence, choose an evidence-supported action, and verify before closure or escalation. Revisions preserve existing steps and evidence while changing the hypothesis and final verification strategy. This makes a re-plan different from simply asking the model the same question again.

The trace recorder writes JSONL events for bootstrap evidence, plans, model replies, tool results, approvals, and loop detection. The trace contains operational model output and evidence IDs, but not secrets or hidden reasoning. The simulator remains authoritative about whether a change worked.

## 2. Planning and re-planning strategy

The controller starts by obtaining the incident through the registry. The ticket's suspected service is treated as a lead, not as a diagnosis. A structured model call creates a plan, and invalid or unavailable structured output falls back to a validated deterministic plan. No remediation action should be selected before this plan exists.

The normal loop is observe, propose, validate, approve where required, execute, record, and decide whether to continue. The re-plan policy reacts to stale preconditions, approval denial, validation errors, non-retryable failures, explicit re-plan results, and successful actions followed by failed recovery verification. Re-planning increments the revision and includes the trigger plus a compact state summary. Existing evidence is retained, so the next hypothesis can account for what has already been ruled out.

The loop guard canonicalizes tool arguments with sorted JSON keys and counts identical action fingerprints. The third identical proposal is blocked when the configured limit is two allowed repeats. A changed world version resets the guard's interpretation because new evidence may justify reconsideration. The controller never changes an expected world version silently after a stale result; it requires new observation and plan reconsideration.

## 3. Failure handling

Transient model failures are retried at most three times with capped exponential backoff. Each attempt consumes LLM budget. Permanent model errors are not retried. A malformed or invented tool proposal is rejected at the controller boundary and cannot reach the simulator. The scripted model and injected sleeper make these behaviors testable without network access or Groq quota.

Telemetry failures are returned as tool results and can trigger a re-plan. A stale world version is recorded as a stale event and causes the controller to use the latest observation before another consequential action. Approval denial is terminal for that proposal: the action is not executed, the denial is recorded, and the controller must choose another path or escalate.

The new external-case tests cover three deterministic simulator cases using an adaptive local model. The model reads the observed incident to choose the service, gathers health and logs, runs `verify_recovery`, and cites the evidence IDs returned by those calls when it proposes escalation. The test does not inspect the simulator's private scenario fields or assume a successful remediation. It asserts that the final status is escalated and that no restart, scale, clear-cache, or rollback action was proposed. A separate test proves that an invented evidence ID is rejected before execution. This is important because repeatedly restarting an internal service cannot repair a dependency outside the managed platform.

## 4. Safety and stopping

Risk is read dynamically from `configs/risk_policy.json`. High and critical tools go through the Python approval gateway before execution. Approval cannot be manufactured by model text. The controller also checks that close cites a successful verification evidence ID. A model claiming that an incident is resolved is not a terminal event.

A resolved run requires objective recovery criteria, a current verification evidence ID, the latest world version, and a successful close result. An impossible or unsafe incident instead ends with `escalate_incident` and observed evidence. The new escalation guard rejects an empty evidence list or IDs that the controller has not observed. This keeps escalation evidence-backed even when the model is uncertain about the root cause.

## 5. Evaluation

I generated and ran all three scenarios with student ID `25I-7654` using the Groq-backed CLI and the repository virtual environment. The JSONL traces are `traces/25I-7654_public-a.jsonl`, `traces/25I-7654_public-b.jsonl`, and `traces/25I-7654_public-c.jsonl`. Counts below include the bootstrap `get_incident` tool call. The elapsed times are calculated from trace timestamps and include provider latency.

| Scenario | Outcome | LLM calls | Tool calls | Elapsed time | Actions | Re-planning | Recovery proof |
|---|---|---:|---:|---:|---|---:|---|
| public-a | `budget_exhausted` | 14 | 14 | ~172 s | restart once; scale twice | 0 | none before budget limit |
| public-b | `resolved` | 10 | 10 | ~122 s | scale once after stale retry | 1 | verify `EV-0009`; close `EV-0010` |
| public-c | `aborted` | 7 | 6 | ~75 s | scale once | 0 | none; malformed provider call |

Public-a investigated `order-service`, then observed the dependent checkout path. It performed a restart and two scale actions, but the run consumed the configured 14-request and 28-tool budgets before reaching verification or a terminal action. This is a safe budget outcome, although the trace shows that the live model spent too many calls on remediation without closing the loop.

Public-b is the strongest successful run. The agent first proposed scaling with an old world version, received `stale_precondition`, revised its plan, re-observed service health, then executed the scale with the current version. `verify_recovery` returned successful evidence `EV-0009`, and `close_incident` succeeded using that evidence, producing the resolved outcome.

Public-c shows provider-failure handling. After observations and a scale action, Groq returned an invalid JSON tool call for `verify_recovery`. The controller did not execute malformed content or claim success; it terminated as `aborted` and recorded the provider error in the trace.

The three runs used no High/Critical action, so no interactive approval was required. Offline validation was also completed in `.venv`: 12 student behavior tests and 4 infrastructure tests passed, and the custom external escalation tests passed all 4 cases.

## 6. Three failure traces

The first failure trace is public-a. The model gathered useful evidence and attempted local mitigation, but it continued to spend calls on restart and scaling. Since no objective verification was reached before the hard budget, the controller returned `budget_exhausted` instead of incorrectly marking the incident resolved. This demonstrates bounded execution, while also identifying an efficiency improvement: the controller should reserve calls for verification and escalation when the budget becomes low.

The second failure trace is public-b's stale-world event. The scale proposal used an outdated concurrency version and the registry rejected it with `stale_precondition`. The controller recorded the event, revised the plan, and obtained fresh health evidence before allowing the scale to execute. The action was not blindly retried by changing only the version. The subsequent verification and close prove that adaptation can lead to a valid resolved outcome.

The third failure trace is public-c's malformed Groq response. The provider generated `verify_recovery` with invalid JSON arguments. The client surfaced this as a permanent request error, and the controller safely aborted. No malformed call reached the simulator, and no final model text was accepted as proof of recovery. This is distinct from a transient retryable failure: retrying an invalid provider payload indefinitely would violate the bounded-runtime requirement.

The offline external-case tests add another important failure class. Their adaptive local model observes health and logs, verifies recovery, and escalates when the cause is outside the managed platform. The controller rejects escalation with an invented evidence ID and prevents repeated internal remediation. These tests cover a safe terminal path that cannot be demonstrated by a success-only script.

## 7. Limitations

The live results show that the controller's safety boundaries work, but model call efficiency still matters. Public-a exhausted its budget and public-c was dependent on malformed provider output. The runtime therefore guarantees bounded behavior more strongly than it guarantees a successful outcome for every model trajectory. A future improvement would add an explicit low-budget guard that prioritizes `verify_recovery` or evidence-backed escalation before another medium-risk action.

The controller relies on the model to choose useful observations and remediation proposals. Python validates schemas, evidence, approval, concurrency, budgets, retries, and terminal conditions, but it cannot diagnose an incident from insufficient evidence. The fallback planner is conservative and explainable, though less capable than a domain-specific runbook.

The simulator's evidence is compact and deterministic. A production system would need durable incident history, richer causal correlation, authenticated operator identity, and stronger audit controls. The local trace records operational model/tool data and evidence IDs, but intentionally does not record hidden chain-of-thought or secrets.

Finally, mitigation is not the same as root-cause repair. Restarting or scaling may improve symptoms temporarily. The controller therefore verifies objective recovery before closure and escalates when recovery is not demonstrated or the cause is external. Public-b shows the complete verify-and-close path; public-a and public-c show why bounded escalation or abort behavior is necessary when that path cannot be proven.
