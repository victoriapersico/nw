"""FastAPI entry point. Run with: uvicorn backend.main:app --reload"""

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from backend.agent import AgentError, analyze as run_analysis
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


app = FastAPI(
    title="NextWave Payment Control Tower API",
    description="Live payment monitoring, incident diagnosis, and recommendations.",
    version="0.1.0",
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