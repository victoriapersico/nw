# DECISIONS.md

# NextWave Hackathon 2026 — Technical Decision Log
## Challenge 2: The Control Tower

This document records the main product and architecture decisions made by the team during the hackathon.

For every major decision we record:
- the decision;
- alternatives considered;
- why we chose it;
- tradeoffs;
- when we would revisit it.

The goal is to make the system easy to defend technically in front of the judges.

---

## DEC-001 — Challenge selection

### Decision
We selected **Challenge 2 — The Control Tower**.

### Why
It combines statistical/ML reasoning, anomaly detection, explainable root-cause analysis, agentic AI, structured tools, a visual live demo and measurable evaluation.

### Tradeoff
It requires coordinating simulator, baseline, detector, RCA, LLM and dashboard.

---

## DEC-002 — Reuse the existing `nw` starter

### Decision
Reuse the existing generic `nw` starter instead of rebuilding from scratch.

Current base architecture:

```text
Streamlit
   ↓
FastAPI
   ↓
agent / decision logic
   ↓
Python tools
   ↓
structured Pydantic output
```

### Why
- already tested end-to-end;
- reduces setup time;
- includes MOCK MODE;
- keeps frontend/backend separation;
- lets us focus on challenge-specific logic.

### Tradeoff
Some generic starter code may later need replacement.

### Revisit
Only if the starter becomes a blocker.

---

## DEC-003 — Frozen domain contracts before parallel development

### Decision
`backend.schemas` is the source of truth for shared models and enums.

Frozen contracts include:
- `Transaction`
- `TransactionBatch`
- `InjectionConfig`
- `Incident`
- `EvidenceItem`
- `EvidencePackage`
- `Diagnosis`
- API request/response wrappers

No track defines alternative field names or enums.

### Why
Four developers need to work independently without breaking integration.

### Tradeoff
Shared-schema changes require coordination.

---

## DEC-004 — Incident detection starts at `merchant × country`

### Decision
For the MVP, an `Incident` represents a statistically significant degradation detected for a specific:

```text
merchant × country
```

The detector creates the `Incident`.

The RCA layer then drills down into:
- provider;
- payment method;
- issuing bank;
- decline code;
- relevant intersections.

### Why
- simple;
- fast to implement;
- easy to validate and explain;
- aligned with the official challenge scenario;
- keeps RCA responsible for discovering the actual cause.

### Tradeoff
A single cross-country provider problem may initially create more than one merchant-country incident.

### Revisit
Only after the full MVP is stable.

---

## DEC-005 — Detection and diagnosis are separate stages

### Alternatives considered
1. Let the LLM inspect raw transactions and determine the cause.
2. Use deterministic/statistical code to detect anomalies and generate evidence, then use the LLM to explain it.

### Decision
Use option 2.

Pipeline:

```text
transactions
→ baseline
→ anomaly detector
→ Incident
→ deterministic RCA
→ EvidencePackage
→ LLM
→ Diagnosis / recommendation
```

### Why
- lower hallucination risk;
- easier to test;
- lower API cost;
- lower latency;
- more explainable;
- easier technical defense.

### Tradeoff
We must implement a separate RCA engine.

---

## DEC-006 — Statistical seasonal baseline before complex ML

### Alternatives considered
- fixed approval threshold;
- Isolation Forest;
- neural anomaly detector;
- seasonal statistical baseline;
- EWMA / change-point approaches.

### Decision
Start with a seasonal baseline and statistical deviation detector.

Primary baseline:

```text
merchant × country × hour_of_week
```

Time split:

```text
Jan–Apr  → TRAIN
May–Aug  → VALIDATION
Sep–Dec  → TEST
```

Initial detector criteria:

```text
minimum volume >= 50 transactions
absolute drop >= 8 percentage points
z-score <= -3
persists for 2 consecutive windows
```

### Why
- interpretable;
- fast;
- little tuning;
- captures day/time seasonality;
- avoids leakage;
- appropriate for 24 hours.

### Tradeoff
Potentially less flexible than more sophisticated anomaly models.

### Revisit
If the MVP is stable and evaluation shows clear weaknesses.

---

## DEC-007 — Five-minute simulated windows

