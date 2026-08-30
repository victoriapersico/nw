# NextWave x Yuno sandbox demo

This guide demonstrates the local integration boundary without sending real payment
data or email. It distinguishes trusted integration/data-quality failures from
merchant payment-performance incidents.

## Start

In one terminal:

```powershell
python -m uvicorn backend.main:app --reload
```

In a second terminal:

```powershell
python -m scripts.yuno_demo
```

Choose a scenario from the menu. The console renders a business-readable receipt
instead of requiring a raw JSON payload.

## API contract

Open `http://127.0.0.1:8000/docs` to inspect and try the sandbox API.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/sandbox/yuno-webhooks` | Receive a signed sandbox payment event. |
| `GET /v1/sandbox/yuno-system-alerts/{account_id}` | Inspect trusted integration failures. |
| `GET /v1/sandbox/yuno-email-outbox` | Inspect rendered sandbox operations emails. |
| `GET /merchants/{merchant}/incidents` | Read merchant-specific payment performance incidents. |

## Demo story

1. Send a valid webhook: it is normalized and no operational notification is needed.
2. Send an invalid amount or malformed transaction: the signature is verified, the
   payload is rejected safely, and one Yuno Operations notification is rendered.
3. Repeat that selection: the retry is accepted as a duplicate and does not produce
   another email.
4. Send an invalid signature: it receives `401` and no notification is emitted,
   because the origin cannot be trusted.

Merchant approval degradation is a separate product flow. It is diagnosed from valid
transaction data and is surfaced to the affected merchant; it is not represented as a
Yuno system failure without separate evidence.
