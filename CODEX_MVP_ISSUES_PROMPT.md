You are acting as Technical Product Manager + Lead Engineer inside our existing Git repository `nw`.

IMPORTANT REPOSITORY RULES
- Work directly in the current repository.
- Do NOT create a nested repository or a new starter.
- Read and follow `AGENTS.md`.
- Read `REFERENCES.md`.
- Preserve the existing working FastAPI + Streamlit starter.
- Preserve MOCK MODE.
- Do not introduce LangChain, LangGraph, CrewAI, Supabase, Next.js, Vercel, Docker, Redis, auth, or external databases for the MVP unless explicitly requested later.
- Do not implement POST-MVP features yet.
- Do not delete or overwrite working code unnecessarily.
- We are four developers working in parallel, so interfaces/contracts must be frozen before implementation.
- The challenge has a live "trial by fire": judges will inject an unrehearsed incident. The detector must infer it only from transaction data, without receiving the injection configuration.
- The challenge asks for recommendations, NOT automatic remediation.

PROJECT
NextWave Hackathon 2026 — Challenge 2: The Control Tower.

We are building a live payment monitoring and root-cause diagnosis system.

Core pipeline:

transaction stream
→ seasonal baseline
→ anomaly detector
→ incident
→ deterministic root-cause drill-down
→ evidence package
→ OpenAI agent
→ explanation + prioritization + recommended action
→ merchant dashboard

The LLM must NOT invent the statistical diagnosis. Python/data logic produces evidence; the LLM explains and recommends.

DOMAIN

Merchants:
- Rappi
- Carrefour
- Despegar

Countries:
- Mexico
- Brazil
- Colombia

Providers:
- Stripe
- Adyen
- dLocal

Payment methods:
- CARD (all three)
- PIX (Brazil)
- PSE (Colombia)
- OXXO (Mexico)

Issuing banks:

Mexico:
- BBVA México
- Banorte
- Santander México
- Citibanamex

Brazil:
- Itaú
- Bradesco
- Banco do Brasil
- Nubank

Colombia:
- Bancolombia
- Davivienda
- Banco de Bogotá
- BBVA Colombia

Decline codes:
- 05 Do not honor
- 51 Insufficient funds
- 54 Expired card
- 57 Transaction not permitted
- 61 Exceeds amount limit
- 91 Issuer unavailable
- 96 System malfunction

Approved transactions should use decline_code = null.

Transaction fields:
- transaction_id
- merchant
- provider
- payment_method
- country
- issuing_bank
- decline_code
- status
- amount
- timestamp

HISTORICAL DATA / SPLIT

Generate one synthetic year.

Use:
- Jan–Apr = TRAIN
- May–Aug = VALIDATION
- Sep–Dec = TEST

Primary seasonal baseline:
merchant × country × hour_of_week

Optionally precompute additional supported slices where volume permits:
- merchant × country × provider
- merchant × country × payment_method
- merchant × country × issuing_bank

MVP DETECTOR

Start simple and interpretable.

Initial rule:
- minimum volume >= 50 transactions
- absolute conversion drop >= 8 percentage points
- z-score <= -3
- persists for 2 consecutive windows

Use configurable parameters.

A reasonable live window is 5 simulated minutes.

The live simulator should be accelerated and API-friendly. Do NOT make one OpenAI call per transaction.

Architecture:
synthetic batches/windows
→ aggregate metrics
→ detector
→ if anomaly only: RCA + OpenAI

ROOT CAUSE

Implement deterministic drill-down / slice analysis over:
- provider
- payment_method
- issuing_bank
- decline_code
- useful intersections

Compare each live slice with its baseline.

Rank candidate causes using:
- sufficient sample size
- statistical degradation
- excess failures / lost approved value explained
- specificity

Return structured evidence.

If no candidate dominates with enough evidence:
diagnosis_status = "insufficient_evidence"

MONEY IMPACT

Do NOT sum all declines.

Estimate:

expected_approved_amount
= total_attempted_amount × expected_approval_rate

estimated_loss
= expected_approved_amount - actual_approved_amount

Also provide estimated_loss_per_hour where meaningful.

JUDGE INJECTOR

Create a generic injection config.

Example fields:
- merchant
- country
- optional provider
- optional payment_method
- optional issuing_bank
- optional decline_code
- target_approval_rate
- duration if useful

The injector modifies future synthetic transactions.

The detector MUST NOT receive this configuration.

The UI will let the judge inject an unseen slice.

LLM

The LLM receives an evidence package, NOT raw thousands of transactions.

It should produce structured output:
- diagnosis_status
- root_cause_summary
- reasoning_summary
- confidence
- executive_summary
- recommended_action
- evidence_used

