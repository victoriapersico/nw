# POST-MVP-04 — Simulation-backed routing recommendation agent

## Responsibility boundary

POST-MVP-04 turns deterministic simulation results into a structured,
human-reviewable recommendation. It does not approve, apply, monitor, or roll
back a routing change.

```text
Diagnosis + RoutingPolicy + SimulationResult[]
→ POST-MVP-04 recommendation
→ human-assisted execution workflow
→ pending_approval
```

The human-assisted workflow may store the recommendation in its audit log and
transition it through `pending_approval`, `approved`, `simulated_active`,
`rolled_back`, or `completed`. POST-MVP-04 never performs those transitions.

## Model boundary

The OpenAI call receives only:

- `Diagnosis`;
- the matching eligible-route `RoutingPolicy`;
- deterministic `SimulationResult` objects.

It never receives raw transactions, provider credentials, approval decisions,
execution requests, or routing tools. The model may select one eligible
`option_id`, provide qualitative rationale, or abstain. Confidence, traffic
percentage, recovery, and cost remain deterministic values copied by the
application from the selected simulation.

## Deterministic gates

The application returns `not_recommended` without an OpenAI call when:

- the diagnosis is `insufficient_evidence`;
- no simulation result exists;
- every alternative is blocked or inconclusive;
- every otherwise eligible alternative violates the routing policy.

An OpenAI selection is rejected when its option is unknown, blocked, or outside
the provider allowlist or traffic cap. Model-authored wording cannot contain
numeric, capacity, fee, or cost claims; those values are rendered locally from
the selected `SimulationResult`.

## Mock mode

Mock Mode ranks eligible alternatives by confidence-adjusted expected recovery,
then prefers the smaller traffic shift and a stable provider-name tie-breaker.
It returns the same `RoutingRecommendation` contract without making an API call.

## Approval and audit integration

The POST-03 human-assisted workflow accepts only a recommendation where:

- `status == "recommended"`;
- `recommended_option_id` resolves to an eligible attached simulation;
- `proposed_traffic_cap` is within the attached policy;
- `required_approval == "merchant_operations"`;
- `dry_run == true`.

Its first state is `pending_approval`. The `recommendation_created` audit event
stores the complete serialized `RoutingRecommendation`, the creating actor, and
a timestamp. A safe abstention is also audited but does not create a workflow.
Rejection, application simulation, monitoring, completion, and rollback events
belong to POST-03 and are never authored by the recommendation agent.
