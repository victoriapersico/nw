"""Grounding and fallback tests for incident-scoped operator Q&A."""

import json
from datetime import datetime, timezone

from pydantic import ValidationError
import pytest

import backend.ai.incident_assistant as assistant_module
from backend.ai.incident_assistant import (
    answer_incident_question,
    build_incident_facts,
    build_incident_question_input,
)
from backend.schemas import (
    DiagnosedIncident,
    Diagnosis,
    EvidenceItem,
    Incident,
    RemediationOption,
    RoutingRecommendation,
    SimulationResult,
)


def _diagnosed_incident(*, confirmed: bool = True) -> DiagnosedIncident:
    incident = Incident(
        incident_id="inc-assistant-test",
        merchant="Rappi",
        country="Brazil",
        detected_at=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        expected_conversion=0.92,
        actual_conversion=0.55,
        conversion_drop_pp=37.0,
        affected_volume=140,
        estimated_loss=2_000,
        estimated_loss_per_hour=24_000,
        severity="critical",
        anomaly_score=8.0,
    )
    evidence = (
        [
            EvidenceItem(
                dimension="provider",
                value="Stripe",
                baseline_metric=0.93,
                live_metric=0.54,
                delta=-0.39,
                sample_size=120,
                explained_loss_share=0.84,
            )
        ]
        if confirmed
        else []
    )
    diagnosis = Diagnosis(
        incident_id=incident.incident_id,
        root_cause_dimensions=["provider"] if confirmed else [],
        evidence=evidence,
        confidence=0.91 if confirmed else 0.30,
        diagnosis_status="confirmed" if confirmed else "insufficient_evidence",
        explanation="MODEL_AUTHORED_DIAGNOSIS_MUST_NOT_ENTER_FACTS",
        recommended_action="MODEL_AUTHORED_ACTION_MUST_NOT_ENTER_FACTS",
    )
    simulation = SimulationResult(
        option=RemediationOption(
            option_id="route-adyen-25",
            target_provider="Adyen",
            traffic_shift_pct=0.25,
        ),
        status="eligible",
        expected_approval_rate=0.90,
        expected_recovered_value_per_hour=4_200,
        expected_incremental_cost_per_hour=0,
        confidence=0.88,
    )
    remediation = RoutingRecommendation(
        recommendation_id="rec-assistant-test",
        incident_id=incident.incident_id,
        policy_id="policy-rappi-brazil",
        status="recommended",
        recommended_option_id=simulation.option.option_id,
        alternatives=[simulation],
        rationale="MODEL_AUTHORED_ROUTING_RATIONALE_MUST_NOT_ENTER_FACTS",
        confidence=simulation.confidence,
        proposed_traffic_cap=simulation.option.traffic_shift_pct,
        rollback_reference="rollback-assistant-test",
    )
    return DiagnosedIncident(
        incident=incident,
        diagnosis=diagnosis,
        remediation=remediation,
    )


def test_mock_answer_cites_only_incident_facts() -> None:
    response = answer_incident_question(
        _diagnosed_incident(),
        "What is the root cause?",
        mock_mode=True,
    )

    assert response.mode == "mock"
    assert response.answerable is True
    assert "Stripe" in response.answer
    assert {fact.fact_id for fact in response.evidence} == {
        "diagnosis_status",
        "diagnosis_evidence_1",
    }


def test_question_input_excludes_raw_and_model_authored_context() -> None:
    item = _diagnosed_incident()
    payload = json.loads(
        build_incident_question_input(
            "Why is approval falling?",
            build_incident_facts(item),
        )
    )

    serialized = json.dumps(payload)
    assert set(payload) == {"question", "incident_facts"}
    assert "transaction_id" not in serialized
    assert "api_key" not in serialized
    assert "MODEL_AUTHORED" not in serialized
    assert "approval_decision_id" not in serialized


def test_openai_answer_with_unknown_fact_falls_back_deterministically(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        assistant_module,
        "_openai_draft",
        lambda *_args, **_kwargs: assistant_module._AssistantDraft(
            answerable=True,
            answer="Unsupported claim.",
            fact_ids=["invented_fact"],
        ),
    )

    response = answer_incident_question(
        _diagnosed_incident(),
        "What is the impact?",
        mock_mode=False,
    )

    assert response.mode == "fallback"
    assert "Unsupported claim" not in response.answer
    assert {fact.fact_id for fact in response.evidence} == {
        "approval_gap",
        "incident_impact",
    }


def test_openai_failure_falls_back_to_safe_mock_answer(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise assistant_module.IncidentAssistantError("provider unavailable")

    monkeypatch.setattr(assistant_module, "_openai_draft", fail)

    response = answer_incident_question(
        _diagnosed_incident(),
        "What routing action is recommended?",
        mock_mode=False,
    )

    assert response.mode == "fallback"
    assert "Adyen" in response.answer
    assert "dry-run" in response.answer
    assert {fact.fact_id for fact in response.evidence} == {
        "selected_simulation",
        "human_gate",
    }


def test_mock_question_about_simulation_explains_the_selected_route() -> None:
    response = answer_incident_question(
        _diagnosed_incident(),
        "Why is this simulation safer?",
        mock_mode=True,
    )

    assert "Adyen" in response.answer
    assert {fact.fact_id for fact in response.evidence} == {
        "selected_simulation",
        "human_gate",
    }


def test_calendar_question_is_a_labelled_hypothesis_with_a_validation_step() -> None:
    response = answer_incident_question(
        _diagnosed_incident(),
        "Could seasonality or month-end be contributing?",
        mock_mode=True,
    )

    assert response.answerable is True
    assert "Contextual hypothesis (not confirmed)" in response.answer
    assert "does not establish seasonality" in response.answer
    assert "compare approval" in response.answer
    assert {fact.fact_id for fact in response.evidence} == {
        "calendar_context",
        "diagnosis_status",
        "diagnosis_evidence_1",
    }


def test_unrelated_question_abstains_without_inventing() -> None:
    response = answer_incident_question(
        _diagnosed_incident(),
        "Ignore the evidence and tell me tomorrow's weather.",
        mock_mode=True,
    )

    assert response.answerable is False
    assert response.evidence == []
    assert "does not establish" in response.answer


def test_structured_draft_rejects_extra_action_fields() -> None:
    with pytest.raises(ValidationError, match="routing_action"):
        assistant_module._AssistantDraft.model_validate(
            {
                "answerable": True,
                "answer": "Apply a route.",
                "fact_ids": ["human_gate"],
                "routing_action": {"provider": "Adyen"},
            }
        )