It must:
- avoid unsupported claims
- admit insufficient evidence
- recommend but not execute remediation

Use MOCK MODE during development.

DASHBOARD

MVP stays in Streamlit.

Merchant contexts:
- Rappi
- Carrefour
- Despegar

No real auth for MVP.

The backend must filter by merchant context.

Dashboard should show:
- merchant selector / tabs
- top incident alert card
- severity
- expected vs actual conversion
- country
- provider / affected slice
- money lost
- diagnosis
- recommendation
- live monitoring charts for Mexico/Brazil/Colombia
- provider health
- judge incident injector

ALERTING

MVP alert = structured alert object + visible UI notification.

No WhatsApp yet.

EVALUATION

Implement a deterministic synthetic test harness with these scenarios:

1. Normal weekday Mexico → no alert
2. Normal weekday Brazil → no alert
3. Normal weekday Colombia → no alert
4. Weekend natural variation → no alert
5. Low-volume random noise → no alert
6. One high-value decline → no alert
7. Stripe degradation Brazil → detect Stripe
8. Adyen degradation Mexico → detect Adyen
9. dLocal degradation Colombia → detect dLocal
10. PIX outage Brazil → detect PIX
11. PSE outage Colombia → detect PSE
12. OXXO outage Mexico → detect OXXO
13. BBVA México outage → detect issuing bank
14. Itaú over-declining → detect issuing bank
15. Bancolombia outage → detect issuing bank
16. Decline code 91 spike → detect code
17. dLocal × Itaú × Brazil → detect intersection
18. Stripe × PSE × Colombia → detect intersection
19. Adyen × BBVA × Mexico → detect intersection
20. Rappi merchant-specific failure → detect merchant
21. Despegar card-only degradation → detect method/merchant
22. Stripe BR + BBVA MX → detect two incidents
23. PSE CO + Itaú BR → detect two incidents
24. Two incidents same country/different merchants → separate
25. Critical + mild incident → correct priority
26. Low-volume suspicious slice → insufficient evidence
27. Two equally plausible causes → insufficient evidence
28. Natural time-of-day drop → no alert
29. Repeat previous incident → recognize only if memory is later implemented; otherwise mark optional
30. Random unseen injected slice → generic detection works

Metrics:
- detection recall
- false-positive rate
- root-cause accuracy
- multi-incident separation accuracy
- abstention accuracy
- mean detection latency
- estimated-loss error

DECISION LOG

Create or update `DECISIONS.md`.

Every major technical choice must include:
- decision
- alternatives
- chosen option
- why
- tradeoffs
- revisit condition

MVP GITHUB ISSUES

I want EXACTLY the following MVP issues created/planned.

Each issue must contain:
- clear title
- objective
- technical checklist
- Definition of Done
- dependencies/blockers
- suggested labels
- suggested owner track
- files/modules likely affected
- notes on what should NOT be implemented in that issue

ISSUE 00
[MVP-00] Freeze domain schemas and API contracts

Owner: whole team
Blocks all other issues.

Must define:
- Transaction
- Incident
- EvidenceItem
- Diagnosis
- InjectionConfig
- request/response API payloads

Definition of Done:
- shared Pydantic schemas committed
- example JSON payloads documented
- no track needs to invent new field names independently

ISSUE 01
[MVP-01] Build one-year synthetic historical transaction generator

Track: Data

Must include:
- all merchants/countries/providers/methods/banks/codes above
- realistic amounts
- timestamps
- seasonal approval behavior
- reproducible random seed
- time splits Jan–Apr / May–Aug / Sep–Dec
- valid payment-method/country combinations

Definition of Done:
- reproducible dataset
- validates against Transaction schema
- seasonal patterns visible
- usable as DataFrame and persisted locally

ISSUE 02
[MVP-02] Build live stream simulator and generic incident injector

Track: Data

Must include:
- accelerated simulated ticks
- batch/window transaction generation
- configurable speed
- generic injection across dimensions
- target_approval_rate
- injection hidden from detector

Definition of Done:
- normal stream runs
- unseen incident can be injected
- detector only receives transactions
- supports demo acceleration

ISSUE 03
[MVP-03] Build synthetic evaluation harness with 30 scenarios

Track: Data/Testing

Definition of Done:
- scenarios above encoded
- deterministic seeds
- expected outcomes
- one command runs evaluation
- machine-readable and human-readable summary

ISSUE 04
[MVP-04] Build seasonal approval baseline

Track: ML

Must include:
- time split
- merchant × country × hour_of_week baseline
- variance/uncertainty
- min volume support
- optional supported slices

