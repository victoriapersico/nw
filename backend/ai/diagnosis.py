"""Mock and OpenAI narration over deterministic RCA diagnoses."""

from __future__ import annotations

from openai import (
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
    OpenAIError,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.ai.prompts import NARRATION_INSTRUCTIONS, build_evidence_input
from backend.config import settings
from backend.schemas import Diagnosis


class DiagnosisNarrationError(RuntimeError):
    """Raised when the optional OpenAI narration cannot produce valid output."""


class _NarrativeResponse(BaseModel):
    """The only fields the language model is allowed to author."""

    model_config = ConfigDict(extra="forbid")

    explanation: str = Field(min_length=1, max_length=2_000)
    recommended_action: str = Field(min_length=1, max_length=1_000)


def _mock_narrative(diagnosis: Diagnosis) -> _NarrativeResponse:
    """Produce deterministic, evidence-bound wording without an API call."""

    if diagnosis.diagnosis_status == "insufficient_evidence":
        return _NarrativeResponse(
            explanation=(
                "The incident is confirmed, but the available deterministic "
                "evidence does not isolate one supported root cause."
            ),
            recommended_action=(
                "Monitor additional windows and collect more evidence before "
                "escalating or changing payment routing."
            ),
        )

    labels = ", ".join(item.value for item in diagnosis.evidence)
    dimensions = ", ".join(diagnosis.root_cause_dimensions)
    if "provider" in diagnosis.root_cause_dimensions:
        action = "Escalate to the affected provider and monitor the affected slice."
    elif "issuing_bank" in diagnosis.root_cause_dimensions:
        action = "Escalate to the affected issuing bank and monitor the affected slice."
    elif "decline_code" in diagnosis.root_cause_dimensions:
        action = "Review the decline-code concentration and monitor the affected slice."
    else:
        action = "Investigate the affected payment route and monitor the affected slice."

    return _NarrativeResponse(
        explanation=(
            f"Deterministic RCA found supported degradation in {dimensions}: "
            f"{labels}. Confidence is {diagnosis.confidence:.0%}."
        ),
        recommended_action=action,
    )


def _openai_narrative(diagnosis: Diagnosis) -> _NarrativeResponse:
    """Use Structured Outputs while preserving all deterministic fields locally."""

    if settings.openai_api_key is None:
        raise DiagnosisNarrationError("OPENAI_API_KEY is missing; use Mock Mode.")

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=1,
    )
    try:
        response = client.responses.parse(
            model=settings.openai_model,
            instructions=NARRATION_INSTRUCTIONS,
            input=build_evidence_input(diagnosis),
            text_format=_NarrativeResponse,
            store=False,
        )
    except (
        OpenAIError,
        ContentFilterFinishReasonError,
        LengthFinishReasonError,
        ValidationError,
    ) as exc:
        raise DiagnosisNarrationError(
            "OpenAI could not return a valid diagnosis narrative."
        ) from exc

    parsed = response.output_parsed
    if parsed is None:
        raise DiagnosisNarrationError("OpenAI returned no structured narrative.")
    return parsed


def narrate_diagnosis(
    diagnosis: Diagnosis,
    *,
    mock_mode: bool | None = None,
) -> Diagnosis:
    """Enrich wording only; deterministic RCA facts always remain unchanged."""

    use_mock = settings.mock_mode if mock_mode is None else mock_mode
    if use_mock or diagnosis.diagnosis_status == "insufficient_evidence":
        narrative = _mock_narrative(diagnosis)
    else:
        try:
            narrative = _openai_narrative(diagnosis)
        except Exception:
            # Narration is optional. Preserve the incident and fall back to the
            # same deterministic evidence-bound wording used in Mock Mode.
            narrative = _mock_narrative(diagnosis)
    return diagnosis.model_copy(
        update={
            "explanation": narrative.explanation,
            "recommended_action": narrative.recommended_action,
        }
    )
