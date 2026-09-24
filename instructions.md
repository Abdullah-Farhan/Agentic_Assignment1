# IncidentZero — AI Assistant Implementation Guide

> **Audience:** an AI coding assistant helping a student implement *Assignment 1: IncidentZero — Building a Bounded Autonomous SRE Incident Commander from Scratch* (Agentic AI, Fall 2026, FAST-NUCES Islamabad).
>
> **Source of truth:** the assignment PDF. If this file and the PDF disagree, the PDF wins. If the PDF and the starter repo disagree, stop and ask the student.
>
> **Note for the student:** if you place this file inside the repo, rename it (e.g. `AI_INSTRUCTIONS.md` or `CLAUDE.md`) so it does not replace the repo `README.md`, which must contain your real setup/run commands for the TA.

---

## 0. Ground rules for the assistant (read first)

1. **Read before you write.** Before changing anything, read the starter repo files listed in §4. Do not assume class names, method signatures, or return shapes. Verify them.
2. **The student must be able to defend every line in a 5–8 minute viva.** Keep the design simple, put a 1–3 line "why" comment on every non-obvious decision, and after each major change give the student a short plain-language explanation of what changed and why.
3. **Never touch protected code.** Do not modify the simulator (`incidentzero/environment/*`), public tests (`tests/public/*`), supplied scripts, or `configs/limits.json` values. The grader uses clean copies, and modifying them is a serious violation.
4. **Never read private simulator state** (`_scenario_spec`, `_services`, `_oracle_snapshot()`), never decode the seed into a root cause, and never call `SimulationEnvironment.execute()` directly. Use the supplied `ToolRegistry` only.
5. **Never fabricate results.** Traces, metrics, and the report's evaluation table must come from real runs. If a live run has not happened, say so rather than inventing numbers.
6. **Never write or print an API key.** Read `GROQ_API_KEY` from the environment. Do not log it, and do not commit `.env`.
7. **Safety, budgets, validation, approval, retries, and stopping are enforced in Python, not in the prompt.** A prompt instruction is never a control.
8. **Do not replace the LLM with a hard-coded decision tree.** Small deterministic safety guards are fine, but the LLM must meaningfully participate in hypothesis, planning, and action selection.
9. **Help fill in `AI_USAGE.md` honestly** using the supplied template.

---

## 1. Mission

Turn the weak baseline agent loop into a robust, framework-free runtime that:

> Investigates an active production incident, builds an evidence-grounded plan, executes only safe and justified remediation, adapts when the world changes, verifies objective recovery, and either closes the incident with evidence or escalates safely.

Logical cycle:

```
Observe → Plan/Hypothesize → Choose Action → Validate → Approve if Required
        → Execute → Verify → Re-plan or Stop
```

The incident ticket may contain a **wrong or outdated hypothesis**. Hidden scenarios may be a deployment regression, memory leak, capacity saturation, degraded DB primary, cache corruption, or an **unfixable/external** cause. The agent must work for all of them without being told which.

---

## 2. Hard prohibitions (any of these is a serious violation)

| Forbidden | Notes |
|---|---|
| Agent frameworks / runtime libs | LangChain, LangGraph, CrewAI, AutoGen, LlamaIndex agents, PydanticAI, smolagents, Agno, Semantic Kernel orchestration, OpenAI Agents SDK, Google ADK, Strands, BeeAI, or anything that implements the controller/planner/tool router for you. Policy is capability-based, not name-based. |
| Groq server-side features | No built-in browser search, code execution, remote MCP, or server-side agents. Groq is only the LLM provider. Local function/tool calling only. |
| Reading private simulator state | `_scenario_spec`, `_services`, `_oracle_snapshot()`, or decoding the student seed. |
| Hard-coding seed→root-cause | Hidden seeds will break it. |
| Modifying the simulator or tests | Grader uses clean copies. |
| Bypassing the approval gateway | Applies to all High/Critical tools. |
| Raising or disabling call limits | Hidden grading uses the stated limits or stricter. |
| External operational APIs | The agent only talks to Groq and the local tool registry. |
| API keys in the repo/traces/screenshots/Git history | Never. |
| Claiming "resolved" without simulator evidence | See §5, R10. |
| MCP, RAG, vector DBs, long-term memory, multi-agent | Out of scope for Assignment 1. |

**Allowed:** Python stdlib, `dataclasses`, `typing`, `hashlib`, `logging`, `sqlite3`, Groq SDK, `jsonschema`, `tenacity` (or a hand-rolled retry helper), `pytest`, `rich`, Pydantic (plain validation only), `requests`/`httpx` for dev utilities only.