### Decision
One detection window represents:

```text
5 simulated minutes
```

The simulator may run faster than real time.

Example:

```text
1 real second ≈ 1 simulated minute
```

`duration_windows = 6` therefore means about 30 simulated minutes.

### Why
- enough transactions per window;
- responsive demo;
- easy to reason about;
- avoids per-transaction processing.

### Tradeoff
Detection latency depends on window size.

---

## DEC-008 — No OpenAI call per transaction

### Decision
OpenAI is invoked only after an anomaly is detected and evidence has been computed.

```text
synthetic transactions
→ local aggregation
→ detector
→ RCA
→ only then OpenAI
```

### Why
- much lower token/API usage;
- lower latency;
- fewer failure points;
- deterministic monitoring;
- easier stress testing.

### Tradeoff
The LLM does not participate in low-level detection.

---

## DEC-009 — The LLM receives evidence, not raw history

### Decision
The LLM receives an `EvidencePackage` with already-computed metrics and candidate causes.

It does not receive thousands of raw transactions.

### Responsibilities
The LLM may:
- explain;
- summarize;
- prioritize;
- recommend;
- adapt wording for operations/executive audiences;
- abstain when evidence is insufficient.

The LLM must not:
- invent evidence;
- silently recalculate the detector;
- claim unsupported root causes.

### Why
Better reliability, cost, explainability and technical defense.

---

## DEC-010 — Explicit `insufficient_evidence` behavior

### Decision
If RCA cannot isolate a sufficiently supported cause, return:

```text
insufficient_evidence
```

instead of inventing one.

### Why
Safer and explicitly valuable in the challenge.

### Tradeoff
Some incidents may not have a definitive diagnosis.

---

## DEC-011 — Monetary impact uses excess loss, not all declines

### Decision
Do not sum every rejected transaction.

Estimate:

```text
expected_approved_amount
=
total_attempted_amount × expected_approval_rate
```

Then:

```text
estimated_loss
=
expected_approved_amount - actual_approved_amount
```

Also compute `estimated_loss_per_hour` where useful.

### Why
Some declines are normal; counting all rejects would overstate impact.

### Tradeoff
It is an estimate, not an accounting value.

---

## DEC-012 — Generic judge incident injection

### Decision
`InjectionConfig` is used only by the simulator/judge interface.

It may include:
- merchant;
- country;
- provider;
- payment method;
- issuing bank;
- decline code;
- target approval rate;
- duration.

The detector never receives injection configuration.

### Why
Trial-by-fire must demonstrate genuine inference from transaction data.

### Tradeoff
The simulator must be flexible enough to create realistic unseen failures.

---

## DEC-013 — `target_approval_rate` instead of abstract failure severity

### Decision
Use a target approval rate for injected incidents.

Example:

```text
normal approval ≈ 92%
target approval = 35%
```

### Why
- interpretable;
- directly tied to challenge metric;
- easy to demo and test.

---

## DEC-014 — Streamlit first, Next.js/Vercel only after MVP stability

### Decision
Keep the MVP dashboard in Streamlit.

Potential later architecture:

```text
Next.js / React
       ↓
     FastAPI
       ↓
detector / RCA / OpenAI
```

### Why
Streamlit already works and maximizes speed.

### Tradeoff
Less polished than a custom React frontend.

### Revisit
Only after:
- happy path works;
- trial-by-fire works;
- evaluation is stable.

---

## DEC-015 — No real authentication in the MVP

### Decision
Support three merchant contexts:
- Rappi;
- Carrefour;
- Despegar.

Backend data is filtered by merchant, but no full login/auth initially.

### Why
Auth is not core to the challenge and would consume time.

### Tradeoff
Not production-ready multi-tenant authentication.

### Revisit
If Supabase/auth becomes useful after the core is stable.

---

## DEC-016 — No database dependency for the first MVP

### Decision
Start with local synthetic data/DataFrames/files.

Do not introduce Supabase until persistence is actually needed.

### Why
- fewer moving parts;
- faster development;
- easier testing;
- easier local demo.

### Tradeoff
No durable production persistence initially.

