"""FastAPI entry point. Run with: uvicorn backend.main:app --reload"""

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, HTTPException

from backend.agent import AgentError, analyze as run_analysis
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
    RemediationAuditEvent,
    SimulatedChangeRequest,
    SimulatedChangeCompletionRequest,
    SimulatedChangeRollbackRequest,
    SimulatedRoutingChange,
    RoutingWorkflow,
    SimulationRequest,
    TransactionBatch,
)
from backend.tools import RecordNotFoundError


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


@lru_cache(maxsize=1)
def get_control_tower() -> LiveControlTower:
    """Build the demo runtime once per API process."""

    return build_live_control_tower()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


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


@app.post("/remediation/changes", response_model=SimulatedRoutingChange)
def apply_simulated_remediation_change(
    request: SimulatedChangeRequest,
) -> SimulatedRoutingChange:
    """Apply an approved route recommendation in demo state only."""

    try:
        return get_control_tower().apply_simulated_change(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown recommendation: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/remediation/changes/{change_id}", response_model=SimulatedRoutingChange)
def get_simulated_remediation_change(change_id: str) -> SimulatedRoutingChange:
    try:
        return get_control_tower().simulated_change(change_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown change: {exc.args[0]}") from exc


@app.get(
    "/remediation/workflows/{recommendation_id}",
    response_model=RoutingWorkflow,
)
def get_remediation_workflow(recommendation_id: str) -> RoutingWorkflow:
    """Show the current human-approved workflow state for one recommendation."""

    try:
        return get_control_tower().workflow(recommendation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown recommendation: {exc.args[0]}") from exc


@app.post(
    "/remediation/changes/{change_id}/rollback",
    response_model=SimulatedRoutingChange,
)
def rollback_simulated_remediation_change(
    change_id: str, request: SimulatedChangeRollbackRequest
) -> SimulatedRoutingChange:
    try:
        return get_control_tower().rollback_simulated_change(change_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown change: {exc.args[0]}") from exc


@app.post(
    "/remediation/changes/{change_id}/complete",
    response_model=SimulatedRoutingChange,
)
def complete_simulated_remediation_change(
    change_id: str, request: SimulatedChangeCompletionRequest
) -> SimulatedRoutingChange:
    """Close a healthy simulated rollout after a human review."""

    try:
        return get_control_tower().complete_simulated_change(change_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown change: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/remediation/audit", response_model=list[RemediationAuditEvent])
def remediation_audit(recommendation_id: str | None = None) -> list[RemediationAuditEvent]:
    """Expose the local audit trail for the human-approved demo workflow."""

    return get_control_tower().remediation_audit(recommendation_id)


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