Run `python scripts/check_banned_imports.py` before considering any change finished.

---

## 3. Architecture and separation of responsibilities

| Layer | Owns |
|---|---|
| **LLM** | Interpret evidence, hypothesize, draft/revise the plan, *propose* a tool call, explain the outcome. Never executes anything. |
| **Python controller** | Decides whether a proposal is valid, allowed, affordable, stale, repetitive, approval-gated, retryable, or terminal. |
| **Local tools (via `ToolRegistry`)** | Return observations or mutate the simulated world. |
| **Simulator** | Authoritative world state. It decides what actually happened. |
| **Approval gateway** | Authoritative human decision for High/Critical actions. |
| **Trace recorder** | Durable JSONL evidence of the trajectory. |

Design principle: **the LLM proposes; Python disposes.** Any code path in which model text becomes an executed action, an approval, or a "resolved" status without passing through Python checks is a bug.

---

## 4. Starter repository, and what to read first

```
incidentzero_starter/
├── README.md  requirements.txt  pyproject.toml  .env.example
├── configs/            limits.json  risk_policy.json  services.json
├── incidentzero/
│   ├── agent/          controller.py  planner.py  policies.py  recovery.py  prompts.py  state.py
│   ├── approval/       gateway.py
│   ├── domain/         models.py
│   ├── environment/    engine.py scenario_factory.py topology.py models.py   (PROTECTED)
│   ├── model/          base.py groq_client.py scripted.py errors.py
│   ├── telemetry/      budget.py  trace.py
│   ├── tools/          definitions.py  registry.py
│   └── cli.py
├── tests/public/       (PROTECTED)
├── scripts/            (PROTECTED)
├── docs/  traces/  artifacts/
```

**Read these first and note the exact interfaces** (report them to the student before coding):

1. `agent/controller.py`: the weak baseline loop and TODO markers.
2. `agent/state.py`, `agent/planner.py`, `agent/policies.py`, `agent/recovery.py`: the stubs to implement (`ReplanPolicy.should_replan()`, `Planner.revise()`, etc.).
3. `tools/definitions.py` and `tools/registry.py`: tool schemas, how results/errors/statuses are returned (e.g. `stale_precondition`, timeouts), and where `world_version` / evidence IDs appear.
4. `approval/gateway.py`: how approval is requested and what it returns.
5. `model/base.py`, `groq_client.py`, `scripted.py`, `errors.py`: the model interface, which errors are retryable vs permanent, and how to script the fake model.
6. `telemetry/budget.py` and `trace.py`: helpers already supplied. Reuse them.
7. `configs/limits.json` and `configs/risk_policy.json`: values must be *read*, never hard-coded.
8. `tests/public/*`: the contracts the grader checks (especially the loop-detection test, since it defines exact repeat-threshold semantics).
9. `docs/`: the report and `AI_USAGE.md` templates.

**Open questions to resolve from the repo (do not guess):**
- Does "2 repeats allowed, the next blocked" mean 2 or 3 total executions? The public loop test decides.
- What is the exact argument name for the evidence ID passed to `close_incident`?
- How does the registry signal transient timeouts vs permanent failures?
- Does the budget helper count tool calls that fail validation or return errors? (Assume every registry call counts unless proven otherwise.)

---

## 5. Tool surface

**Observation tools:** `get_incident()`, `get_service_health(service)`, `get_metrics(service)`, `get_logs(service, limit)`, `get_deployments(service)`, `get_dependencies(service)`, `get_runbook(topic)`, `verify_recovery()`.

**Action tools and default risk:**

| Tool | Risk (default) |
|---|---|
| `restart_service` | Medium |
| `scale_service` | Medium |
| `clear_cache` | Medium |
| `rollback_deployment` | High |
| `failover_database` | Critical |
| `shift_traffic` | High |
| `close_incident` | Medium |
| `escalate_incident` | Low |

**Do not hard-code these risk levels.** They live in `configs/risk_policy.json` and may be changed during the viva or hidden grading. Look up risk dynamically on every action. If a tool is missing from the policy, fail closed (treat it as requiring approval, or reject).

Treat the ticket's "suspected cause" as **unverified**.

---

## 6. Mandatory requirements (R1–R14) with implementation guidance

