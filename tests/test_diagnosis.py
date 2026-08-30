import json
from dataclasses import replace

import backend.ai.diagnosis as diagnosis_module
from backend.ai.diagnosis import narrate_diagnosis
from backend.ai.prompts import build_evidence_input
from backend.schemas import Diagnosis, EvidenceItem


def make_diagnosis(status: str = "confirmed") -> Diagnosis:
    evidence = [
        EvidenceItem(
            dimension="provider",
            value="Stripe",
            baseline_metric=0.93,
            live_metric=0.55,
            delta=-0.38,
            sample_size=140,
            explained_loss_share=0.82,
        )
    ]
    return Diagnosis(
        incident_id="inc-rappi-brazil",
        root_cause_dimensions=["provider"] if status == "confirmed" else [],
        evidence=evidence if status == "confirmed" else [],
        confidence=0.92 if status == "confirmed" else 0.40,
        diagnosis_status=status,
        explanation="Deterministic RCA output.",
        recommended_action="Investigate the affected payment route.",
    )


def test_mock_narration_preserves_deterministic_evidence() -> None:
    deterministic = make_diagnosis()

    narrated = narrate_diagnosis(deterministic, mock_mode=True)

    assert narrated.incident_id == deterministic.incident_id
    assert narrated.evidence == deterministic.evidence
    assert narrated.root_cause_dimensions == deterministic.root_cause_dimensions
    assert narrated.confidence == deterministic.confidence
    assert narrated.diagnosis_status == deterministic.diagnosis_status
    assert "Stripe" in narrated.explanation
    assert "Stripe" in narrated.recommended_action
    assert "Stripe" in narrated.executive_summary
    assert "Rappi" not in narrated.executive_summary
    assert "93.0%" in narrated.explanation
    assert "55.0%" in narrated.explanation
    assert "140 transactions" in narrated.explanation
    assert narrated.evidence_citations == ["evidence-1"]


