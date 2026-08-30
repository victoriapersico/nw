# The Control Tower

NextWave Hackathon 2026 · Challenge 2

The Control Tower is a live payment-operations demo for Rappi, Carrefour, and
Despegar across Mexico, Brazil, and Colombia. It converts simulated payment
attempts into interpretable incidents: seasonal anomaly detection, monetary
impact, deterministic root-cause analysis (RCA), evidence-bound narration, and a
merchant-scoped dashboard.

The product recommends an action; it never changes routing or remediates payments
automatically.

The repository also includes two deliberately bounded demo surfaces: a local
notification inbox with optional read-only Telegram delivery, and a separate
Yuno API Manager sandbox. Telegram is opt-in and best-effort; the Yuno surface
uses synthetic local telemetry and contacts neither Yuno nor an email provider.

## What runs end to end

```mermaid
flowchart LR
    H["2025 normal history"] --> B["Seasonal baseline"]
    J["Judge Lab InjectionConfig"] --> S["Live simulator"]
    S --> T["TransactionBatch"]
    B --> D["Anomaly detector"]
    T --> D
    D --> I["IncidentEngine: separate + prioritize"]
    I --> R["Deterministic RCA"]
    R --> N["Mock or OpenAI narration"]
    N --> A["FastAPI live state"]
    T --> A
    A --> U["Streamlit dashboard"]
    A --> L["Local notifications inbox"]
    A -.->|opt-in, best-effort| TG["Telegram incident alert"]
    A --> Y["Yuno API Manager<br/>local synthetic sandbox"]
```

`InjectionConfig` stops at the simulator. The detector, RCA, LLM prompt, and
evaluation observations receive generated transactions or calculated evidence,
never the judge's answer.

Core components:

- Historical data: the committed
  `data/historical_transactions_2025_seed42.csv` is deterministic normal traffic.
  January–April trains the runtime baseline; later months remain validation/test
  data.
- Live simulator: seeded five-minute windows, aligned with the same volume,
  approval, provider, method, and bank behavior used by history.
- Baseline and detector: a smoothed seasonal merchant×country expectation,
  minimum-volume guard, absolute/statistical drop thresholds, and two-window
  persistence.
- Incident handling: independent incidents stay separate and are ordered by
  severity, estimated loss, anomaly score, then conversion drop.
- RCA: deterministic slice comparisons return either `confirmed` dimensions or
  `insufficient_evidence`. The LLM cannot change those facts.
- Dashboard: polls the backend and displays only the current real simulator batch,
  backend incidents, RCA, and recommendations. If FastAPI is unavailable, it
  shows an error and no fake live fallback.
- Notifications: every detected incident creates a local inbox alert. With
  explicit Telegram configuration, the backend can also send a read-only summary
  with evidence, estimated impact, and recommendation. Operator decisions remain
  dashboard-only.
- Yuno API Manager: a separate Streamlit sandbox demonstrates trusted malformed
  traffic isolation, local alert/email previews, and invalid-signature rejection
  without external delivery.

## Install

Run from the repository root with Python 3.11+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

The committed historical CSV is sufficient to start; no data-generation step is
required.

## Configuration and safe demo mode