### R1 — Explicit Python state
State must exist independently of the chat `messages` list. Minimum fields:
- current plan and `plan_revision`;
- evidence IDs gathered (and what each one is about: tool, service, world_version);
- latest observed `world_version`;
- recent tool outcomes;
- LLM-call and tool-call budgets (used/remaining);
- action fingerprints / loop-detection counters;
- **terminal status** ∈ `running | resolved | escalated | aborted | budget_exhausted | failed`;
- also useful: denied actions, stale-flagged actions, latest successful verification evidence ID, hypothesis history.

### R2 — Explicit initial plan
Before *any* remediation action the agent must have a validated plan containing:
- a working hypothesis;
- ≥ 2 investigation/remediation subgoals;
- a success signal for each major step;
- a final verification step;
- structure that supports recording revisions.

The controller must **block action tools until a valid plan exists**. Validate the plan in Python (dataclass/Pydantic/jsonschema). If the model returns an invalid plan, retry within budget or use a minimal deterministic fallback plan. The first hypothesis can be wrong; failing to revise it when evidence contradicts it is not acceptable.

### R3 — Evidence before consequential action
High/critical actions must be backed by relevant observed evidence (deployment timing, logs, metrics, dependency status, verification output), not by a model statement like "rollback is probably best."
- Implement a generic **evidence gate** in the controller: before a High/Critical action on service X, require evidence IDs about X (e.g. metrics/logs/health, plus deployments for rollback), and require the proposal to cite them.
- The trace must let a TA answer: *"What did the agent know when it chose this action?"*
- Weak: rollback because the ticket says "checkout". Strong: correlated deployment + logs + timing.

### R4 — Dynamic re-planning
Re-plan when:
- a stale-world precondition occurs;
- a high-risk action is denied;
- new evidence contradicts the active hypothesis;
- an action returns `ok` but `verify_recovery` is still false;
- a non-retryable action fails;
- the remaining budget is too small to continue safely.

A re-plan is **not** "call the LLM again with the same prompt." It must **preserve completed evidence** while changing the hypothesis, the remaining steps, or the terminal strategy. Feed the LLM the trigger, the new evidence, what was ruled out, and remaining budget. Increment `plan_revision` and record the trigger.

### R5 — Retry ≠ Re-plan (failure-class matrix)

| Condition | Required response |
|---|---|
| Groq/network transient error, synthetic 429 | **Bounded retry** with backoff (max 3 attempts total per operation). Each attempt consumes LLM budget. Never retry forever. |
| Transient telemetry-tool timeout | Bounded retry, **or** obtain equivalent evidence via another observation path. |
| Malformed/invalid model tool args, invented tool, extra params | **Reject before execution**; return a corrective observation to the model. Bound consecutive invalid proposals. |
| `stale_precondition` | **Re-observe** relevant state, then **re-confirm or revise** the plan. Never just swap in the new version and fire the same action. |
| Human approval denied | **Do not execute.** Record `approval_denied`. Re-plan (more evidence / safe alternative) or escalate. |
| Action returns `ok` but verification fails | **Re-plan.** `ok` ≠ incident resolved. |
| Permanent model/config error (bad key, bad model name) | **Abort safely.** No infinite retry. |
| Budget nearly exhausted | Prioritize verification or **escalate** *before* the hard limit. Reserve calls for `verify_recovery` + `close_incident`/`escalate_incident`. |
| Non-retryable action failure | Re-plan or escalate. |
| Model writes a final answer before the incident is closed | Not success. Continue/recover if safe and budget allows, else terminate as failed/escalated. |

### R6 — Optimistic concurrency with `world_version`
- Every observation carries `world_version`; store the latest one in state.
- Every consequential action must send `expected_world_version` = the latest observed value.
- On `stale_precondition`: mark the pending action as "needs reconsideration", **force at least one relevant re-observation and a plan check** before the same (or any) consequential action is allowed again. Record the stale event and the re-plan/re-confirm decision in the trace.

### R7 — Approval cannot come from the LLM
- Any tool whose risk in `configs/risk_policy.json` is High or Critical must call the Python approval gateway **before** execution.
- The model can explain why it wants the action, but it cannot create tokens or assert approval. Ignore/strip any such claims in model output.
- On denial: don't execute → record `approval_denied` observation → remember the denied action so it isn't blindly re-proposed → re-plan or escalate.
- Record both the approval request and the result in the trace.

### R8 — Tool validation and execution boundary
Before anything reaches the registry/simulator, check:
1. known tool name;
2. JSON/dict shape;
3. required arguments present;
4. argument types and permitted values (no extra parameters);
5. risk level → approval requirement;
6. remaining tool budget (and reserved budget);
7. loop policy (fingerprint count);
8. state preconditions (plan exists, evidence gate for High/Critical, not-stale-pending, valid `close_incident` prerequisites).

