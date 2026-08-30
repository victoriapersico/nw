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

## DEC-024 — Deterministic hourly historical generator

### Alternatives considered
1. Generate each transaction independently without a temporal model.
2. Generate history by hourly merchant-country windows with deterministic local
   random streams.

### Decision
Use option 2 in `backend.data_generator`. A seed plus an hourly timestamp derives
the random stream for that hour. The generator returns a pandas DataFrame with
derived `split` and `hour_of_week` columns, while every raw row is first validated
as a `Transaction`.

### Why
- matches the `merchant × country × hour_of_week` baseline;
- preserves normal seasonal variation without hidden incidents;
- makes a single hour reproducible in isolation for debugging and fixtures;
- supports local CSV persistence without a database.

### Tradeoff
Generating a complete year takes longer than a tiny static fixture. The caller can
generate a shorter hourly-aligned interval while developing.

### Revisit
Only if profiling shows a full-year DataFrame is too slow for the demo machine.

---

## DEC-025 — Baseline implementation and configurable thresholds

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

## DEC-026 — Multi-country problems are represented per country

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

## DEC-027 — Escrow or payment holds are post-MVP only

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

## DEC-028 — Evaluation is a black-box, deterministic runtime harness

### Alternatives considered
1. Hard-code expected alerts in the harness and call that an evaluation.
2. Let the detector read scenario or injection metadata.
3. Define deterministic stimuli and expectations, then run simulator → detector →
   RCA through separate interfaces.

### Decision
Use option 3. The evaluator owns seeds, time, expected outcomes and simulator
stimuli. It passes an `InjectionConfig` only to the simulator and sends the
detector only `DetectionRequest(batch=...)`. It produces JSON and Markdown
reports.

### Why
- proves inference from transaction data rather than test-specific shortcuts;
- makes regressions repeatable and measurable;
- keeps MVP-02, MVP-05 and MVP-07 independently mergeable;
- supports the required 30-scenario challenge suite.

### Tradeoff
An adapter is needed once the live simulator and detector are merged. Until then,
the catalog and its contract can be tested but not executed end-to-end.

### Revisit
Add ground-truth loss reporting when the simulator exposes it, so estimated-loss
error becomes an evaluated metric.

---

## DEC-029 — Detector uses seasonal deviation and per-slice persistence

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

## DEC-030 — Initial incident severity is based on approval-rate drop

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

## DEC-029 — MVP-06 prioritizes without changing the Incident contract

### Decision
Do not add `priority`, `confidence`, or relationship fields to the frozen `Incident` contract for the first MVP-06 implementation.

Incidents are ordered externally using existing fields:

```text
severity → estimated_loss → anomaly_score → conversion_drop_pp
```

`anomaly_score` is the initial proxy for statistical confidence.

### Why
- The current contract already supports deterministic ordering.
- Adding fields unilaterally would create avoidable integration risk for the other tracks.
- Priority is derived data and does not need to be persisted in each incident.

### Tradeoff
The dashboard does not receive a separately named confidence value from the incident engine yet.

### Revisit
If the dashboard, evaluation harness, or RCA needs an explicit confidence field that cannot be derived from anomaly evidence.

---

## DEC-030 — MVP-06 deduplicates only exact incident identities

### Decision
Do not deduplicate incidents merely because they share `merchant` and `country`.
For the current contract, only equal `incident_id` values are treated as duplicate representations of the same incident.

### Why
Two independent payment problems can affect the same merchant and country. MVP-05 does not yet carry enough slice detail (provider, method, bank) for the incident engine to safely merge them.

### Tradeoff
The dashboard can temporarily show multiple incidents for the same merchant-country scope until RCA adds finer evidence.

### Revisit
When detector incidents include a stable affected-slice identity, extend the duplicate key with provider, payment method, issuing bank, and other supported dimensions.

---

## DEC-031 — MVP-08 preserves deterministic RCA facts

### Decision
MVP-08 receives the deterministic `Diagnosis` output produced by MVP-07 and
uses the language model only to author `explanation` and `recommended_action`.
It preserves status, dimensions, evidence, and confidence locally.

### Why
MVP-07 already returns a schema-valid deterministic diagnosis. Preserving its
facts avoids a breaking contract rewrite and prevents the language model from
modifying statistical diagnosis.

### Tradeoff
The first AI layer is a narrative enrichment over the existing Diagnosis model,
rather than a newly named EvidencePackage-to-Diagnosis boundary.

### Revisit
When the team schedules a coordinated, additive EvidencePackage contract change.

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

## DEC-024 — Merchant-specific visual identity

