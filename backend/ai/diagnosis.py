"""Mock and OpenAI narration over deterministic RCA diagnoses."""

from __future__ import annotations

import re
from typing import get_args

from openai import APIError, OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.ai.prompts import NARRATION_INSTRUCTIONS, build_evidence_input
from backend.config import settings
from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    Diagnosis,
    NarrativeLanguage,
    NarrativeTone,
    PaymentMethod,
    Provider,
)


_KNOWN_EVIDENCE_VALUES = frozenset(
    (*get_args(Provider), *get_args(PaymentMethod))
).union(*COUNTRY_ISSUING_BANKS.values())
_UNSUPPORTED_ASSERTIONS = (
    "global outage",
    "confirmed outage",
    "fully resolved",
    "will recover",
    "caída global",
    "interrupción confirmada",
    "totalmente resuelto",
    "se recuperará",
)


class DiagnosisNarrationError(RuntimeError):
    """Raised when the optional OpenAI narration cannot produce valid output."""


class _EvidenceBoundStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(min_length=1)


class _NarrativeResponse(BaseModel):
    """The only fields the language model is allowed to author."""

    model_config = ConfigDict(extra="forbid")

    operator_summary: _EvidenceBoundStatement
    executive_one_liner: _EvidenceBoundStatement
    recommended_action: _EvidenceBoundStatement


def _validate_evidence_bindings(
    narrative: _NarrativeResponse,
    diagnosis: Diagnosis,
) -> None:
    """Reject missing, unknown, or mismatched citations from model output."""

    evidence_by_id = {
        f"evidence-{index}": item
        for index, item in enumerate(diagnosis.evidence, start=1)
    }
    for statement in (
        narrative.operator_summary,
        narrative.executive_one_liner,
        narrative.recommended_action,
    ):
        for evidence_id in statement.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise DiagnosisNarrationError(
                    "OpenAI cited evidence that was not supplied."
                )
            if evidence.value.casefold() not in statement.text.casefold():
                raise DiagnosisNarrationError(
                    "OpenAI returned a claim that does not match its citation."
                )
        supplied_values = {item.value.casefold() for item in diagnosis.evidence}
        unsupported_values = {
            value
            for value in _KNOWN_EVIDENCE_VALUES
            if value.casefold() in statement.text.casefold()
            and value.casefold() not in supplied_values
        }
        if unsupported_values or any(
            phrase in statement.text.casefold()
            for phrase in _UNSUPPORTED_ASSERTIONS
        ):
            raise DiagnosisNarrationError(
                "OpenAI returned an unsupported factual claim."
            )
        supplied_decline_codes = {
            item.value
            for item in diagnosis.evidence
            if item.dimension == "decline_code"
        }
        mentioned_decline_codes = set(
            re.findall(
                r"(?:decline code|código de rechazo)\s+([0-9]{2})",
                statement.text.casefold(),
            )
        )
        if not mentioned_decline_codes.issubset(supplied_decline_codes):
            raise DiagnosisNarrationError(
                "OpenAI returned an unsupported decline code."
            )


