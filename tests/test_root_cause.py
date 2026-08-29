from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

import backend.root_cause as root_cause_module
from backend.detector.impact import calculate_money_impact
from backend.root_cause import RootCauseAnalyzer
from backend.schemas import Diagnosis, Incident, Transaction, TransactionBatch


UTC = timezone.utc
HISTORICAL_TIME = datetime(2025, 1, 7, 13, tzinfo=UTC)
LIVE_TIME = datetime(2026, 9, 1, 13, tzinfo=UTC)
PROVIDERS = ("Stripe", "Adyen", "dLocal")
PAYMENT_METHODS = ("CARD", "PIX")
BANKS = ("Itaú", "Bradesco", "Banco do Brasil", "Nubank")
DECLINE_CODES = ("05", "51", "54", "57", "61", "91", "96")


def historical_transactions(
    *, timestamp: datetime = HISTORICAL_TIME
) -> list[Transaction]:
    transactions: list[Transaction] = []
    sequence = 0
    for provider, payment_method, bank in product(
        PROVIDERS, PAYMENT_METHODS, BANKS
    ):
        for position in range(70):
            approved = position < 63
            code = None if approved else DECLINE_CODES[position - 63]
            sequence += 1
            transactions.append(
                make_transaction(
                    transaction_id=f"history-{sequence}",
                    timestamp=timestamp,
                    provider=provider,
                    payment_method=payment_method,
                    bank=bank,
                    approved=approved,
                    decline_code=code,
                )
            )
    return transactions


def live_batches(
    degraded,
    *,
    target_rate: float = 0.0,
    forced_decline_code: str | None = None,
    boost_degraded_traffic: bool = False,
) -> tuple[TransactionBatch, TransactionBatch]:
    batches: list[TransactionBatch] = []
    sequence = 0
    combinations = tuple(product(PROVIDERS, PAYMENT_METHODS, BANKS))
    for batch_index in range(2):
        start = LIVE_TIME + timedelta(minutes=5 * batch_index)
        transactions: list[Transaction] = []
        for combination_index, (provider, payment_method, bank) in enumerate(combinations):
            is_degraded = degraded(provider, payment_method, bank)
            count = 28 if boost_degraded_traffic and is_degraded else 14
            approval_rate = target_rate if is_degraded else 13 / 14
            approved_count = round(count * approval_rate)
            for position in range(count):
                approved = position < approved_count
                code = None
                if not approved:
                    code = (
                        forced_decline_code
                        if is_degraded and forced_decline_code is not None
                        else DECLINE_CODES[
                            (combination_index + position + batch_index)
                            % len(DECLINE_CODES)
                        ]
                    )
                sequence += 1
                transactions.append(
                    make_transaction(
                        transaction_id=f"live-{sequence}",
                        timestamp=start + timedelta(seconds=position),
                        provider=provider,
                        payment_method=payment_method,
                        bank=bank,
                        approved=approved,
                        decline_code=code,
                    )
                )
        batches.append(
            TransactionBatch(
                window_start=start,
                window_end=start + timedelta(minutes=5),
                transactions=transactions,
            )
        )
    return batches[0], batches[1]


def make_transaction(
    *,
    transaction_id: str,
    timestamp: datetime,
    provider: str,
    payment_method: str,
    bank: str,
    approved: bool,
    decline_code: str | None,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        merchant="Rappi",
        provider=provider,
        payment_method=payment_method,
        country="Brazil",
        issuing_bank=bank,
        decline_code=decline_code,
        status="approved" if approved else "declined",
        amount=100.0,
        timestamp=timestamp,
    )


def incident_for(batches: tuple[TransactionBatch, TransactionBatch]) -> Incident:
    current = batches[-1]
    transactions = current.transactions
    expected = 0.90
    actual = sum(item.status == "approved" for item in transactions) / len(
        transactions
    )
    impact = calculate_money_impact(
        transactions,
        expected_conversion=expected,
        window_minutes=5,
    )
    return Incident(
        incident_id="inc-rappi-brazil",
        merchant="Rappi",
        country="Brazil",
        detected_at=current.window_end,
        expected_conversion=expected,
        actual_conversion=actual,
        conversion_drop_pp=max(0.0, (expected - actual) * 100),
        affected_volume=len(transactions),
        estimated_loss=impact.estimated_loss,
        estimated_loss_per_hour=impact.estimated_loss_per_hour,
        severity="critical" if expected - actual >= 0.30 else "high",
        anomaly_score=10.0,
    )


def diagnose(
    batches: tuple[TransactionBatch, TransactionBatch],
    *,
    history: list[Transaction] | None = None,
) -> Diagnosis:
    analyzer = RootCauseAnalyzer(history or historical_transactions())
    return analyzer.diagnose(incident_for(batches), batches)


def evidence_values(diagnosis: Diagnosis, dimension: str) -> set[str]:
    return {
        item.value for item in diagnosis.evidence if item.dimension == dimension
    }


def test_provider_only_degradation_is_identified() -> None:
    batches = live_batches(lambda provider, _method, _bank: provider == "dLocal")

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "confirmed"
    assert diagnosis.root_cause_dimensions == ["provider"]
    assert evidence_values(diagnosis, "provider") == {"dLocal"}
    provider_evidence = next(
        item for item in diagnosis.evidence if item.dimension == "provider"
    )
    assert provider_evidence.sample_size == 224


