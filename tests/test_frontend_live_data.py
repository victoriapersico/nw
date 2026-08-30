from datetime import datetime, timedelta, timezone

from frontend.live_data import build_merchant_snapshot, diagnosis_presentation
from backend.schemas import DiagnosedIncident, Diagnosis, Incident, Transaction, TransactionBatch


START = datetime(2025, 9, 2, 13, tzinfo=timezone.utc)


def transaction(sequence: int, country: str, status: str) -> Transaction:
    return Transaction(
        transaction_id=f"ui-{sequence}",
        merchant="Rappi",
        provider="Stripe",
        payment_method={"Mexico": "CARD", "Brazil": "PIX", "Colombia": "PSE"}[country],
        country=country,
        issuing_bank={"Mexico": "Banorte", "Brazil": "Itaú", "Colombia": "Bancolombia"}[country],
        decline_code=None if status == "approved" else "91",
        status=status,
        amount=100.0,
        timestamp=START + timedelta(seconds=sequence),
    )


def active_incident() -> DiagnosedIncident:
    incident = Incident(
        incident_id="inc-ui",
        merchant="Rappi",
        country="Brazil",
        detected_at=START + timedelta(minutes=5),
        expected_conversion=0.9,
        actual_conversion=0.5,
        conversion_drop_pp=40.0,
        affected_volume=2,
        estimated_loss=50.0,
        estimated_loss_per_hour=600.0,
        severity="critical",
        anomaly_score=5.0,
    )
    return DiagnosedIncident(
        incident=incident,
        diagnosis=Diagnosis(
            incident_id=incident.incident_id,
            diagnosis_status="insufficient_evidence",
            confidence=0.4,
            explanation="Not enough evidence.",
            recommended_action="Collect another window.",
        ),
    )


def test_snapshot_metrics_come_directly_from_batch_transactions() -> None:
    batch = TransactionBatch(
        window_start=START,
        window_end=START + timedelta(minutes=5),
        transactions=[
            transaction(1, "Brazil", "approved"),
            transaction(2, "Brazil", "declined"),
            transaction(3, "Mexico", "approved"),
            transaction(4, "Colombia", "declined"),
        ],
    )

    snapshot = build_merchant_snapshot(batch, "Rappi", [active_incident()])

    assert snapshot.transaction_count == 4
    assert snapshot.approval_rate == 0.5
    assert snapshot.countries["Brazil"].transaction_count == 2
    assert snapshot.countries["Brazil"].approval_rate == 0.5
    assert snapshot.countries["Brazil"].status == "Critical"
    assert snapshot.countries["Mexico"].status == "No active incident"
    assert [item.transaction_id for item in snapshot.recent_transactions] == [
        "ui-4",
        "ui-3",
        "ui-2",
        "ui-1",
    ]


def test_confirmed_diagnosis_is_labeled_as_confirmed_root_cause() -> None:
    presentation = diagnosis_presentation("confirmed")

    assert presentation.heading == "Confirmed root cause"
    assert presentation.evidence_heading == "Confirmed supporting evidence"


def test_abstention_never_labels_candidate_evidence_as_root_cause() -> None:
    presentation = diagnosis_presentation("insufficient_evidence")

    assert presentation.heading == "Insufficient evidence to isolate a single root cause."
    assert (
        presentation.evidence_heading
        == "Observed evidence — not sufficient for confirmation"
    )
    assert "root cause" not in presentation.evidence_heading.lower()