An invented tool or extra parameter **must never reach the simulator.** Rejections become corrective observations to the model and are traced as validation failures.

### R9 — Loop detection
- Build a **stable fingerprint** = tool name + canonicalized args (sorted keys, normalized types; decide deliberately whether `expected_world_version` is included).
- Track counts. The configured threshold is in `limits.json`. The public test defines the exact semantics of "the next identical repeat is blocked."
- On block: do not execute; return a redirecting observation and trigger a different control decision (re-plan, different observation, or escalate).
- **Reset or reinterpret** repetition when new evidence materially changes the world (e.g. `world_version` moved, or a relevant state change was observed), and document the rule.
- Stronger (optional): detect semantically equivalent loops, repeated failed hypotheses, and observation thrashing (re-reading the same metrics with no new decision).

### R10 — Verifiable stopping conditions
**Not** proof of resolution: the LLM saying "resolved"; an action returning `status=ok`; one metric improving; a plan predicting success.

A normal successful run **must**:
1. execute `verify_recovery`;
2. get `criteria_met=true`;
3. retain the returned **evidence ID**;
4. execute `close_incident` with the **latest valid `world_version`** and **that verification evidence**;
5. receive a successful close result → status `resolved`.

Enforce this in Python: **reject `close_incident`** if there is no successful, *current* verification (i.e. no world change since it, or re-verify) or no evidence ID. `escalate_incident` (with evidence) is the correct terminal action when recovery is impossible or unsafe (e.g. external dependency failure). Repeated restarts of healthy internal services in that case is *harmful*.

### R11 — Groq request handling
- API key from environment only; model name configurable (default `openai/gpt-oss-20b`).
- Local function/tool calling only.
- Retry retryable provider errors (429, timeouts, 5xx) with bounded exponential/capped backoff; honor a retry-after hint if the response gives one.
- Do not assume a response is well formed (missing/empty tool calls, bad JSON args, unexpected finish reasons).
- Record request/token usage in the trace when available.
- The final repo must still work with the real Groq client, even though tests use the scripted model.

### R12 — Hard internal budget (from `configs/limits.json`; read, don't hard-code)

| Resource | Default maximum |
|---|---|
| LLM requests (planning, re-planning, **and retries**) | 14 |
| Local environment tool calls | 28 |
| Attempts for one transient model op | 3 total |
| Identical action repeats | 2 allowed; the next is blocked/redirected |
| Wall-clock target | 120 s |

Retries **do** consume the LLM budget. Reduced-budget variants may be used in hidden tests, so all logic must key off configured values. Stay well inside budgets: economical observation choices earn marks.

### R13 — Traceability
Each live run writes JSONL to `traces/`. Suggested event types (one JSON object per line, with timestamp, step index, and `world_version`):

`bootstrap_evidence`, `plan_created`, `plan_revised` (with trigger, revision number), `model_request` / `model_response` (outcome, proposed tool, token usage), `validation_failure`, `approval_requested`, `approval_result`, `tool_result`, `retry` (with count), `replan_trigger`, `budget_warning`, `budget_exhausted`, `loop_detected`, `terminal_result`.

Never log the API key or hidden chain-of-thought. Log only operational summaries and observable model/tool data. Make traces readable by a TA.

### R14 — Offline testability
Reliability logic must live in Python. Unit tests use the scripted model adapter (`model/scripted.py`) or another local fake. **No test may consume Groq quota.** Inject the sleeper (and ideally the clock) into retry code so tests run instantly.

---

## 7. Reference controller flow (adapt; don't copy blindly)

The grader checks **invariants**, not one exact tool sequence.

```
run(incident):
  state = AgentState(limits=configs/limits.json, risk=configs/risk_policy.json)
  bootstrap: get_incident via registry -> record evidence + world_version
  plan = planner.create(...)            # LLM call, validated; fallback if invalid
  while state.status == RUNNING:
      if wall_clock_exceeded or hard budget hit:  -> terminate (budget_exhausted / escalate if possible)
      if budget_low(state):                        -> replan(trigger="budget_low"): verify or escalate
      proposal = model_step()                      # bounded retry; every attempt counted
      if model failed permanently:                 -> ABORT
      if malformed / no tool call / final-text:    -> corrective observation; continue
      verdict = validate(proposal)                 # R8 checklist
      if verdict.rejected:                         -> trace + corrective observation (+ replan if warranted); continue
      if requires_approval(tool):                  # from risk_policy.json
          if not gateway.approve(...):             -> approval_denied obs; remember; replan/escalate; continue
      result = registry.call(tool, args + expected_world_version)   # counts tool budget
      state.update(result)                         # evidence, world_version, fingerprints, outcomes
      decision = replan_policy.should_replan(state, result)
      switch decision: RETRY | REOBSERVE | REPLAN | ESCALATE | ABORT | CONTINUE
      if tool == close_incident and ok:   status = RESOLVED
      if tool == escalate_incident and ok: status = ESCALATED
```