def test_payment_method_degradation_is_identified() -> None:
    batches = live_batches(lambda _provider, method, _bank: method == "PIX")

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "confirmed"
    assert diagnosis.root_cause_dimensions == ["payment_method"]
    assert evidence_values(diagnosis, "payment_method") == {"PIX"}
    assert evidence_values(diagnosis, "merchant") == {"Rappi"}


def test_issuing_bank_degradation_is_identified() -> None:
    batches = live_batches(lambda _provider, _method, bank: bank == "Itaú")

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "confirmed"
    assert diagnosis.root_cause_dimensions == ["issuing_bank"]
    assert evidence_values(diagnosis, "issuing_bank") == {"Itaú"}


def test_decline_code_spike_is_identified() -> None:
    batches = live_batches(
        lambda _provider, _method, _bank: True,
        target_rate=0.30,
        forced_decline_code="91",
    )

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "confirmed"
    assert "decline_code" in diagnosis.root_cause_dimensions
    assert evidence_values(diagnosis, "decline_code") == {"91"}


def test_provider_payment_method_intersection_is_identified() -> None:
    batches = live_batches(
        lambda provider, method, _bank: provider == "dLocal" and method == "PIX"
    )

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "confirmed"
    assert diagnosis.root_cause_dimensions == ["provider", "payment_method"]
    assert "dLocal × PIX" in evidence_values(diagnosis, "intersection")
    assert "dLocal" in evidence_values(diagnosis, "provider")
    assert "PIX" in evidence_values(diagnosis, "payment_method")


def test_provider_bank_intersection_is_identified_when_supported() -> None:
    batches = live_batches(
        lambda provider, _method, bank: provider == "dLocal" and bank == "Itaú",
        boost_degraded_traffic=True,
    )

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "confirmed"
    assert diagnosis.root_cause_dimensions == ["provider", "issuing_bank"]
    assert "dLocal × Itaú" in evidence_values(diagnosis, "intersection")


def test_normal_dimensions_are_not_ranked_as_root_causes() -> None:
    batches = live_batches(lambda provider, _method, _bank: provider == "dLocal")

    diagnosis = diagnose(batches)

    assert evidence_values(diagnosis, "provider") == {"dLocal"}
    assert evidence_values(diagnosis, "payment_method") == set()
    assert evidence_values(diagnosis, "issuing_bank") == set()
    assert evidence_values(diagnosis, "decline_code") == set()


def test_low_volume_candidate_is_ignored() -> None:
    batches = live_batches(
        lambda provider, method, bank: (
            provider == "dLocal" and method == "PIX" and bank == "Itaú"
        )
    )

    diagnosis = diagnose(batches)

    assert "dLocal × PIX × Itaú" not in evidence_values(
        diagnosis, "intersection"
    )
    assert all(item.sample_size >= 34 for item in diagnosis.evidence)


def test_ambiguous_competing_providers_produce_insufficient_evidence() -> None:
    batches = live_batches(
        lambda provider, _method, _bank: provider in {"Stripe", "dLocal"}
    )

    diagnosis = diagnose(batches)

    assert diagnosis.diagnosis_status == "insufficient_evidence"
    assert diagnosis.root_cause_dimensions == []


def test_same_hour_of_week_history_is_preferred() -> None:
    same_hour = historical_transactions()
    other_hour = historical_transactions(timestamp=HISTORICAL_TIME + timedelta(hours=1))
    # Make broad dLocal behavior much worse; supported same-hour evidence remains 90%.
    changed_history = [
        item.model_copy(
            update={
                "status": "declined",
                "decline_code": "05",
            }
        )
        if item.provider == "dLocal" and item.status == "approved"
        else item
        for item in other_hour
    ]
    batches = live_batches(lambda provider, _method, _bank: provider == "dLocal")

    diagnosis = diagnose(batches, history=[*same_hour, *changed_history])

    dlocal = next(
        item
        for item in diagnosis.evidence
        if item.dimension == "provider" and item.value == "dLocal"
    )
    assert dlocal.baseline_metric == pytest.approx(0.90)


def test_global_history_is_used_when_hour_of_week_slice_is_sparse() -> None:
    history = historical_transactions(timestamp=HISTORICAL_TIME + timedelta(hours=1))
    batches = live_batches(lambda provider, _method, _bank: provider == "dLocal")

    diagnosis = diagnose(batches, history=history)

    assert diagnosis.diagnosis_status == "confirmed"
    dlocal = next(
        item
        for item in diagnosis.evidence
        if item.dimension == "provider" and item.value == "dLocal"
    )
    assert dlocal.baseline_metric == pytest.approx(0.90)


def test_output_is_schema_valid_deterministic_and_has_no_injection_dependency() -> None:
    batches = live_batches(lambda provider, _method, _bank: provider == "dLocal")
    analyzer = RootCauseAnalyzer(historical_transactions())
    incident = incident_for(batches)

    first = analyzer.diagnose(incident, batches)
    second = analyzer.diagnose(incident, batches)

    assert Diagnosis.model_validate(first.model_dump()) == first
    assert first == second
    assert not hasattr(root_cause_module, "InjectionConfig")
    assert first.recommended_action == "Investigate the affected payment route."
