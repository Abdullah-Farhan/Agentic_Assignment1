# IncidentZero

IncidentZero is a framework-free, bounded incident commander for a local SRE simulator. The Groq model investigates incidents, creates hypotheses and plans, and proposes tool calls. The Python controller is authoritative: it validates proposals, enforces evidence and approval, tracks budgets and world versions, retries transient failures, detects loops, verifies recovery, and chooses a safe terminal status.

The runtime follows this control loop:

```text
Observe -> Plan -> Propose -> Validate -> Approve if required
	-> Execute -> Verify -> Re-plan or Close/Escalate
```

The model never executes simulator actions directly. All environment access goes through `ToolRegistry`.

## Requirements

- Python 3.11 or newer
- PowerShell on Windows, or an equivalent shell on Linux/macOS
- A Groq API key for live runs only
- Internet access for live Groq requests

Offline tests use local scripted models and do not require an API key.

## Installation

Clone the repository and open a terminal at its root:

```powershell
git clone <REPOSITORY-URL>
cd incidentzero_starter
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, enable it only for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

The virtual environment can also be used without activation by replacing `python` with `.\.venv\Scripts\python.exe`.

## Configure Groq

For a live run, set the key in the current shell or place it in a local `.env` file:

```powershell
$env:GROQ_API_KEY = "your-groq-key"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
```

The CLI loads `.env` automatically through `python-dotenv`. Never commit `.env`, print the key, place it in a trace, or include it in screenshots. `.env` is ignored by Git. `GROQ_MODEL` is optional; the CLI defaults to `openai/gpt-oss-20b` and also accepts `--model`.

## Run Live Scenarios

Use your own student or roll number for evaluation. Replace `<ROLL-NO>` in every command:

```powershell
python scripts/generate_student_scenario.py --student-id <ROLL-NO> --scenario public-a
python -m incidentzero.cli run --student-id <ROLL-NO> --scenario public-a

python scripts/generate_student_scenario.py --student-id <ROLL-NO> --scenario public-b
python -m incidentzero.cli run --student-id <ROLL-NO> --scenario public-b

python scripts/generate_student_scenario.py --student-id <ROLL-NO> --scenario public-c
python -m incidentzero.cli run --student-id <ROLL-NO> --scenario public-c
```

The scenario generator prints the incident observation without revealing the root cause. The CLI then runs the agent and prints an `AgentOutcome`. Each run writes a JSONL trace to:

```text
traces/<ROLL-NO>_<SCENARIO>.jsonl
```

High- and critical-risk tools use the Python approval gateway. Review the displayed action, arguments, and justification; type `APPROVE` to execute it. Any other response denies the action and lets the controller re-plan or escalate.

To use a different supported model for one run:

```powershell
python -m incidentzero.cli run --student-id <ROLL-NO> --scenario public-a --model <MODEL-NAME>
```

## Offline Validation

These commands use the local virtual environment and do not consume Groq quota:

```powershell
python -m pytest -q tests/public -m infrastructure
python -m pytest -q tests/public
python -m pytest -q tests/student
python -m pytest -q tests/
python scripts/check_banned_imports.py
python scripts/check_protected_integrity.py
python scripts/count_todos.py
```

The external-dependency cases use a local adaptive model and can be run without credentials:

```powershell
python -m pytest -q tests/student/test_external_escalation.py
```

## Configuration

Runtime limits are read from `configs/limits.json`:

- 14 maximum LLM requests
- 28 maximum simulator tool calls
- 3 total attempts for one transient model operation
- 2 allowed identical action repeats
- 120-second target runtime

Risk levels are read dynamically from `configs/risk_policy.json`. High and critical tools require human approval. Do not hard-code these values in the controller.

## Repository Layout

```text
incidentzero/
	agent/        controller, planner, state, policies, recovery
	approval/     human approval gateway
	environment/  protected local simulator
	model/        Groq and scripted model adapters
	telemetry/    budgets and JSONL traces
	tools/        schemas and registry boundary
tests/
	public/       supplied contract and infrastructure tests
	student/      reliability and scenario tests
configs/        runtime limits, risk policy, and service configuration
docs/           architecture, contracts, FAQ, and report templates
traces/         local run evidence
```

## Safety and Git Hygiene

Do not modify the simulator, supplied public tests, supplied scripts, or protected configuration limits. Do not access private simulator state. The model may propose an action, but only Python validation and the registry can execute it.

Before pushing, check that secrets and local artifacts are excluded:

```powershell
git status --short
git diff --check
```

The repository ignores `.env`, `.venv`, Python caches, logs, generated artifacts, and JSONL traces by default. Do not force-add any of them unless a course submission specifically requires a reviewed, sanitized trace.

## Documentation

- `REPORT.md` contains the architecture, evaluation table, failure-trace analysis, limitations, and live-run evidence.
- `AI_USAGE.md` records the tools and assistance used during implementation.
- `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, and `docs/FAQ.md` describe the design boundaries and assignment constraints.