def _mock_narrative(
    diagnosis: Diagnosis,
    *,
    language: NarrativeLanguage,
    tone: NarrativeTone,
) -> _NarrativeResponse:
    """Produce deterministic, evidence-bound wording without an API call."""

    if diagnosis.diagnosis_status == "insufficient_evidence":
        if language == "es":
            summary = "El incidente está confirmado, pero la evidencia disponible no permite aislar una causa raíz."
            executive = "Incidente de aprobación confirmado; la causa raíz sigue bajo investigación."
            action = "Monitorear más ventanas y recopilar evidencia antes de escalar o cambiar el enrutamiento."
        else:
            summary = "The incident is confirmed, but the available evidence does not isolate one supported root cause."
            executive = "Approval incident confirmed; root cause remains under investigation."
            action = "Monitor additional windows and collect more evidence before escalating or changing payment routing."
        citation_ids = [
            f"evidence-{index}"
            for index in range(1, len(diagnosis.evidence) + 1)
        ]

        def statement(text: str) -> _EvidenceBoundStatement:
            if citation_ids:
                return _EvidenceBoundStatement(text=text, evidence_ids=citation_ids)
            # Some abstentions contain no observed evidence at all. They never
            # cross the model boundary, so an empty citation set is explicit.
            return _EvidenceBoundStatement.model_construct(
                text=text,
                evidence_ids=[],
            )

        return _NarrativeResponse(
            operator_summary=statement(summary),
            executive_one_liner=statement(executive),
            recommended_action=statement(action),
        )

    supported_evidence = [
        (index, item)
        for index, item in enumerate(diagnosis.evidence, start=1)
        if item.dimension in diagnosis.root_cause_dimensions
    ]
    if not supported_evidence:
        supported_evidence = list(enumerate(diagnosis.evidence, start=1))

    labels = ", ".join(item.value for _, item in supported_evidence)
    dimensions = ", ".join(diagnosis.root_cause_dimensions)
    if "provider" in diagnosis.root_cause_dimensions:
        action = f"Escalate to {labels} and monitor the affected payment slice."
    elif "issuing_bank" in diagnosis.root_cause_dimensions:
        action = f"Escalate to {labels} and monitor the affected payment slice."
    elif "decline_code" in diagnosis.root_cause_dimensions:
        action = f"Review decline code {labels} and monitor the affected payment slice."
    else:
        action = f"Investigate the affected {labels} payment slice and continue monitoring."

    citation_ids = [f"evidence-{index}" for index, _ in supported_evidence]
    metric_details = "; ".join(
        (
            f"{item.value} approval moved from {item.baseline_metric:.1%} "
            f"to {item.live_metric:.1%} across {item.sample_size} transactions"
        )
        for _, item in supported_evidence
    )
    if language == "es":
        metric_details = "; ".join(
            (
                f"la aprobación de {item.value} pasó de "
                f"{item.baseline_metric:.1%} a {item.live_metric:.1%} "
                f"en {item.sample_size} transacciones"
            )
            for _, item in supported_evidence
        )
        explanation = (
            f"El RCA determinístico confirma degradación en {dimensions}: "
            f"{metric_details}. La confianza del diagnóstico es "
            f"{diagnosis.confidence:.0%}."
        )
        executive = f"La degradación de aprobaciones está concentrada en {labels}."
        if "provider" in diagnosis.root_cause_dimensions or "issuing_bank" in diagnosis.root_cause_dimensions:
            action = f"Escalar a {labels} y monitorear el segmento de pagos afectado."
        elif "decline_code" in diagnosis.root_cause_dimensions:
            action = f"Revisar el código de rechazo {labels} y monitorear el segmento afectado."
        else:
            action = f"Investigar el segmento de pagos {labels} y continuar el monitoreo."
    else:
        explanation = (
            f"Deterministic RCA confirms degradation in {dimensions}: "
            f"{metric_details}. Diagnosis confidence is {diagnosis.confidence:.0%}."
        )
        executive = f"Approval degradation is concentrated in {labels}."
    if tone == "executive":
        explanation = executive
    return _NarrativeResponse(
        operator_summary=_EvidenceBoundStatement(text=explanation, evidence_ids=citation_ids),
        executive_one_liner=_EvidenceBoundStatement(text=executive, evidence_ids=citation_ids),
        recommended_action=_EvidenceBoundStatement(text=action, evidence_ids=citation_ids),
    )


def _openai_narrative(
    diagnosis: Diagnosis,
    *,
    language: NarrativeLanguage,
    tone: NarrativeTone,
) -> _NarrativeResponse:
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
            input=build_evidence_input(diagnosis, language=language, tone=tone),
            text_format=_NarrativeResponse,
        )
    except APIError as exc:
        raise DiagnosisNarrationError(f"OpenAI API request failed: {exc}") from exc
    except ValidationError as exc:
        raise DiagnosisNarrationError("OpenAI returned an invalid narrative.") from exc

    parsed = response.output_parsed
    if parsed is None:
        raise DiagnosisNarrationError("OpenAI returned no structured narrative.")
    _validate_evidence_bindings(parsed, diagnosis)
    return parsed


def narrate_diagnosis(
    diagnosis: Diagnosis,
    *,
    mock_mode: bool | None = None,
    language: NarrativeLanguage = "en",
    tone: NarrativeTone = "operations",
) -> Diagnosis:
    """Enrich wording only; deterministic RCA facts always remain unchanged."""

    use_mock = settings.mock_mode if mock_mode is None else mock_mode
    if use_mock or diagnosis.diagnosis_status == "insufficient_evidence":
        narrative = _mock_narrative(diagnosis, language=language, tone=tone)
    else:
        try:
            narrative = _openai_narrative(diagnosis, language=language, tone=tone)
        except Exception:
            # Narration is optional: an API outage or unsafe response must never
            # break incident delivery.
            narrative = _mock_narrative(diagnosis, language=language, tone=tone)
    citations = list(dict.fromkeys(
        evidence_id
        for statement in (
            narrative.operator_summary,
            narrative.executive_one_liner,
            narrative.recommended_action,
        )
        for evidence_id in statement.evidence_ids
    ))
    return diagnosis.model_copy(
        update={
            "explanation": narrative.operator_summary.text,
            "executive_summary": narrative.executive_one_liner.text,
            "recommended_action": narrative.recommended_action.text,
            "evidence_citations": citations,
        }
    )
