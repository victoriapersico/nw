"""Tests for POST-01's bounded, recommendation-only simulation."""

from datetime import datetime, timedelta, timezone

from backend.remediation import RemediationSimulator
from backend.schemas import (
    Diagnosis,
    EvidenceItem,
    Incident,
    RoutingPolicy,
    Transaction,
    TransactionBatch,
)


UTC = timezone.utc
START = datetime(2025, 9, 2, 13, tzinfo=UTC)


def _transaction(
    transaction_id: str,
    *,
    provider: str,
    approved: bool,
    timestamp: datetime,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        merchant="Rappi",
        country="Brazil",
        provider=provider,
        payment_method="PIX",
        issuing_bank="Itaú",
        status="approved" if approved else "declined",
        decline_code=None if approved else "91",
        amount=100.0,
        timestamp=timestamp,
    )


def _history() -> list[Transaction]:
    return [
        _transaction(
            f"history-{provider}-{index}",
            provider=provider,
            approved=index < approved_count,
            timestamp=datetime(2025, 1, 7, 13, tzinfo=UTC),
        )
        for provider, approved_count in (("Stripe", 94), ("Adyen", 90), ("dLocal", 85))
        for index in range(100)
    ]


def _batches(*, unhealthy_adyen: bool = False) -> tuple[TransactionBatch, ...]:
    batches = []
    for batch_index in range(2):
        start = START + timedelta(minutes=5 * batch_index)
        transactions = [
            _transaction(
                f"dlocal-{batch_index}-{index}",
                provider="dLocal",
                approved=False,
                timestamp=start,
            )
            for index in range(20)
        ]
        transactions.extend(
            _transaction(
                f"adyen-{batch_index}-{index}",
                provider="Adyen",
                approved=not unhealthy_adyen,
                timestamp=start,
            )
            for index in range(20)
        )
        batches.append(
            TransactionBatch(
                window_start=start,
                window_end=start + timedelta(minutes=5),
                transactions=transactions,
            )
        )
    return tuple(batches)


def _incident() -> Incident:
    return Incident(
        incident_id="inc-rappi-dlocal-pix",
        merchant="Rappi",
        country="Brazil",
        detected_at=START + timedelta(minutes=10),
        expected_conversion=0.92,
        actual_conversion=0.45,
        conversion_drop_pp=47.0,
        affected_volume=80,
        estimated_loss=3_760.0,
        estimated_loss_per_hour=22_560.0,
        severity="critical",
        anomaly_score=10.0,
    )


def _confirmed_diagnosis() -> Diagnosis:
    return Diagnosis(
        incident_id="inc-rappi-dlocal-pix",
        diagnosis_status="confirmed",
        confidence=0.90,
        root_cause_dimensions=["provider", "payment_method"],
        evidence=[
            EvidenceItem(
                dimension="intersection",
                value="dLocal × PIX",
                baseline_metric=0.92,
                live_metric=0.0,
                delta=-0.92,
                sample_size=40,
                explained_loss_share=0.90,
            )
        ],
        explanation="dLocal PIX is degraded.",
        recommended_action="Investigate dLocal.",
    )


def test_returns_ranked_simulations_without_executing_a_route() -> None:
    proposal = RemediationSimulator(_history()).propose(
        _incident(), _confirmed_diagnosis(), _batches()
    )

    assert proposal.status == "recommended"
    assert proposal.required_approval == "merchant_operations"
    assert proposal.recommended_option_id is not None
    assert len(proposal.alternatives) == 4
    assert {item.option.target_provider for item in proposal.alternatives} == {
        "Stripe",
        "Adyen",
    }
    assert all(item.status == "eligible" for item in proposal.alternatives)
    assert all(item.expected_recovered_value_per_hour > 0 for item in proposal.alternatives)
    assert "roll back" in proposal.rollback_condition.lower()


def test_blocks_a_target_route_that_is_currently_unhealthy() -> None:
    proposal = RemediationSimulator(_history()).propose(
        _incident(), _confirmed_diagnosis(), _batches(unhealthy_adyen=True)
    )

    adyen = [item for item in proposal.alternatives if item.option.target_provider == "Adyen"]
    assert all(item.status == "blocked" for item in adyen)
    assert all("currently unhealthy" in item.rejection_reason for item in adyen)


def test_abstains_when_rca_has_insufficient_evidence() -> None:
    diagnosis = _confirmed_diagnosis().model_copy(
        update={"diagnosis_status": "insufficient_evidence", "root_cause_dimensions": []}
    )

    proposal = RemediationSimulator(_history()).propose(_incident(), diagnosis, _batches())

    assert proposal.status == "not_recommended"
    assert proposal.alternatives == []


def test_routing_policy_enforces_the_traffic_cap() -> None:
    policy = RoutingPolicy(
        policy_id="rappi-brazil-pix-25pct",
        merchant="Rappi",
        country="Brazil",
        payment_method="PIX",
        eligible_target_providers=["Stripe", "Adyen"],
        max_traffic_shift_pct=0.25,
    )

    proposal = RemediationSimulator(_history(), policies=[policy]).propose(
        _incident(), _confirmed_diagnosis(), _batches()
    )

    assert proposal.policy_id == policy.policy_id
    assert len(proposal.alternatives) == 2
    assert {item.option.traffic_shift_pct for item in proposal.alternatives} == {0.25}
