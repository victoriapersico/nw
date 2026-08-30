# POST-01 — Counterfactual remediation simulator

## Scope and safety boundary

POST-01 is a deterministic, recommendation-only backend capability. It does
not contain provider credentials, provider connectors, or unrestricted tools.
LLMs may later explain a completed `RoutingRecommendation`, but they never
receive credentials and cannot invoke the simulation, approval, or execution
endpoints on their own.

`ExecutionRequest` is a contract for downstream compatibility only. Provider
execution is disabled. A request without a matching `ApprovalDecision` returns
`denied`; an approved request can only return `dry_run` in this MVP. In every
case `ExecutionResult.executed` is `false`.

## Shared contracts

- `RoutingPolicy`: eligible providers, traffic cap, and execution flags.
- `SimulationRequest`: merchant-scoped request to re-evaluate a known incident.
- `SimulationResult`: deterministic estimate for one traffic-shift option.
- `RoutingRecommendation`: selected option, alternatives, rollback reference,
  and approval requirement.
- `ApprovalDecision`: human approval or rejection.
- `ExecutionRequest` / `ExecutionResult`: idempotent, safety-first execution
  boundary.

All schemas are defined in `backend.schemas`; downstream tracks must import
them rather than define alternate field names.

## Demo policy defaults

Every merchant-country pair receives one explicit default policy:

```text
eligible target providers: Stripe, Adyen, dLocal (never the detected provider)
traffic cap:               50%
candidate traffic shifts:  25%, 50%
dry_run_only:              true
execution_enabled:         false
minimum target sample:     50 historical transactions
```

The target is blocked when its observed live approval rate is below 75% with at
least ten transactions. Historical provider performance determines the
counterfactual estimate; fees and capacity are stated assumptions, not inferred
facts.

## API examples

Create a dry-run simulation for an incident already returned by the Control
Tower:

```json
POST /remediation/simulations
{
  "merchant": "Rappi",
  "incident_id": "inc-rappi-brazil-20250902T131000",
  "dry_run": true,
  "idempotency_key": "simulate-rappi-001"
}
```

Record a human decision:

```json
POST /remediation/approvals
{
  "decision_id": "approval-rappi-001",
  "recommendation_id": "rec-inc-rappi-brazil-20250902T131000",
  "decision": "approved",
  "decided_by": "merchant-operator",
  "decided_at": "2026-08-30T12:00:00Z"
}
```

Run the only permitted execution mode:

```json
POST /remediation/executions
{
  "recommendation_id": "rec-inc-rappi-brazil-20250902T131000",
  "approval_decision_id": "approval-rappi-001",
  "idempotency_key": "execution-rappi-001",
  "rollback_reference": "rollback-inc-rappi-brazil-20250902T131000",
  "dry_run": true
}
```

The response is `dry_run` with `executed: false`. A missing, rejected, or
mismatched approval returns `denied`, also with `executed: false`.
