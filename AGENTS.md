# AGENTS.md

## Project context

This repository is a generic starter for a 24-hour AI hackathon.

The actual challenge will only be known at kickoff.

The goal is to build an impressive, reliable, working demo under severe time constraints.

Optimize all technical decisions for:

1. Reliability
2. Simplicity
3. Fast implementation
4. Easy debugging
5. Clear business value
6. Demo quality

Do not optimize for production-scale architecture unless the challenge explicitly requires it.

---

## Core engineering principle

Always prefer the smallest complete vertical slice that demonstrates value.

Target:

input
→ backend
→ AI reasoning / decision
→ tool or action
→ structured result
→ frontend

Get one complete happy path working before adding additional features.

---

## Preferred stack

Prefer the existing stack in this repository.

Expected technologies may include:

- Python
- FastAPI
- OpenAI SDK
- Pydantic
- Streamlit
- pandas
- requests
- python-dotenv

Do not introduce additional frameworks without a concrete reason.

Avoid by default:

- LangChain
- LangGraph
- CrewAI
- complex multi-agent architectures
- Redis
- Kubernetes
- unnecessary databases
- unnecessary authentication
- premature infrastructure

If a new dependency is proposed, explain why the existing stack cannot solve the problem first.

---

## AI architecture

Prefer:

frontend
→ FastAPI
→ agent / decision logic
→ Python tools
→ structured response

Use tool calling when the model needs to interact with deterministic functionality or external data.

Prefer structured outputs over parsing arbitrary natural-language responses.

Do not build multiple agents simply for novelty.

A single agent with several well-designed tools is preferable unless multiple agents clearly improve the solution.

---

## Hackathon workflow

When the challenge is revealed:

1. Read the entire challenge carefully.
2. Identify the actual business problem.
3. Identify judging criteria and constraints.
4. Propose a maximum of three possible solutions.
5. Compare them by:
   - business impact
   - feasibility within 24 hours
   - technical risk
   - demo wow-factor
6. Choose the smallest strong solution.
7. Define ONE happy path.
8. Build that path end-to-end.
9. Test it.
10. Only then add sophistication.

Do not begin implementing a large architecture before the happy path is defined.

---

## Challenge adaptation

Challenge-specific code should be easy to find.

Prefer modifying:

- backend/schemas.py
- backend/tools.py
- backend/agent.py
- backend/main.py
- frontend/app.py

Clearly separate generic infrastructure from challenge-specific logic.

---

## Coding agent behavior

Before making large changes:

- inspect the existing repository
- understand the current architecture
- preserve working functionality
- avoid unnecessary rewrites

When fixing bugs:

- reproduce the bug
- identify the cause
- make the smallest safe fix
- verify the fix
- avoid unrelated refactors

When implementing features:

- work in small vertical slices
- execute the code
- test actual behavior
- do not claim success based only on static inspection

---

## Installed skills

Useful engineering skills may be available to the coding agent.

Use them when appropriate, especially for:

- prototyping
- diagnosing bugs
- code review
- grilling/refining requirements
- resolving merge conflicts

Do not invoke a complex workflow if a straightforward solution is faster.

---

## Git and collaboration

This project may be edited by four people simultaneously.

Minimize edits to unrelated files.

Keep commits focused.

Do not overwrite another teammate's work without understanding their intent.

When resolving merge conflicts, preserve the intended behavior from both branches where possible.

Never commit:

- API keys
- `.env`
- credentials
- tokens
- private datasets

---

## Demo reliability

Live-demo reliability has priority over architectural elegance.

Before the final demo:

- verify the full happy path
- verify backend/frontend communication
- handle obvious errors gracefully
- keep sample inputs ready
- prepare deterministic demo data when useful
- avoid last-minute unnecessary refactors

Never break a working demo merely to improve architecture.

---

## External references

See `REFERENCES.md`.

Prefer:

1. official OpenAI documentation/examples
2. official framework documentation
3. trusted engineering references

over random snippets or unnecessary third-party frameworks.

Use external repositories as references.

Do not copy entire external repositories into this project.