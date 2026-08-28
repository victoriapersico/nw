# Current local status

## Installed locally

- Matt Pocock skills:
  - prototype
  - diagnosing-bugs
  - code-review
  - grill-with-docs
  - resolving-merge-conflicts

## Local reference repositories

- OpenAI Cookbook:
  - Local path if present: `hackathon-references/openai-cookbook/`

## NOT installed locally

The following repositories are REMOTE REFERENCES ONLY unless explicitly installed later:

- OpenAI Agents SDK
- Vercel Agent Skills
- Vercel Chatbot
- Awesome AI Agents

Do not assume a remote reference is installed.
Before using any local repository or dependency, verify that it actually exists.
Do not install or clone anything automatically unless there is a concrete need.

# REFERENCES.md

External resources available during the hackathon.

These repositories are references and tools, NOT parts of the submitted application unless explicitly needed.

---

## 1. OpenAI Cookbook

Repository:

https://github.com/openai/openai-cookbook

Local copy if available:

hackathon-references/openai-cookbook/

Use for:

- OpenAI API examples
- Responses API
- tool / function calling
- structured outputs
- agent patterns
- file search / retrieval
- multimodal examples
- evaluation patterns

When implementing OpenAI functionality, prefer current official Cookbook patterns over third-party abstractions.

Only adapt the minimum relevant pattern.

Do not copy entire examples or architectures unnecessarily.

---

## 2. OpenAI Agents SDK

Repository:

https://github.com/openai/openai-agents-python

Use when the challenge clearly benefits from:

- agents with tools
- agent handoffs
- guardrails
- sessions
- tracing
- agent orchestration

Do NOT introduce Agents SDK merely because the project involves AI.

For simple workflows, the standard OpenAI SDK may be sufficient.

---

## 3. Matt Pocock Skills

Repository:

https://github.com/mattpocock/skills

Several skills may already be installed for the coding agent.

Especially useful:

### prototype

Use to rapidly test a product or implementation idea.

### diagnosing-bugs

Use when a difficult bug cannot be immediately explained.

### code-review

Use before final submission or after significant implementation.

### grill-with-docs

Use after receiving the challenge to stress-test the proposed solution and assumptions.

### resolving-merge-conflicts

Use when concurrent work creates Git merge or rebase conflicts.

Use these skills as engineering support.

They are not part of the hackathon product.

---

## 4. Vercel Agent Skills

Repository:

https://github.com/vercel-labs/agent-skills

Use ONLY if the project uses React / Next.js or a relevant Vercel stack.

Potential uses:

- frontend review
- UI/UX improvements
- React best practices
- performance review

Ignore this resource if the frontend remains Streamlit.

---

## 5. Vercel Chatbot

Repository:

https://github.com/vercel/chatbot

Reference only.

Potentially useful for:

- AI application UI patterns
- streaming interfaces
- chat UX
- modern AI frontend architecture

Do NOT clone or adapt the entire application during the hackathon unless there is an exceptional reason.

---

## 6. Awesome AI Agents

Repository:

https://github.com/e2b-dev/awesome-ai-agents

Use only for discovery.

Example:

"We need a tool capable of X. Does something appropriate already exist?"

Do not browse this repository without a specific technical need.

---

# Reference usage rule

Do not ask:

"What technology from these repositories can we use?"

Ask:

"What concrete problem do we currently need to solve?"

Then consult the appropriate reference.

Examples:

Need OpenAI tool calling
→ OpenAI Cookbook

Need structured agent orchestration
→ OpenAI Agents SDK

Hard bug
→ diagnosing-bugs skill

Need to challenge our product idea
→ grill-with-docs

Git conflict
→ resolving-merge-conflicts

React frontend needs polish
→ Vercel Agent Skills

Need to discover an existing AI tool
→ Awesome AI Agents

If the existing code already solves the problem reliably:

DO NOT introduce another technology.