### Revisit
If we need incident history, shared state, auth/RLS or cross-session persistence.

---

## DEC-017 — Recommendation only; no automatic remediation

### Decision
The Control Tower recommends the next action but does not automatically reroute real traffic.

Example:

```text
Recommended action:
Consider rerouting affected PIX traffic from dLocal to the healthiest provider.
```

### Why
This matches the challenge objective.

### Tradeoff
The system stops before execution.

### Post-MVP
A remediation simulator may estimate outcomes without executing them.

---

## DEC-018 — External context is post-MVP enrichment

### Decision
News, weather, football matches, holidays and external outages are not part of primary RCA.

Order:

```text
transaction evidence
→ root cause
→ optional external context enrichment
```

### Why
External events can create speculative correlations.

### Tradeoff
The MVP may miss useful context.

---

## DEC-019 — Structured alert first; WhatsApp/Slack later

### Decision
MVP alerting means creating a structured alert object and showing it in the Control Tower UI.

### Why
Satisfies the core product need without adding external integration risk.

### Post-MVP
WhatsApp, Slack or email.

---

## DEC-020 — Evaluation uses deterministic synthetic scenarios

### Decision
Use a synthetic test harness with predefined and randomized scenarios.

Core categories:
- normal weekday;
- weekend variation;
- low-volume noise;
- provider degradation;
- payment-method outage;
- issuing-bank outage;
- decline-code spike;
- intersections;
- simultaneous incidents;
- ambiguous evidence;
- unseen injected incident.

### Metrics
- detection recall;
- false-positive rate;
- root-cause accuracy;
- multi-incident separation accuracy;
- abstention accuracy;
- mean detection latency;
- estimated-loss error.

### Why
We need measured evidence, not only a successful demo.

---

## DEC-021 — MOCK MODE remains available

### Decision
Keep MOCK MODE working even after real OpenAI integration.

### Why
- faster development;
- zero-credit deterministic tests;
- backup if API/Wi-Fi fails;
- safer demo fallback.

### Tradeoff
Mock behavior must stay aligned with the real response schema.

---

## DEC-022 — API budget goes to evaluation after core stability

### Decision
Do not spend OpenAI calls on deterministic tasks.

Use API budget primarily for:
- final diagnosis runs;
- prompt evaluation;
- adversarial cases;
- repeated test scenarios;
- uncertainty tests;
- stress testing;
- final technical review.

### Why
Maximizes useful information gained per API call.

---

## DEC-023 — Parallel development after contracts are frozen

### Decision
After MVP-00, split into four tracks.

### Track A — Data / Simulator
- historical generator;
- live stream;
- incident injector;
- evaluation scenarios.

### Track B — ML / Detection
- seasonal baseline;
- anomaly detector;
- monetary impact;
- simultaneous incident handling.

### Track C — RCA / AI
- deterministic RCA;
- evidence package;
- LLM explanation;
- recommendation;
- abstention.

### Track D — Frontend / Integration
- merchant dashboard;
- live charts;
- incident cards;
- judge injector UI.

### Why
Frozen contracts let each track work independently with mocks/fixtures.

---

## DEC-024 — Baseline implementation and configurable thresholds

### Alternatives considered
1. Use one fixed conversion threshold for every merchant and country.
2. Hard-code all detector and baseline thresholds inside the implementation.
3. Train an interpretable seasonal baseline and configure operational thresholds centrally.

### Decision
The initial baseline is trained only with January-April transactions and groups results by:

```text
merchant x country x hour_of_week
```

Each supported bucket stores approval rate, sample size, and variance. A bucket with fewer than `BASELINE_MINIMUM_VOLUME` transactions is unavailable and returns no expected conversion.

Global defaults are declared through environment settings:

```text
BASELINE_MINIMUM_VOLUME=50
DETECTOR_MINIMUM_VOLUME=50
DETECTOR_ABSOLUTE_DROP=0.08
DETECTOR_Z_SCORE_THRESHOLD=-3
DETECTOR_CONSECUTIVE_WINDOWS=2
LIVE_WINDOW_MINUTES=5
```

### Why
- Keeps normal behavior seasonal and explainable.
- Avoids training leakage from validation or test months.
- Allows calibration without editing detector code.
- Avoids alerting on statistically weak low-volume slices.