Keep the controller readable: small helpers (`validate`, `handle_stale`, `handle_denial`, `handle_failed_verification`, `budget_guard`) are easier to test and to explain in viva than one giant function. Marks reward correct behavior, not code volume.

---

## 8. Implementation tasks (A–G)

- **Task A — Re-planning policy:** implement `ReplanPolicy.should_replan()` and integrate it. Different failure classes → different responses (retry, re-observe, re-plan, terminate).
- **Task B — Loop guard:** stable action fingerprints; block repeated unsafe/unproductive actions; reset/reinterpret on materially new evidence.
- **Task C — Model retry policy:** bounded exponential/capped backoff for transient model failures; injectable sleeper; permanent errors abort.
- **Task D — Approval integration:** read the risk policy dynamically; call the gateway before High/Critical actions; record request/outcome; on denial re-plan or escalate.
- **Task E — Plan revision:** `Planner.revise()` (or equivalent) that increments the revision counter, preserves useful evidence, and changes the hypothesis/steps/strategy in response to new information.
- **Task F — Controller hardening:** make `AgentController.run()` satisfy every condition in §6; must not depend on one fixed tool sequence.
- **Task G — Tests:** see §9.

The TODO markers are minimum signposts, not the full checklist. Run `python scripts/count_todos.py` to track them, and improve the design beyond deleting comments.

---

## 9. Testing plan

**Requirement:** ≥ 10 student-written tests, covering ≥ 5 different failure classes, with ≥ 4 using the scripted model or another local fake. Put them in a new file (e.g. `tests/student/test_*.py`), not in `tests/public/`.

Suggested coverage (aim for more than the minimum):
1. stale world → re-observe → not blindly retried with the new version;
2. approval denied → action not executed → re-plan or escalate;
3. invalid tool name / bad args / extra params → rejected, never reaches the registry;
4. 429/transient error → bounded retry then safe termination (with injected sleeper);
5. permanent model error → abort with no retry;
6. repeated identical action → blocked after threshold;
7. premature `close_incident` (no verification / stale verification) → rejected;
8. `ok` action + `criteria_met=false` → re-plan;
9. budget nearly exhausted → verify/escalate before the hard limit; graceful budget exhaustion;
10. impossible/external incident → evidence-backed escalation;
11. risk-policy change (e.g. a Medium tool made High in a temp config) → the controller adapts with no code change;
12. model claims "resolved" or "approved" in text → ignored.

Commands:
```bash
pytest -q tests/public -m infrastructure     # must pass before AND after your changes
pytest -q tests/public                        # student-requirement tests, initially failing
pytest -q tests/                              # include your own tests
python scripts/check_banned_imports.py
python scripts/count_todos.py
```
Do **not** edit public tests to make them pass.

---

## 10. Live evaluation runs (student only, consumes Groq quota)

Generate and run the three public scenarios using the student's own roll number (do not invent one):

```bash
python scripts/generate_student_scenario.py --student-id <ROLL-NO> --scenario public-a
# repeat for public-b and public-c
```
Use the CLI (`incidentzero/cli.py`, see the repo README) to run each scenario and save a trace in `traces/`. Don't burn quota on repeated runs during development; use the scripted model. Do live runs early, not the last hour.

For each of public-a/b/c, record in the report: terminal outcome; LLM requests; tool calls; plan revisions (count + trigger); high-risk actions (proposed / approved-or-denied / executed); recovery proof (verification evidence ID + close result, if resolved); redundant calls; approximate runtime.

---

## 11. Deliverables

Submit one ZIP named `A1_<RollNo>_<Name>.zip` containing:

