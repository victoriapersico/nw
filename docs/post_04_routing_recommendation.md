# POST-MVP-04 — Simulation-backed routing recommendation agent

## Responsibility boundary

POST-MVP-04 deterministically ranks simulation results and turns the selected
option into a structured, human-reviewable explanation. It does not approve,
apply, monitor, or roll back a routing change.

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

The application first ranks eligible options by confidence-adjusted expected
recovery, then prefers the smaller traffic shift and stable identifiers for
ties. OpenAI does not participate in this selection.

The OpenAI call receives only:

- `Diagnosis`;
- the matching eligible-route `RoutingPolicy`;
- deterministic `SimulationResult` objects, including the application-selected
  result marked explicitly as `deterministic_selection`.

It never receives raw transactions, provider credentials, approval decisions,
execution requests, or routing tools. Its structured output has no `option_id`:
the model may provide qualitative rationale or abstain. Confidence, traffic
percentage, recovery, and cost remain deterministic values copied by the
application from the selected simulation.

## Deterministic gates

The application returns `not_recommended` without an OpenAI call when:

- the diagnosis is `insufficient_evidence`;
- no simulation result exists;
- every alternative is blocked or inconclusive;
- every otherwise eligible alternative violates the routing policy.

The structured explanation rejects any extra field, so OpenAI cannot insert or
replace the selected option. Model-authored wording cannot contain numeric,
capacity, fee, or cost claims; those values are rendered locally from the
selected `SimulationResult`.

## Mock mode

Mock Mode uses the same application-owned ranking and a deterministic explanation.
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