`.env.example` is ready for deterministic mock narration:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
OPENAI_TIMEOUT_SECONDS=30
MOCK_MODE=true
CONTROL_TOWER_API_URL=http://127.0.0.1:8000
BACKEND_REQUEST_TIMEOUT_SECONDS=90
TELEGRAM_NOTIFICATIONS_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_DASHBOARD_URL=
```

`MOCK_MODE=true` is the primary live-demo mode. It uses the real simulator,
detector, money calculation, IncidentEngine, and RCA; only the final wording is
local and deterministic. This avoids making the judge demo depend on Wi-Fi or an
external API.

For an intentional OpenAI narration test, set a valid `OPENAI_API_KEY` and
`MOCK_MODE=false`. Do not use that as the primary presentation mode: automatic
fallback after an OpenAI request failure is not yet guaranteed.

Never commit `.env`, API keys, tokens, or credentials.

Telegram stays disabled unless `TELEGRAM_NOTIFICATIONS_ENABLED=true` and both
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured locally. An optional
public HTTPS `TELEGRAM_DASHBOARD_URL` adds an **Open Control Tower** button; local
URLs are intentionally not sent as Telegram deep links. Delivery failures never
interrupt monitoring. Telegram cannot approve, reject, simulate, or roll back a
recommendation.

## Start the product

Use two terminals, both at the repository root.

Terminal 1 — backend:

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

Verify it:

```bash
curl http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`. API docs are at
<http://127.0.0.1:8000/docs>.

Terminal 2 — dashboard:

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

Open <http://127.0.0.1:8501>. No `PYTHONPATH` override or extra command is
required.

Optional local Yuno API Manager sandbox:

```bash
source .venv/bin/activate
streamlit run frontend/yuno_demo.py --server.port 8502
```

Open <http://127.0.0.1:8502>. This is a synthetic local operations demo, not a
production Yuno integration.

On Windows PowerShell, the checked-in launcher starts FastAPI, the Control Tower,
and the Yuno sandbox with the repository virtual environment:

```powershell
.\start_demo.ps1
```

Its default endpoints are `8000`, `8501`, and `8502`; optional port parameters
are supported. Telegram remains controlled exclusively by the local `.env`.

## Five-minute judge flow

1. Start in `MOCK_MODE=true` and open the dashboard.
2. Watch two or three normal windows update. No incident should appear.
3. Open **Judge Lab** on the right.
4. Choose a merchant and country, then select one **Anomaly scope**: all traffic,
   provider, payment method, or issuing bank.
5. Use a strong target approval rate (20% is the known-good demo value) and click
   **Inject incident**.
6. The simulator advances, the detector reacts automatically, and the dashboard
   shows the incident, impact, diagnosis status, evidence, and recommendation.
7. Optionally open **Notifications** to show the local incident alert. Keep
   Telegram off for the primary demo so the happy path has no network dependency.
8. For an eligible routing recommendation, click **Approve recommendation** and
   then **Simulate application**. Inspect the before/expected/observed metrics and
   audit log, then choose **Revert simulated change** or **Complete review**.
9. Click **Reset demo** before repeating. This calls `POST /monitor/reset`; it is
   not a Streamlit-only reset.

Known-good injection: **Rappi · Brazil · Stripe · target 20% · 6 windows**.

The same injection can be submitted directly for diagnostics:

```bash
curl -X POST http://127.0.0.1:8000/injections \
  -H 'Content-Type: application/json' \
  -d '{"config":{"merchant":"Rappi","country":"Brazil","provider":"Stripe","target_approval_rate":0.2,"duration_windows":6}}'