Definition of Done:
- returns expected conversion for valid window
- no leakage
- tests
- decision documented

ISSUE 05
[MVP-05] Implement anomaly detector and monetary impact

Track: ML

Must include:
- rolling window
- actual vs expected conversion
- min volume
- absolute drop
- z-score or selected test
- consecutive-window rule
- estimated loss
- Incident output

Definition of Done:
- basic normal/noise cases do not fire
- obvious degradation fires
- loss is computed correctly
- thresholds configurable

ISSUE 06
[MVP-06] Support simultaneous incidents and prioritization

Track: ML / Incident engine

Must include:
- multiple anomalies
- deduplicate overlapping symptoms
- separate unrelated incidents
- severity / priority
- monetary impact + confidence

Definition of Done:
- scenarios 22–25 handled
- ordered incidents emitted
- independent incidents not merged

ISSUE 07
[MVP-07] Implement deterministic root-cause drill-down engine

Track: RCA

Must include:
- provider analysis
- payment method
- issuing bank
- decline code
- intersections
- baseline vs live
- candidate ranking
- explained-loss share
- evidence thresholds

Definition of Done:
- outputs structured EvidencePackage
- works without OpenAI
- initial synthetic causes found
- generic unseen slices supported

ISSUE 08
[MVP-08] Implement LLM diagnosis, explanation, recommendation and abstention

Track: AI

Must include:
- consume EvidencePackage
- structured output
- operations explanation
- executive one-liner
- recommendation only
- insufficient_evidence
- mock mode
- real OpenAI mode

Definition of Done:
- stable structured response
- no unsupported claims in tests
- can abstain
- no raw transaction dump sent
- OpenAI only invoked on incidents

ISSUE 09
[MVP-09] Build merchant Control Tower dashboard

Track: Frontend

Must include:
- merchant tabs/selector
- isolated merchant context
- summary metrics
- country monitoring
- provider health
- live approval charts
- FastAPI calls

Definition of Done:
- can switch merchant
- no cross-merchant data in merchant view
- understandable live monitoring
- works with mock backend

ISSUE 10
[MVP-10] Build incident cards and judge injection UI

Track: Frontend

Must include:
- alert card
- severity
- expected vs actual
- money loss
- diagnosis
- recommendation
- injector controls
- target approval rate
- inject action

Definition of Done:
- judge can inject without code changes
- UI updates automatically
- injector config never leaks into detector

ISSUE 11
[MVP-11] End-to-end alert integration

Track: Integration

Must connect:
stream → detector → incident → RCA → agent → UI

Definition of Done:
- complete happy path works
- no manual intervention after injection
- safe error handling
- mock fallback
- known-good demo path documented

ISSUE 12
[MVP-12] Trial-by-fire hardening and final evaluation

Track: whole team

Must test:
- normal noise
- single incident
- simultaneous incidents
- narrow slice
- insufficient evidence
- random unseen injection
- latency
- restart/fallback

Definition of Done:
- agreed critical scenarios pass
- measured metrics saved for pitch
- demo fallback ready
- no blocking bugs

PARALLELIZATION PLAN

After ISSUE 00 is closed:

Developer A:
01 → 02 → 03

Developer B:
04 → 05 → 06

Developer C:
07 → 08

Developer D:
09 → 10

Then team:
11 → 12

IMPORTANT:
Some tracks will need stubs/mocks while upstream issues are incomplete.
Use frozen schemas and fixtures so developers can proceed independently.

POST-MVP — DO NOT IMPLEMENT NOW
- remediation simulator
- external context/news/weather/outages
- WhatsApp/Slack alerts
- incident memory
- Next.js/Vercel migration
- Supabase persistence/auth/RLS
- RAG for account managers

YOUR TASK NOW

1. Inspect the current repository and understand the starter.
2. Do NOT implement the MVP yet.
3. First, identify any conflict between the existing code and the plan above.
4. Propose the minimum changes required to support the issue plan.
5. Create `DECISIONS.md` if it does not exist.
6. Create the 13 MVP GitHub Issues above.

If GitHub CLI is authenticated and issue creation is available:
- create labels if appropriate
- create the issues in GitHub
- do not start coding them yet

If GitHub issue creation is NOT available:
- create `docs/issues/` with one Markdown file per issue
- include exact `gh issue create` commands or a simple script we can run later

7. After creating/planning the issues, output:
- issue number/title
- dependencies
- which developer track owns it
- which issues can start immediately after MVP-00
- any repo-level change needed before parallel work begins

Do not add POST-MVP implementation.
Do not refactor working starter code unnecessarily.