### Alternatives considered
1. Use the same visual identity for every merchant.
2. Create a completely different interface for each merchant.
3. Keep a shared dashboard structure while dynamically adapting its visual identity.

### Decision
Use a single dashboard structure and dynamically apply a different color palette based on the selected merchant.

Initial palettes:

- Rappi: coral.
- Carrefour: blue with red accents.
- Despegar: purple with yellow accents.

Streamlit development controls are also hidden so the demo feels like a finished application rather than a development tool.

### Why
- improves the sense of merchant personalization;
- visually reinforces separation between merchants;
- keeps one interface that is easy to develop and test;
- avoids duplicating components and logic;
- improves the visual quality of the demo.

### Tradeoff
The customization is visual only. It is not yet a complete white-label system and does not use official brand assets.

### Revisit
Review the palettes and add official logos only after the end-to-end MVP flow is complete.


## DEC-026 — Separate customer and judge experiences

### Alternatives considered
1. Display the incident injector inside the customer dashboard.
2. Place the customer dashboard and injector in separate Streamlit pages.
3. Build a separate application for the judge.

### Decision
Keep one customer-facing Streamlit dashboard and expose the Judge Lab as a compact
floating configuration panel anchored in the sidebar. The panel opens above the
dashboard and contains incident configuration, injection and reset controls.

The lab and dashboard share the same application state and backend contracts.

### Why
- testing controls stay collapsed unless a judge deliberately opens the lab;
- the dashboard remains visible while configuring trial-by-fire scenarios;
- judges can inject and observe an incident without navigating between pages;
- one Streamlit application remains simple to run and demonstrate.

### Tradeoff
The lab is visually separated but is not protected by authentication or role-based access.

### Revisit
Consider separate routes, authentication and role-based access only after the end-to-end MVP is stable.


Do not silently change a shared architectural decision in one branch.

## DEC-027 — Use a Stripe-inspired operations dashboard layout

### Decision
Use the classic Stripe dashboard information hierarchy as the visual reference for
the Control Tower: a persistent blue-gray navigation sidebar, compact top utility
bar, dense typography, and rectangular white monitoring panels with subtle borders.
Merchant colors remain accents, while incident red is reserved for operational alerts.

### Why
- judges can scan navigation, status and monitoring data quickly;
- the visual language is familiar for a payments operations product;
- compact panels keep the incident and evidence visible without decorative clutter.

### Tradeoff
The Streamlit implementation approximates the reference layout and does not reproduce
Stripe's proprietary components or interactions exactly.

## DEC-028 — Do not fabricate live monitoring values in the dashboard

### Decision
Keep the compact Streamlit fragment for visual refresh, but render only approval values
already supplied by the Control Tower API. The frontend must not apply deterministic
movements to operational metrics while the simulator and incident endpoints are live.

### Why
- judges must see evidence-based values rather than an animated mock;
- the simulator, detector, RCA and diagnosis endpoints are now available;
- this preserves the isolation guarantee: the Judge Lab configuration never becomes
  dashboard evidence.

### Tradeoff
The API advances simulation on injection and explicit monitoring ticks, rather than
continuously from the browser. Add polling or a server-driven stream only after the MVP
flow is stable.

Update this file whenever the team makes a meaningful change that could come up in technical defense.

## DEC-034 — Demo dashboard polls real simulator windows

### Decision
The Control Tower dashboard advances the local simulator through `POST /monitor/tick`
every five seconds while Live simulator is enabled. It renders approval rate, expected
rate, volume and chart history from `GET /merchants/{merchant}/monitoring`.

### Why
The browser must not invent changing operational values. A visible refresh now maps to
a five-minute simulated transaction window that has passed through the same simulator,
baseline and detector pipeline used by the MVP.

### Tradeoff
Refreshing the dashboard advances the local demo clock. This is appropriate for the
single-user hackathon demonstration but production needs a server-owned scheduler so
multiple viewers do not control monitoring time.

### Revisit
Replace browser-triggered ticks with a background worker or streaming transport when
the system is deployed for multiple users.

## DEC-035 — Demo chart retains a 30-day rolling operational window

### Decision
The live runtime retains 8,640 approval observations per merchant-country chart.
Each observation is one five-minute simulated window, so the retained time horizon is
30 days. The frontend downsamples the rendered SVG to a bounded number of points while
preserving the full time range and dates on the horizontal axis.

### Why
The monthly horizon makes normal variation and incident onset readable in operational
context. Downsampling keeps the page responsive even after the full range is retained.