1. the complete modified source repository;
2. `REPORT.md`, 1,200–1,800 words, following the supplied structure. It should cover: architecture, evaluation table for public-a/b/c, **three failure-trace analyses**, limitations, the mitigation-vs-root-cause trade-off (FAQ Q26), and justification for any added tools;
3. `AI_USAGE.md` (supplied template; complete and honest);
4. ≥ 10 student-written tests;
5. trace files for public-a, public-b, public-c;
6. an updated repo `README.md` section with exact setup and run commands;
7. a working `requirements.txt`.

**Do not include:** `.env`, API keys/tokens, virtual environments, cache folders (`__pycache__`, `.pytest_cache`), agent-framework dependencies, or huge logs/artifacts. The TA must be able to run it from a clean environment with the documented commands.

---

## 12. Grading rubric (100 marks): where to spend effort

| Category | Marks | Strong work looks like |
|---|---|---|
| Planning, decomposition, dynamic re-planning | 18 | Useful plan, success criteria, grounded revisions, preserved evidence, correct reaction to stale/denied/contradictory outcomes |
| Agent runtime and explicit state | 16 | Clean controller boundary, correct state, model proposals separated from authoritative execution, explicit terminal state |
| Tool orchestration and validation | 14 | Strict schema/arg checks, unknown-tool rejection, correct tool-result protocol, no fabricated execution, correct world-version handling |
| Failure recovery in a dynamic environment | 14 | Correct retry / re-observe / re-plan / abort distinctions, bounded transients, no blind repetition |
| Safety, approval, stopping correctness | 14 | Dynamic risk policy, real Python-side approval, denial respected, no false success, verify+close invariant |
| Testing, observability, engineering quality | 10 | Failure-focused tests, offline fake model, complete readable traces, modular code, no secret leakage |
| Groq/API budget and efficiency | 8 | Correct accounting, robust 429 handling, economical calls, safe under reduced budget, no quota-burning tests |
| Report and AI-use declaration | 6 | Concise, evaluation table, three failure traces, limitations, complete declaration |

---

## 13. Hidden evaluation and viva: design for these

Hidden tests are adversarial: unseen seeds, state changes between observation and action, misleading tickets, transient tool failures, synthetic 429s, malformed tool calls, approval denial, impossible incidents, reduced budgets, repeated-action loops, and "action ok but recovery unmet."

The viva (about 5–8 min, individual TA) may ask the student to:
- trace one tool request end-to-end: LLM output → validation → approval → execution → observation;
- explain why a specific failure is retried vs re-planned;
- show the loop detector;
- explain how model claims are prevented from becoming false incident closure;
- **change a risk level or call budget** in config and show the system adapts;
- handle an injected malformed tool call or approval denial;
- say what would break if a given line were removed.

So: keep configuration-driven behavior, keep the code small enough to explain, and don't add complexity for its own sake.

---

## 14. Suggested work order

| Day | Focus |
|---|---|
| 1 | Run infrastructure tests; read simulator/tool contracts; map the baseline controller; make one live Groq call |
| 2 | Retry policy, validation flow, risk/approval integration, loop guard, with unit tests |
| 3 | Plan revision and stale-world recovery; scripted-model tests |
| 4 | Terminal verification/closure logic; budget-aware fallback/escalation |
| 5 | Run public-a/b/c, inspect traces, cut redundant calls, harden failure handling |
| 6 | Finish tests, report evaluation table, three failure-trace analyses, AI-use declaration |
| 7 | Clean-room install test, final live runs, secret scan, banned-framework scan, viva prep |

---

## 15. Final pre-submission checklist

- [x] `pytest -q tests/public -m infrastructure` passes
- [x] Student tests (≥ 10, ≥ 5 failure classes, ≥ 4 offline) pass
- [x] `python scripts/check_banned_imports.py` passes
- [x] No API key in source, traces, screenshots, Git history, or `.env`
- [x] High/critical actions genuinely call the approval gateway; risk levels are read from config
- [x] Stale actions cause re-observation and reconsideration
- [x] 429/transient errors cannot cause an infinite retry loop; retries are counted in the LLM budget
- [x] Repeated identical actions are detected and blocked
- [x] Resolved outcomes require `verify_recovery` (`criteria_met=true`) + successful `close_incident` citing the evidence ID
- [ ] Impossible/external cases can end in safe, evidence-backed escalation
- [x] Limits in `configs/limits.json` are unmodified
- [x] Simulator and public tests are unmodified; no private state is accessed
- [x] Public-a/b/c traces included; `REPORT.md` (1,200–1,800 words) and `AI_USAGE.md` complete
- [ ] README run section is accurate from a clean environment
- [ ] Student can explain every major controller transition