```

Reset directly with:

```bash
curl -X POST http://127.0.0.1:8000/monitor/reset
```

## Tests and evaluation

Run the full test suite:

```bash
MOCK_MODE=true PYTHONPATH=. .venv/bin/pytest -q
```

Run all 30 deterministic evaluation scenarios and save both reports:

```bash
MOCK_MODE=true PYTHONPATH=. .venv/bin/python -m backend.evaluation --output artifacts/evaluation
```

Outputs:

- `artifacts/evaluation/evaluation_results.json`
- `artifacts/evaluation/evaluation_summary.md`

The harness separately reports detection recall, false-positive rate, confirmed
root-cause accuracy, abstention accuracy, simultaneous-incident separation, and
mean latency. Estimated-loss error remains explicitly unavailable because the
catalog has no independent ground-truth loss label.

The Incident assistant client uses a 5-second connection timeout and a 70-second
read timeout. The suite includes a slow-LLM regression test that confirms the UI
waits for a valid response beyond the former short timeout.

## Supported Judge Lab scope

Supported trial-by-fire injections are statistically observable slices:

- merchant + country;
- merchant + country + one provider;
- merchant + country + one payment method;
- merchant + country + one issuing bank;
- decline-code degradation when enough declines are present;
- intersections only when they contain enough traffic (evaluation coverage, not
  the primary Judge Lab promise).

Both Judge Lab surfaces render only the filter selected by **Anomaly scope**, so
multiple optional slice filters cannot be submitted accidentally. Ultra-narrow
intersections and mild changes can fall below the detector's merchant×country
minimum-volume/signal policy and are intentionally not promised. See
[`docs/judge_lab_scope_limitations.md`](docs/judge_lab_scope_limitations.md) for
the exact UI contract, reset behavior, and scope rationale.

## Known limitations and fallback strategy

- Detection happens at merchant×country level. Three narrow intersection cases
  and the random narrow catalog case currently fall below detection support.
- A mild second incident in evaluation scenario 25 is statistically too small;
  strong simultaneous scenarios 22–24 are the supported acceptance cases.
- Deterministic RCA abstains when one cause cannot be isolated. The UI preserves
  that result and labels candidate evidence as unconfirmed.
- Active incidents do not auto-resolve after recovery; use **Reset demo** between
  rehearsals.
- Money impact is a non-negative estimate of excess expected approvals multiplied
  by observed average approved amount and scaled per hour. There is no independent
  loss ground truth, so no loss-error accuracy is claimed.
- Runtime state is in memory: no database, authentication, durable incident
  history, multi-user isolation, or automatic remediation.
- If the OpenAI path is unhealthy, restart with `MOCK_MODE=true`. The deterministic
  product pipeline remains fully functional without an API key.
- Telegram is an optional read-only delivery channel and depends on network and
  valid local bot configuration; the local Notifications inbox is the reliable
  fallback and retains all operator actions in the dashboard.
- The Yuno API Manager is a synthetic local sandbox. It does not claim a live Yuno
  contract, real partner telemetry, webhook delivery, or email delivery.

## Delivery package

- [`SUBMISSION.md`](SUBMISSION.md): concise final submission, verified results,
  architecture, setup, and limitations.
- [`DECISIONS.md`](DECISIONS.md): technical decision log for the defense.
- [`docs/DEMO_RECORDING_GUIDE.md`](docs/DEMO_RECORDING_GUIDE.md): exact recording,
  preflight, optional OpenAI/Yuno coverage, and Telegram boundaries.
- [`.env.example`](.env.example): safe configuration template with empty secret
  fields and external delivery disabled by default.
- [`start_demo.ps1`](start_demo.ps1): Windows launcher for the three local demo
  surfaces.

## Main API paths

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Backend readiness |
| `POST` | `/monitor/tick` | Advance one real simulated window |
| `GET` | `/monitor/latest-batch` | Latest transactions used by dashboard KPIs |
| `POST` | `/monitor/reset` | Clean simulator/detector/RCA/live lifecycle |
| `POST` | `/injections` | Activate a judge-controlled simulator change |
| `GET` | `/merchants/{merchant}/incidents` | Merchant-scoped diagnosed incidents in backend priority order |
| `POST` | `/remediation/approvals` | Record a human approval or rejection |
| `GET` | `/remediation/workflows/{recommendation_id}` | Read the human-gated workflow state |
| `POST` | `/remediation/changes` | Activate a local dry-run change after approval |
| `GET` | `/remediation/changes/{change_id}` | Read before/after monitoring metrics |
| `POST` | `/remediation/changes/{change_id}/rollback` | Revert the local simulated change |
| `POST` | `/remediation/changes/{change_id}/complete` | Complete the simulated review |
| `GET` | `/remediation/audit` | Read the append-only in-memory audit trail |

The legacy `/analyze` starter route remains for compatibility; it is not the
Control Tower demo path.