### Tradeoff
This remains an in-memory history and begins filling when the local simulator starts.
It is not durable incident history.

### Revisit
Production should retain a persistent time series and let users select time ranges,
rather than relying on in-process memory.

## DEC-036 — Recovery recommendations remain bounded, human-approved dry-runs

### Alternatives considered
1. Let the dashboard automatically reroute payment traffic after an incident.
2. Show only a natural-language recommendation.
3. Show deterministic counterfactual route simulations, followed by explicit human approval and a dry-run-only result.

### Decision
Use option 3 for POST-01. The dashboard may request a remediation simulation only
for an active merchant-scoped incident. It presents eligible and blocked target
routes, estimated recovered value, approval estimate, confidence, assumptions,
risks and rollback condition.

An operator may record an approval and run the final demo step, but the backend
returns a `dry_run` result with `executed: false`. No provider credentials,
provider connectors or automatic routing actions exist in this scope.

### Why
- Makes the proposed business value visible without turning a diagnosis into an
  unreviewed payment action.
- Keeps statistical evidence and counterfactual estimates deterministic.
- Produces a clear, defensible demo narrative: detect, diagnose, simulate,
  approve, validate.

### Tradeoff
The interface demonstrates the operational decision flow rather than an actual
provider traffic shift. It must be labeled as a simulation in the demo.

### Revisit
Only after provider-approved integration contracts, routing guardrails,
persistent audit logging, authorization, rollback controls and human operating
procedures are defined.

## DEC-037 — Demo incident reports are session-local and downloadable

### Alternatives considered
1. Add a database before showing any incident history.
2. Show no history or export capability in the demo.
3. Retain incident and recovery entries in the Streamlit session and provide
   CSV and Markdown downloads.

### Decision
Use option 3 for the demo dashboard. Each `incident_id` produces one local log
entry containing the observed cause, severity, estimated loss, deterministic
recovery recommendation and evaluated options. Users can download the current
log as CSV or a grouped monthly Markdown report.

### Why
- Lets judges inspect the operational trail without new infrastructure.
- Keeps exported values tied to the same evidence and simulation shown in the UI.
- Does not claim durable audit storage where none exists.

### Tradeoff
The log survives Streamlit reruns but not a new browser session or application
restart. The monthly report covers only entries captured in the current session.

### Revisit
Replace it with server-side persistent storage and audited exports when the
post-MVP database and authorization work is approved.

## DEC-038 — RCA supports method-bank intersections

### Alternatives considered
1. Diagnose payment method and issuing bank independently, then abstain when both are plausible.
2. Let the injector disclose its selected dimensions to the RCA.
3. Add the deterministic `payment_method × issuing_bank` slice to the RCA's existing supported intersections.

### Decision
Use option 3. The RCA evaluates provider-method, provider-bank,
method-bank and provider-method-bank slices using the same historical and live
evidence rules. The detector still receives only transactions; injection
configuration is never exposed to it or to RCA.

### Why
- A bank-specific outage can be concentrated in one method without being a
  provider outage.
- It lets the Judge Lab demonstrate narrow, previously unseen slices honestly.
- It preserves abstention when the combined slice lacks sufficient evidence.

### Tradeoff
More supported intersections increase the number of candidates the RCA must
evaluate, though the MVP has only a small fixed dimension vocabulary.

### Revisit
Add further intersections only when the evaluation harness demonstrates clear
coverage need and sufficient historical volume.

## DEC-039 — Preserve a dominant single cause when its symptoms span other slices

### Alternatives considered
1. Abstain whenever provider, method and bank symptoms cannot form one sufficiently supported intersection.
2. Always choose the highest-loss candidate, even when alternatives are similarly plausible.
3. Confirm one single-dimension cause only when it explains at least 90% of the loss, exceeds the next single-dimension hypothesis by at least 20%, and has no incompatible competing candidate.

### Decision
Use option 3. A strongly supported bank-only, provider-only or method-only cause may
be confirmed even though its downstream provider/method/bank slices also degrade.
All other cases keep the existing intersection-first selection and abstention rules.

### Why
An outage isolated to one issuing bank naturally appears as degraded CARD and provider
sub-slices. Treating these correlated symptoms as independent competing causes made
the live Mexico bank injection abstain despite strong evidence for the bank.

### Tradeoff
The 90% and 20% thresholds are deterministic heuristics. They must be tested against
new synthetic scenarios to avoid turning truly ambiguous incidents into false certainty.

### Revisit
Recalibrate or replace these thresholds when a larger labeled incident dataset is
available, or if evaluation false-positive/abstention metrics regress.

