"""FastAPI entry point. Run with: uvicorn backend.main:app --reload"""

from contextlib import asynccontextmanager
from functools import lru_cache
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request

from backend.agent import AgentError, analyze as run_analysis
from backend.email_mock import MockEmailMessage, MockEmailOutbox
from backend.live_control_tower import LiveControlTower, build_live_control_tower
from backend.schemas import (
    ApprovalDecision,
    AnalysisRequest,
    AnalysisResponse,
    CreateInjectionRequest,
    CreateInjectionResponse,
    ExecutionRequest,
    ExecutionResult,
    HealthResponse,
    LiveTickResponse,
    Merchant,
    MerchantMonitoringResponse,
    MerchantIncidentsResponse,
    RoutingRecommendation,
    SimulationRequest,
    TransactionBatch,
)
from backend.tools import RecordNotFoundError
from backend.yuno_mock import (
    MOCK_ACCOUNT_MERCHANTS,
    MockYunoSystemAlert,
    MockYunoSystemAlertOutbox,
    MockYunoApiEvent,
    MockYunoApiHealth,
    MockYunoApiTelemetry,
    MockYunoWebhookIngestor,
    MockYunoWebhookReceipt,
    YunoMockWebhookError,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load local history before the UI starts polling."""

    get_control_tower()
    yield


app = FastAPI(
    title="NextWave Payment Control Tower API",
    description="Live payment monitoring, incident diagnosis, and recommendations.",
    version="0.1.0",
    lifespan=lifespan,
)

mock_yuno_ingestor = MockYunoWebhookIngestor()
mock_yuno_system_alert_outbox = MockYunoSystemAlertOutbox()
mock_yuno_email_outbox = MockEmailOutbox()
mock_yuno_api_telemetry = MockYunoApiTelemetry()


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

    started_at = perf_counter()
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="webhook payload must be an object")
    source_event_id = str(payload.get("idempotency_key", "unidentified-request"))
    try:
        ingested = mock_yuno_ingestor.ingest(
            payload,
            request.headers.get("x-hmac-signature"),
        )
    except YunoMockWebhookError as exc:
        if not exc.trusted:
            mock_yuno_api_telemetry.record(
                source_event_id=source_event_id,
                account_id=None,
                outcome="unauthorized",
                latency_ms=(perf_counter() - started_at) * 1000,
                error_code=exc.error_code,
            )
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        account_id = str(payload.get("account_id", ""))
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
        mock_yuno_api_telemetry.record(
            source_event_id=source_event_id,
            account_id=account_id if account_id in MOCK_ACCOUNT_MERCHANTS else None,
            outcome="duplicate" if alert is None else "rejected",
            latency_ms=(perf_counter() - started_at) * 1000,
            error_code=exc.error_code,
        )
        return MockYunoWebhookReceipt(
            event_id=source_event_id,
            accepted=False,
            duplicate=alert is None,
            error_code=exc.error_code,
        )

    mock_yuno_api_telemetry.record(
        source_event_id=source_event_id,
        account_id=str(payload.get("account_id", "")) or None,
        outcome="duplicate" if ingested.duplicate else "accepted",
        latency_ms=(perf_counter() - started_at) * 1000,
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


@app.get(
    "/v1/sandbox/yuno-api-health",
    response_model=MockYunoApiHealth,
)
def mock_yuno_api_health() -> MockYunoApiHealth:
    """Return safe API-manager health aggregates for the local Yuno sandbox."""

    return mock_yuno_api_telemetry.health_for()


@app.post(
    "/v1/sandbox/yuno-api-demo-seed",
    response_model=MockYunoApiHealth,
)
def seed_mock_yuno_api_baseline() -> MockYunoApiHealth:
    """Load a small healthy sandbox baseline for the Yuno API Manager demo."""

    return mock_yuno_api_telemetry.seed_healthy_baseline()


@app.get(
    "/v1/sandbox/yuno-api-log",
    response_model=list[MockYunoApiEvent],
)
def mock_yuno_api_log() -> list[MockYunoApiEvent]:
    """Return the sandbox API activity log, newest record first."""

    return list(mock_yuno_api_telemetry.events_for())


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


@app.post("/monitor/reset", response_model=HealthResponse)
def reset_monitoring() -> HealthResponse:
    """Restore the deterministic live demo to its clean initial state."""

    try:
        get_control_tower().reset()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return HealthResponse(status="ok")


@app.get("/monitor/latest-batch", response_model=TransactionBatch)
def latest_monitoring_batch() -> TransactionBatch:
    """Expose the most recent simulator batch for real dashboard metrics."""

    try:
        batch = get_control_tower().latest_batch()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail="No monitoring batch is available; advance the monitor first.",
        )
    return batch


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


@app.post("/remediation/simulations", response_model=RoutingRecommendation)
def simulate_remediation(request: SimulationRequest) -> RoutingRecommendation:
    """Return a new dry-run recommendation for an existing active incident."""

    try:
        return get_control_tower().simulate_remediation(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {exc.args[0]}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/remediation/approvals", response_model=ApprovalDecision)
def record_remediation_approval(decision: ApprovalDecision) -> ApprovalDecision:
    """Record a human approval or rejection; it never executes routing."""

    try:
        return get_control_tower().record_approval(decision)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Unknown recommendation: {exc.args[0]}"
        ) from exc


@app.post("/remediation/executions", response_model=ExecutionResult)
def request_remediation_execution(request: ExecutionRequest) -> ExecutionResult:
    """Safe contract endpoint: only dry-runs are possible in POST-01."""

    return get_control_tower().request_execution(request)


@app.get(
    "/merchants/{merchant}/monitoring",
    response_model=MerchantMonitoringResponse,
)
def merchant_monitoring(merchant: Merchant) -> MerchantMonitoringResponse:
    """Return actual approval metrics from the latest simulated live window."""

    try:
        return get_control_tower().monitoring_for(merchant)
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
    ExecutionRequest,
    ExecutionResult,