### Tradeoff
The first baseline does not model every finer dimension and can abstain when a merchant-country-hour bucket lacks support.

### Revisit
After evaluation shows that supported optional slices or threshold calibration are needed to reduce false positives or improve recall.

---

## DEC-025 — Multi-country problems are represented per country

### Alternatives considered
1. Allow one `InjectionConfig` and one `Incident` to contain a list of countries.
2. Use one country per injection and create one merchant-country incident per affected country.

### Decision
Keep `InjectionConfig.country` and `Incident.country` singular. A merchant issue that affects several countries is expanded into one injection per country and is detected as independent merchant-country incidents.

The UI may offer an "all countries" convenience option, but it must expand into individual injection requests before reaching the simulator.

### Why
- Baseline conversion, transaction volume, and money impact are country-specific.
- A failure can have different severity by country.
- It preserves the detector's transaction-only isolation from injection intent.
- MVP-06 can later relate incidents without losing country-level evidence.

### Tradeoff
One broad provider or merchant failure can create several visible incidents.

### Revisit
Only after MVP-06 is stable and the dashboard needs a derived cross-country incident grouping for presentation.

---

## DEC-026 — Escrow or payment holds are post-MVP only

### Decision
Do not implement escrow, funds custody, or automatic payment holds in the Control
Tower MVP. Retain it as a possible future integration for marketplace-style flows.

### Why
The MVP monitors transactions and recommends actions; it does not move, retain,
or release money. Escrow would require payment-provider integrations, a ledger,
compliance, auditability, and explicit operational approval.

### Future direction
If later approved, the safe progression is:

```text
detected incident → recommendation to review or hold → human approval → payment-provider action
```

The detector must not initiate a hold automatically.

### Revisit
Only after the core monitoring MVP is stable and a licensed payment/custody
provider plus compliance requirements are in scope.

---

## DEC-027 — Detector uses seasonal deviation and per-slice persistence

### Alternatives considered
1. Alert on any raw conversion decrease.
2. Alert after one unusual live window.
3. Compare each merchant-country live group to its seasonal baseline and require repeated statistical degradation.

### Decision
MVP-05 evaluates each `merchant x country` group independently. It calculates actual approval conversion for the live batch, compares it to the expected baseline conversion, and computes:

```text
conversion_drop_pp = (expected_conversion - actual_conversion) x 100
z_score = (actual_conversion - expected_conversion) / sqrt(baseline_variance / live_volume)
```

An incident candidate must meet configured volume, conversion-drop, and z-score thresholds for the configured number of consecutive windows. The persistence counter is tracked separately for each `(merchant, country)` key.

### Why
- A raw decrease is not enough without seasonal context.
- Repeated windows reduce noise-based false positives.
- Independent counters allow simultaneous incidents in different merchants or countries.
- The approach remains explainable and directly testable.

### Tradeoff
The first alert is delayed until the persistence threshold is met, and a broad merchant-country incident may contain multiple finer causes that RCA resolves later.

### Revisit
After MVP-06 and evaluation scenarios 22-25 demonstrate whether additional slice-level detection or grouping is required.

---

## DEC-028 — Initial incident severity is based on approval-rate drop

### Decision
MVP-05 assigns a preliminary severity from the measured conversion drop:

```text
critical: drop >= 30pp
high:     drop >= 20pp
medium:   drop >= 12pp
low:      drop >= configured minimum drop
```

### Why
This is deterministic, immediately explainable, and available when an incident is first emitted.

### Tradeoff
Conversion drop alone is not a complete business priority measure; a small high-value incident can deserve more attention than a large low-value one.

### Revisit
MVP-06 will combine severity with estimated loss, confidence, and persistence to prioritize simultaneous incidents.

---

# Adding a new decision

Append decisions using:

```markdown
## DEC-XXX — Short title

### Alternatives considered
1. ...
2. ...

### Decision
...

### Why
- ...

### Tradeoff
...

### Revisit
...
```

Do not silently change a shared architectural decision in one branch.

Update this file whenever the team makes a meaningful change that could come up in technical defense.
