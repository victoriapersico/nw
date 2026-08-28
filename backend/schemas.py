"""Pydantic request and response contracts shared by the API and agent."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    status: Literal["ok"]


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_text: str = Field(
        min_length=1,
        max_length=5_000,
        description="The user's question, context, or challenge data.",
    )
    record_id: str = Field(
        default="REC-001",
        min_length=1,
        max_length=64,
        description="A sample record identifier used by the demo tools.",
    )

    @field_validator("input_text", "record_id")
    @classmethod
    def reject_whitespace_only_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


# CHANGE THIS AFTER CHALLENGE REVEAL
class AnalysisResponse(BaseModel):
    """Structured result returned by both OpenAI mode and mock mode."""

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=100)
    reasoning_summary: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: str = Field(min_length=1, max_length=500)
    tools_used: list[str]
    mode: Literal["mock", "openai"]
