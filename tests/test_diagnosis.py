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
    assert "provider" in narrated.recommended_action.lower()


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


def test_evidence_prompt_excludes_raw_transactions() -> None:
    prompt = build_evidence_input(make_diagnosis())

    assert "Stripe" in prompt
    assert "raw_transactions" not in prompt
    assert "transaction_id" not in prompt
