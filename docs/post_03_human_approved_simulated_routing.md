# POST-03 — Human-approved simulated routing workflow

POST-03 demonstrates the operational step after a POST-01 recommendation. It
never calls a payment provider, stores credentials, or changes production
routing. A simulated change exists only in the local Control Tower process.

## Flow

```text
eligible POST-01 recommendation (pending_approval)
→ merchant-operations approval (approved)
→ POST /remediation/changes (simulated_active)
→ inspect target-route health every five-minute demo window
→ manual rollback, automatic rollback after two target windows below 80%, or human completion
```

`POST /remediation/executions` remains the POST-01 compatibility endpoint and
always returns `dry_run` or `denied`. It is not an execution path.

## Guardrails

- The selected alternative must be the recommendation's eligible option.
- The approval must match the recommendation and be `approved`.
- The rollback reference must match the recommendation.
- Applying the same idempotency key returns the original simulated change.
- Every approval, activation, monitoring observation, and rollback is exposed
  in `GET /remediation/audit`.

## Demo endpoints

- `POST /remediation/approvals` — human approves or rejects.
- `POST /remediation/changes` — activates the local simulated change.
- `GET /remediation/workflows/{recommendation_id}` — shows the explicit lifecycle
  (`pending_approval`, `approved`, `simulated_active`, `rolled_back`, or `completed`).
- `GET /remediation/changes/{change_id}` — shows state and monitor windows.
- `POST /remediation/changes/{change_id}/rollback` — human rollback.
- `POST /remediation/changes/{change_id}/complete` — human closes a healthy simulation.
- `GET /remediation/audit` — local audit trail.
