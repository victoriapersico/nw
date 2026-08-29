# MVP-00 — Frozen domain contracts

The shared Pydantic contracts live in `backend.schemas`. Every track imports those
models and vocabulary; no track defines alternative field names or values.

`TransactionBatch` is the only simulator-to-detector transport contract. It has
transactions and its simulated time window, but deliberately has no injection
configuration. `InjectionConfig` is only used by the simulator/judge API.

The API payloads are `CreateInjectionRequest`/`CreateInjectionResponse`,
`DetectionRequest`/`DetectionResponse`, and `DiagnosisResponse`. The existing
starter `/analyze` route is intentionally untouched until its replacement is built.

## Transaction example

```json
{
  "transaction_id": "txn-2026-01-15-000001",
  "merchant": "Rappi",
  "provider": "dLocal",
  "payment_method": "PIX",
  "country": "Brazil",
  "issuing_bank": "Itaú",
  "decline_code": null,
  "status": "approved",
  "amount": 42.50,
  "timestamp": "2026-01-15T20:05:00+00:00"
}
```

An approved transaction always has `decline_code: null`; a declined transaction
must contain one of `05`, `51`, `54`, `57`, `61`, `91`, or `96`.

## Injection request example

```json
{
  "config": {
    "merchant": "Rappi",
    "country": "Brazil",
    "provider": "dLocal",
    "payment_method": "PIX",
    "issuing_bank": null,
    "decline_code": "91",
    "target_approval_rate": 0.35,
    "duration_windows": 6
  }
}
```

## Simulator-to-detector example

```json
{
  "window_start": "2026-09-01T14:00:00+00:00",
  "window_end": "2026-09-01T14:05:00+00:00",
  "transactions": ["<Transaction objects only>"]
}
```

The live endpoint receives that batch wrapped as `{ "batch": ... }` and returns
`{ "incidents": [] }` when no anomaly is detected. A diagnosis endpoint returns
`{ "diagnosis": { ... } }` using the `Diagnosis` contract.

When supplied in `InjectionConfig`, `decline_code` is the code assigned to the
new declines caused by that injection. It is not sent to the detector.

## Incident and diagnosis ownership

- The detector creates `Incident`.
- The root-cause layer calculates `EvidenceItem` values and creates `Diagnosis`.
- The LLM may phrase the diagnosis and recommendation, but it does not receive
  raw batches or calculate the metrics.
