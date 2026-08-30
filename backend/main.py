"""FastAPI entry point. Run with: uvicorn backend.main:app --reload"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request

from backend.agent import AgentError, analyze as run_analysis
from backend.email_mock import MockEmailMessage, MockEmailOutbox
from backend.live_control_tower import LiveControlTower, build_live_control_tower
from backend.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    CreateInjectionRequest,
    CreateInjectionResponse,
    HealthResponse,
    LiveTickResponse,
    Merchant,
    MerchantIncidentsResponse,
)
from backend.tools import RecordNotFoundError
from backend.yuno_mock import (
    MOCK_ACCOUNT_MERCHANTS,
    MockYunoSystemAlert,
    MockYunoSystemAlertOutbox,
    MockYunoWebhookIngestor,
    MockYunoWebhookReceipt,
    YunoMockWebhookError,
)


app = FastAPI(
    title="NextWave Payment Control Tower API",
    description="Live payment monitoring, incident diagnosis, and recommendations.",
    version="0.1.0",
)

mock_yuno_ingestor = MockYunoWebhookIngestor()
mock_yuno_system_alert_outbox = MockYunoSystemAlertOutbox()
mock_yuno_email_outbox = MockEmailOutbox()


@lru_cache(maxsize=1)
def get_control_tower() -> LiveControlTower:
    """Build the demo runtime once per API process."""

    return build_live_control_tower()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/v1/sandbox/yuno-webhooks",
    response_model=MockYunoWebhookReceipt,
)
async def receive_mock_yuno_webhook(request: Request) -> MockYunoWebhookReceipt:
    """Receive a signed local Yuno fixture; not a production integration endpoint."""

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="webhook payload must be an object")
    try:
        ingested = mock_yuno_ingestor.ingest(
            payload,
            request.headers.get("x-hmac-signature"),
        )
    except YunoMockWebhookError as exc:
        if not exc.trusted:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        account_id = str(payload.get("account_id", ""))
        source_event_id = str(payload.get("idempotency_key", "invalid-event"))
        alert = None
        if account_id in MOCK_ACCOUNT_MERCHANTS:
            alert = mock_yuno_system_alert_outbox.notify_failure(
                account_id=account_id,
                source_event_id=source_event_id,
                error_code=exc.error_code,
                field_path=exc.field_path,
                summary=(
                    "A signed Yuno sandbox payment webhook could not be normalized: "
                    f"{exc.error_code}."
                ),
            )
        if alert is not None:
            mock_yuno_email_outbox.send_yuno_system_alert(alert)
        return MockYunoWebhookReceipt(
            event_id=source_event_id,
            accepted=False,
            duplicate=alert is None,
            error_code=exc.error_code,
        )

    return MockYunoWebhookReceipt(
        event_id=ingested.event_id,
        accepted=True,
        duplicate=ingested.duplicate,
        transaction_id=(
            ingested.transaction.transaction_id if ingested.transaction else None
        ),
    )


@app.get(
    "/v1/sandbox/yuno-system-alerts/{account_id}",
    response_model=list[MockYunoSystemAlert],
)
def mock_yuno_system_alerts(account_id: str) -> list[MockYunoSystemAlert]:
    """Inspect the simulated operations alerts that would be sent to Yuno."""

    return list(mock_yuno_system_alert_outbox.alerts_for(account_id))


@app.get(
    "/v1/sandbox/yuno-email-outbox",
    response_model=list[MockEmailMessage],
)
def mock_yuno_email_messages() -> list[MockEmailMessage]:
    """Inspect rendered demo emails without sending an external message."""

    return list(mock_yuno_email_outbox.messages)


@app.post("/injections", response_model=CreateInjectionResponse)
def create_injection(
    request: CreateInjectionRequest,
) -> CreateInjectionResponse:
    """Apply a judge injection to future simulated transactions only."""

    try:
        injection_id = get_control_tower().inject(request.config)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return CreateInjectionResponse(
        injection_id=injection_id,
        status="active",
    )


@app.post("/monitor/tick", response_model=LiveTickResponse)
def advance_monitoring() -> LiveTickResponse:
    """Advance one accelerated five-minute monitoring window."""

    try:
        return get_control_tower().tick()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get(
    "/merchants/{merchant}/incidents",
    response_model=MerchantIncidentsResponse,
)
def merchant_incidents(merchant: Merchant) -> MerchantIncidentsResponse:
    """Return active incidents isolated to one merchant context."""

    try:
        return get_control_tower().incidents_for(merchant)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/analyze", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    """Legacy starter endpoint retained during the MVP transition."""

    try:
        return run_analysis(request)
    except RecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
