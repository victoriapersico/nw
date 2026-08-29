# Post-MVP ideas — Control Tower

This document collects future product ideas. None of these are part of the
hackathon MVP or authorized for implementation unless the team explicitly moves
an item into scope.

## Product direction

The team intends to pursue the ideas in this document after the MVP is stable.
They form the target roadmap, but each item still requires its own design,
security, compliance review, acceptance tests, and explicit implementation
approval.

## 1. Human-approved payment holds / escrow

For marketplace-style payment flows, a future Control Tower could recommend a
temporary payment hold after a high-confidence incident or risk signal.

```text
incident detected
→ recommendation to review or hold
→ human approval
→ action through a licensed payment provider
```

The MVP must never hold, move, release, or reroute money automatically. This
would require provider integration, a ledger, compliance, auditability, and
clear operational ownership. Blockchain is not required; a regulated payment
provider could implement custody if the business case justifies it.

## 2. Remediation simulator

Model the estimated effect of a recommended action without performing it.

Examples:

- Estimate the recovered approved value if traffic were shifted to a healthier provider.
- Compare providers for an affected merchant-country-payment-method slice.
- Show confidence and assumptions, not an automatic execution button.

## 3. Incident memory and recurrence

Persist prior incidents to identify recurring provider, bank, method, or
decline-code patterns. Use it to add context such as “similar incident occurred
last week,” while keeping current transaction evidence as the primary basis.

## 4. External context enrichment

Optionally enrich an already-detected incident with provider-status pages, local
holidays, known outages, weather, or news. External context must never replace
transaction evidence or establish unsupported causal claims by itself.

## 5. Operational notifications

Send structured alerts to Slack, WhatsApp, email, or an on-call system after an
incident is detected and prioritized. The Control Tower UI remains the first
alert channel for the MVP.

## 6. Durable multi-tenant platform

Add persistence, authentication, role-based access, audit logs, merchant tenant
isolation, and a production dashboard only after the monitoring core is stable.

## 7. More advanced detection

Evaluate additional seasonal slices, change-point detection, or other anomaly
models only when deterministic evaluation shows that the interpretable MVP
baseline needs improvement.

## 8. Scalable cloud platform

Move from local demo state to a managed multi-tenant platform once the MVP is
validated.

```text
Next.js web dashboard on Vercel
        ↓
FastAPI service
        ↓
Supabase: Postgres, merchant data, incident history, auth, RLS, audit records
```

Potential Supabase responsibilities:

- Merchant, user, and team membership records.
- Row-level security so each merchant only sees its own data.
- Incident, diagnosis, alert-delivery, and operator-decision history.
- Feedback labels that improve evaluation and future routing policies.
- Realtime dashboard updates where they provide clear product value.

Potential Vercel/Next.js responsibilities:

- Production merchant portal and responsive dashboard.
- Role-specific operations, executive, and account-manager views.
- Secure presentation layer; it must not directly own payment-routing credentials.

## 9. Multi-channel alerting and escalation

Deliver structured incident alerts through configurable channels:

- WhatsApp;
- Slack;
- Microsoft Teams;
- email;
- PagerDuty or another on-call system;
- webhooks for merchant systems.

Each merchant should control channel, severity threshold, recipients, quiet
hours, escalation timing, and acknowledgement behavior. Every delivery and
operator acknowledgement should be stored for audit and reliability metrics.

## 10. Routing recommendation agent

Introduce a narrowly scoped remediation-advisor agent after deterministic RCA.
It receives the incident evidence, current provider health, merchant routing
policy, and approved routing options. It may propose, but not silently invent,
a recommendation such as:

```text
"Consider shifting Brazil PIX traffic from the affected provider to the
healthiest approved provider for a limited period."
```

The agent must return a structured proposal containing:

- affected merchant, country, method, and provider slice;
- recommended target route;
- expected benefit and uncertainty;
- evidence and assumptions used;
- risk, cost, and rollback plan;
- required approval level;
- expiration / review time.

The proposal is included in the alert sent to the merchant or operations team.

## 11. Opt-in routing execution service

For customers who explicitly subscribe to the service, recommendations can move
through a controlled execution workflow:

```text
evidence → recommendation → customer policy check → human/approved auto-approval
→ limited routing change → continuous monitoring → rollback if guardrails fail
```

### Mandatory simulation gate

Before any rerouting recommendation can be executed, the system must run a
counterfactual simulation. The AI may propose a route, but deterministic logic
must estimate the outcome using approved constraints before the proposal becomes
executable.

```text
incident evidence
→ routing recommendation
→ simulate eligible alternative route
→ show expected recovery, cost, uncertainty, and risk
→ customer/human approval or pre-approved policy
→ limited execution
→ live monitoring and rollback
```

The simulation result must be attached to the alert and to the audit record. If
the simulation is inconclusive, violates a policy limit, or lacks sufficient
data, execution is blocked.

Required safeguards:

- Per-merchant explicit opt-in and approved routing destinations.
- Policy limits by country, method, amount, traffic percentage, and severity.
- Feature flags, canary rollout, cooldown periods, and one-click rollback.
- Immutable audit trail of evidence, proposal, approval, execution, and outcome.
- Idempotent provider actions and failure-safe behavior.
- No action when evidence is insufficient or provider health is unknown.
- No rerouting execution without a stored simulation result.

## 12. Additional product ideas

- **Provider scorecards:** approval, latency, decline-code mix, and estimated
  lost value over time by merchant-country-method.
- **SLO and SLA monitoring:** agreed conversion/latency targets with automatic
  breach reports for providers and account managers.
- **Incident workspace:** timeline, owners, acknowledgements, internal notes,
  and status updates for operations teams.
- **Counterfactual routing simulator:** estimate what would have happened using
  a different eligible provider before proposing a change.
- **Merchant policy builder:** no-code rules for alert channels, approval
  thresholds, routing caps, and rollback conditions.
- **Provider connectors:** standardized adapters for status, health, routing,
  and incident-ticket APIs.
- **Post-incident reports:** automatically drafted, evidence-linked summaries
  with loss, recovery, root cause, and follow-up actions.
- **Feedback loop:** let operators mark recommendations helpful or incorrect;
  use that feedback for evaluation before changing automated policies.
- **Privacy and compliance controls:** retention windows, PII minimization,
  export/delete workflows, and region-specific data residency.

## Guardrails

- Do not implement these ideas during MVP work.
- Maintain evidence-first diagnosis and human approval for financial actions.
- Promote an idea only after defining its business value, data needs, risk,
  compliance implications, and acceptance tests.
