# AI Assistance Declaration

Name: Muhammad Abdullah Farhan
Roll number: 25I-7654

## Tools used

- Claude: I provided the assignment PDF and used Claude to generate the implementation-guidance Markdown file (`instructions.md`), including the requirements and checklist for the LLM coding assistant.
- GitHub Copilot: used those instructions to inspect the repository, implement the reliability behavior, add tests, run the virtual-environment validation, execute the live Groq scenarios, and complete the report and documentation.

## What I used them for

I gave Claude the assignment PDF so it could organize the assignment requirements into `instructions.md` for the coding model. I then used GitHub Copilot to follow those instructions: understand the existing controller and tool contracts, implement evidence-backed escalation and reliability behavior, design offline tests for impossible/external incidents, run the test suite in `.venv`, run the three Groq scenarios, and write the report. I reviewed the resulting code, traces, and documentation against the repository contracts.

## Two suggestions I rejected or changed

1. I did not treat a model statement such as "resolved" as proof of recovery. The controller still requires successful `verify_recovery` evidence before `close_incident`.
2. I did not create a hard-coded success path for external incidents. The test model observes the incident and current verification result, then cites evidence IDs supplied by the registry when proposing escalation.

## One AI-generated or AI-assisted bug I personally diagnosed

The initial external-case test attempt was too close to a fixed scripted sequence and did not demonstrate uncertainty. I changed it to an adaptive local model that derives the service from the observed incident and derives escalation evidence from prior tool results. This made the test exercise the evidence boundary instead of merely checking a predetermined answer.

## Code ownership statement

I can explain every submitted component, its failure behavior, and the trade-offs I chose. I understand that the TA may ask me to modify the code during viva.

Signature / typed name: Muhammad Abdullah Farhan