def test_insufficient_evidence_abstains_without_openai(monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("OpenAI must not run for insufficient evidence")

    monkeypatch.setattr(diagnosis_module, "OpenAI", fail_if_called)

    narrated = narrate_diagnosis(
        make_diagnosis("insufficient_evidence"),
        mock_mode=False,
    )

    assert narrated.diagnosis_status == "insufficient_evidence"
    assert "does not isolate" in narrated.explanation
    assert "more evidence" in narrated.recommended_action
    assert narrated.evidence_citations == []


def test_abstention_cites_observed_evidence_without_claiming_a_cause() -> None:
    diagnosis = make_diagnosis().model_copy(
        update={
            "diagnosis_status": "insufficient_evidence",
            "root_cause_dimensions": [],
        }
    )

    narrated = narrate_diagnosis(diagnosis, mock_mode=False)

    assert "under investigation" in narrated.executive_summary
    assert narrated.root_cause_dimensions == []
    assert narrated.evidence == diagnosis.evidence
    assert narrated.evidence_citations == ["evidence-1"]


def test_evidence_prompt_excludes_raw_transactions() -> None:
    prompt = build_evidence_input(make_diagnosis())
    payload = json.loads(prompt)

    assert "Stripe" in prompt
    assert "raw_transactions" not in prompt
    assert "transaction_id" not in prompt
    assert "InjectionConfig" not in prompt
    assert set(payload) == {
        "incident_id",
        "diagnosis_status",
        "language",
        "tone",
        "root_cause_dimensions",
        "confidence",
        "deterministic_explanation",
        "deterministic_recommendation",
        "evidence",
    }
    assert set(payload["evidence"][0]) == {
        "evidence_id",
        "dimension",
        "value",
        "baseline_metric",
        "live_metric",
        "delta",
        "sample_size",
        "explained_loss_share",
    }


def test_prompt_carries_requested_language_and_tone() -> None:
    prompt = build_evidence_input(
        make_diagnosis(), language="es", tone="executive"
    )

    assert '"language": "es"' in prompt
    assert '"tone": "executive"' in prompt


def test_spanish_variant_is_deterministic_and_evidence_bound() -> None:
    narrated = narrate_diagnosis(make_diagnosis(), mock_mode=True, language="es")

    assert "degradaci" in narrated.executive_summary.lower()
    assert "Stripe" in narrated.executive_summary
    assert narrated.evidence_citations == ["evidence-1"]


def test_executive_tone_uses_the_short_summary_in_fallback() -> None:
    narrated = narrate_diagnosis(
        make_diagnosis(), mock_mode=True, tone="executive"
    )

    assert narrated.explanation == narrated.executive_summary


def test_openai_outage_returns_safe_mock_fallback(monkeypatch) -> None:
    def outage(*_args, **_kwargs):
        raise TimeoutError("simulated outage")

    monkeypatch.setattr(diagnosis_module, "_openai_narrative", outage)

    narrated = narrate_diagnosis(make_diagnosis(), mock_mode=False)

    assert "Stripe" in narrated.explanation
    assert narrated.evidence_citations == ["evidence-1"]


def test_unsupported_openai_citation_returns_safe_fallback(monkeypatch) -> None:
    def unsupported(*_args, **_kwargs):
        raise diagnosis_module.DiagnosisNarrationError(
            "OpenAI cited evidence that was not supplied."
        )

    monkeypatch.setattr(diagnosis_module, "_openai_narrative", unsupported)

    narrated = narrate_diagnosis(make_diagnosis(), mock_mode=False)

    assert narrated.evidence_citations == ["evidence-1"]
    assert "Stripe" in narrated.explanation


def test_openai_structured_output_regression(monkeypatch) -> None:
    class FakeResponses:
        def parse(self, **kwargs):
            statement = diagnosis_module._EvidenceBoundStatement
            parsed = diagnosis_module._NarrativeResponse(
                operator_summary=statement(
                    text="Stripe approval is below its supplied baseline.",
                    evidence_ids=["evidence-1"],
                ),
                executive_one_liner=statement(
                    text="Stripe is the evidence-backed affected slice.",
                    evidence_ids=["evidence-1"],
                ),
                recommended_action=statement(
                    text="Escalate to Stripe and monitor the affected slice.",
                    evidence_ids=["evidence-1"],
                ),
            )
            assert kwargs["text_format"] is diagnosis_module._NarrativeResponse
            return type("Response", (), {"output_parsed": parsed})()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr(diagnosis_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        diagnosis_module,
        "settings",
        replace(diagnosis_module.settings, openai_api_key="test-key"),
    )

    narrated = narrate_diagnosis(make_diagnosis(), mock_mode=False)

    assert narrated.explanation.startswith("Stripe approval")
    assert narrated.executive_summary.startswith("Stripe is")
    assert narrated.evidence_citations == ["evidence-1"]


def test_unsupported_entity_in_openai_output_uses_fallback(monkeypatch) -> None:
    statement = diagnosis_module._EvidenceBoundStatement
    unsafe = diagnosis_module._NarrativeResponse(
        operator_summary=statement(
            text="Stripe and Adyen have a global outage.",
            evidence_ids=["evidence-1"],
        ),
        executive_one_liner=statement(
            text="Stripe and Adyen are affected.", evidence_ids=["evidence-1"]
        ),
        recommended_action=statement(
            text="Escalate to Stripe.", evidence_ids=["evidence-1"]
        ),
    )

    def return_unsafe(*_args, **_kwargs):
        diagnosis_module._validate_evidence_bindings(unsafe, make_diagnosis())
        return unsafe

    monkeypatch.setattr(diagnosis_module, "_openai_narrative", return_unsafe)

    narrated = narrate_diagnosis(make_diagnosis(), mock_mode=False)

    assert "Adyen" not in narrated.explanation
    assert "Deterministic RCA" in narrated.explanation
