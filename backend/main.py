"""FastAPI entry point. Run with: uvicorn backend.main:app --reload"""

from fastapi import FastAPI, HTTPException

from backend.agent import AgentError, analyze as run_analysis
from backend.schemas import AnalysisRequest, AnalysisResponse, HealthResponse
from backend.tools import RecordNotFoundError


app = FastAPI(
    title="NextWave Practice Starter API",
    description="Minimal backend for rapidly adapting an AI hackathon demo.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/analyze", response_model=AnalysisResponse)
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    try:
        return run_analysis(request)
    except RecordNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
