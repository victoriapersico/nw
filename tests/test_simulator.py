import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import get_args

import pytest

from backend.data_generator import (
    BANK_WEIGHTS,
    PAYMENT_METHOD_WEIGHTS,
    PROVIDER_WEIGHTS,
    expected_approval_rate,
    expected_hourly_volume,
)
from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    DeclineCode,
    InjectionConfig,
    Transaction,
    TransactionBatch,
)
from backend.simulator import (
    DEFAULT_TRANSACTIONS_PER_WINDOW,
    LiveTransactionSimulator,
    TransactionContext,
)


START_TIME = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
VALID_DECLINE_CODES = set(get_args(DeclineCode))


def matches(transaction: Transaction, config: InjectionConfig) -> bool:
    return (
        transaction.merchant == config.merchant
        and transaction.country == config.country
        and (config.provider is None or transaction.provider == config.provider)
        and (
            config.payment_method is None
            or transaction.payment_method == config.payment_method
        )
        and (
            config.issuing_bank is None
            or transaction.issuing_bank == config.issuing_bank
        )
    )


def approval_rate(transactions: list[Transaction]) -> float:
    return sum(transaction.status == "approved" for transaction in transactions) / len(
        transactions
    )


def paired_simulators(
    *, seed: int, transactions_per_window: int
) -> tuple[LiveTransactionSimulator, LiveTransactionSimulator]:
    arguments = {
        "start_time": START_TIME,
        "seed": seed,
        "transactions_per_window": transactions_per_window,
    }
    return LiveTransactionSimulator(**arguments), LiveTransactionSimulator(**arguments)


def test_normal_batch_validates_against_frozen_contract() -> None:
    simulator = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=250,
        seed=1,
    )

    batch = simulator.next_batch()

    assert len(batch.transactions) == 250
    assert TransactionBatch.model_validate(batch.model_dump()) == batch
    assert all(
        batch.window_start <= transaction.timestamp < batch.window_end
        for transaction in batch.transactions
    )


def test_default_batch_contains_exactly_1_200_transactions() -> None:
    batch = LiveTransactionSimulator(start_time=START_TIME, seed=15).next_batch()

    assert DEFAULT_TRANSACTIONS_PER_WINDOW == 1_200
    assert len(batch.transactions) == DEFAULT_TRANSACTIONS_PER_WINDOW


def test_live_uses_exact_historical_approval_rate_for_same_context() -> None:
    context = TransactionContext(
        merchant="Rappi",
        country="Brazil",
        provider="dLocal",
        payment_method="PIX",
        issuing_bank="Itaú",
        amount=42.5,
        timestamp=START_TIME + timedelta(minutes=3),
    )
    expected = expected_approval_rate(
        merchant=context.merchant,
        country=context.country,
        provider=context.provider,
        payment_method=context.payment_method,
        issuing_bank=context.issuing_bank,
        hour_start=START_TIME,
    )

    actual = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=1,
        seed=16,
    ).normal_approval_probability(context)

    assert actual == expected


def test_live_allocation_preserves_relative_historical_volume_profile() -> None:
    batch = LiveTransactionSimulator(start_time=START_TIME, seed=17).next_batch()
    counts = Counter(
        (transaction.merchant, transaction.country)
        for transaction in batch.transactions
    )
    weights = {
        payment_slice: expected_hourly_volume(
            merchant=payment_slice[0],
            country=payment_slice[1],
            hour_start=START_TIME,
        )
        for payment_slice in counts
    }
    total_weight = sum(weights.values())

    assert len(batch.transactions) == 1_200
    assert min(counts.values()) > 50
    for payment_slice, weight in weights.items():
        expected_count = len(batch.transactions) * weight / total_weight
        assert counts[payment_slice] == pytest.approx(expected_count, abs=1)


def test_live_reuses_historical_provider_method_and_bank_weights() -> None:
    transactions = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=36_000,
        seed=18,
    ).next_batch().transactions

    for country in ("Mexico", "Brazil", "Colombia"):
        country_transactions = [
            transaction
            for transaction in transactions
            if transaction.country == country
        ]
        for attribute, configured_weights in (
            ("provider", PROVIDER_WEIGHTS[country]),
            ("payment_method", PAYMENT_METHOD_WEIGHTS[country]),
            ("issuing_bank", BANK_WEIGHTS[country]),
        ):
            observed = Counter(
                getattr(transaction, attribute)
                for transaction in country_transactions
            )
            total_configured_weight = sum(weight for _, weight in configured_weights)
            for value, weight in configured_weights:
                observed_share = observed[value] / len(country_transactions)
                expected_share = weight / total_configured_weight
                assert observed_share == pytest.approx(expected_share, abs=0.025)


def test_simulated_timestamps_advance_exactly_one_window() -> None:
    simulator = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=10,
        seed=2,
    )

    first = simulator.next_batch()
    second = simulator.next_batch()

    assert first.window_start == START_TIME
    assert first.window_end == START_TIME + timedelta(minutes=5)
    assert second.window_start == first.window_end
    assert second.window_end == first.window_end + timedelta(minutes=5)
    assert simulator.current_time == second.window_end


def test_same_seed_produces_reproducible_output() -> None:
    first = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=300,
        seed=3,
    )
    second = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=300,
        seed=3,
    )

    assert first.next_batch() == second.next_batch()
    assert first.next_batch() == second.next_batch()


@pytest.mark.parametrize(
    ("payment_method", "required_country"),
    [("PIX", "Brazil"), ("PSE", "Colombia"), ("OXXO", "Mexico")],
)
def test_country_specific_methods_never_leave_their_country(
    payment_method: str,
    required_country: str,
) -> None:
    batch = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=3_000,
        seed=4,
    ).next_batch()
    matching = [
        transaction
        for transaction in batch.transactions
        if transaction.payment_method == payment_method
    ]

    assert matching
    assert {transaction.country for transaction in matching} == {required_country}


def test_issuing_bank_always_belongs_to_transaction_country() -> None:
    batch = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=3_000,
        seed=5,
    ).next_batch()

    assert all(
        transaction.issuing_bank in COUNTRY_ISSUING_BANKS[transaction.country]
        for transaction in batch.transactions
    )


def test_approved_transactions_have_no_decline_code() -> None:
    transactions = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=1_000,
        seed=6,
    ).next_batch().transactions

    approved = [transaction for transaction in transactions if transaction.status == "approved"]
    assert approved
    assert all(transaction.decline_code is None for transaction in approved)


def test_declined_transactions_have_a_valid_decline_code() -> None:
    transactions = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=1_000,
        seed=7,
    ).next_batch().transactions

    declined = [transaction for transaction in transactions if transaction.status == "declined"]
    assert declined
    assert all(transaction.decline_code in VALID_DECLINE_CODES for transaction in declined)


def test_injection_changes_only_its_matching_slice_and_uses_configured_code() -> None:
    control, injected = paired_simulators(seed=8, transactions_per_window=5_400)
    config = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        provider="dLocal",
        payment_method="PIX",
        decline_code="91",
        target_approval_rate=0.0,
        duration_windows=1,
    )
    injected.activate_injection(config)

    control_batch = control.next_batch()
    injected_batch = injected.next_batch()
    newly_declined = 0
    matching_count = 0

    for normal, changed in zip(
        control_batch.transactions, injected_batch.transactions, strict=True
    ):
        if not matches(normal, config):
            assert changed == normal
            continue

        matching_count += 1
        assert changed.status == "declined"
        if normal.status == "approved":
            newly_declined += 1
            assert changed.decline_code == "91"

    assert matching_count > 50
    assert newly_declined > 0


def test_injected_approval_rate_moves_toward_target() -> None:
    simulator = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=9_000,
        seed=9,
    )
    config = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        decline_code="96",
        target_approval_rate=0.35,
        duration_windows=1,
    )
    simulator.activate_injection(config)

    matching = [
        transaction
        for transaction in simulator.next_batch().transactions
        if matches(transaction, config)
    ]

    assert len(matching) > 900
    assert approval_rate(matching) == pytest.approx(0.35, abs=0.05)


def test_injection_affects_only_future_batches_and_expires() -> None:
    control, injected = paired_simulators(seed=10, transactions_per_window=1_800)
    config = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        decline_code="91",
        target_approval_rate=0.0,
        duration_windows=2,
    )

    assert injected.next_batch() == control.next_batch()
    injected.activate_injection(config)

    first_active = injected.next_batch()
    first_control = control.next_batch()
    assert any(
        matches(normal, config) and normal.status == "approved" and changed != normal
        for normal, changed in zip(
            first_control.transactions, first_active.transactions, strict=True
        )
    )
    assert [item.remaining_windows for item in injected.active_injections] == [1]

    second_active = injected.next_batch()
    second_control = control.next_batch()
    assert any(
        matches(normal, config) and normal.status == "approved" and changed != normal
        for normal, changed in zip(
            second_control.transactions, second_active.transactions, strict=True
        )
    )
    assert injected.active_injections == []

    assert injected.next_batch() == control.next_batch()


def test_two_non_overlapping_injections_work_in_the_same_batch() -> None:
    control, injected = paired_simulators(seed=11, transactions_per_window=5_400)
    first = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        provider="dLocal",
        decline_code="91",
        target_approval_rate=0.0,
        duration_windows=6,
    )
    second = InjectionConfig(
        merchant="Despegar",
        country="Mexico",
        provider="Stripe",
        decline_code="96",
        target_approval_rate=0.0,
        duration_windows=4,
    )
    injected.activate_injection(first)
    injected.activate_injection(second)

    normal_batch = control.next_batch()
    changed_batch = injected.next_batch()
    caused_declines = {"91": 0, "96": 0}

    for normal, changed in zip(
        normal_batch.transactions, changed_batch.transactions, strict=True
    ):
        selected = first if matches(normal, first) else second if matches(normal, second) else None
        if selected is None:
            assert changed == normal
        elif normal.status == "approved":
            assert changed.status == "declined"
            assert changed.decline_code == selected.decline_code
            caused_declines[selected.decline_code] += 1

    assert caused_declines["91"] > 0
    assert caused_declines["96"] > 0
    assert [item.remaining_windows for item in injected.active_injections] == [5, 3]


def test_simultaneous_injections_expire_independently() -> None:
    control, injected = paired_simulators(seed=12, transactions_per_window=2_400)
    longer = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        provider="dLocal",
        decline_code="91",
        target_approval_rate=0.0,
        duration_windows=2,
    )
    shorter = InjectionConfig(
        merchant="Despegar",
        country="Mexico",
        provider="Stripe",
        decline_code="96",
        target_approval_rate=0.0,
        duration_windows=1,
    )
    injected.activate_injection(longer)
    injected.activate_injection(shorter)

    injected.next_batch()
    control.next_batch()
    assert len(injected.active_injections) == 1
    assert injected.active_injections[0].config == longer
    assert injected.active_injections[0].remaining_windows == 1

    second_changed = injected.next_batch()
    second_normal = control.next_batch()
    longer_changes = 0
    for normal, changed in zip(
        second_normal.transactions, second_changed.transactions, strict=True
    ):
        if matches(normal, shorter):
            assert changed == normal
        if matches(normal, longer) and normal.status == "approved":
            assert changed.status == "declined"
            longer_changes += 1

    assert longer_changes > 0
    assert injected.active_injections == []
    assert injected.next_batch() == control.next_batch()


def test_overlapping_injections_use_lowest_target_and_its_decline_code() -> None:
    control, injected = paired_simulators(seed=13, transactions_per_window=5_400)
    broad = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        decline_code="91",
        target_approval_rate=0.50,
        duration_windows=1,
    )
    severe = InjectionConfig(
        merchant="Rappi",
        country="Brazil",
        provider="dLocal",
        decline_code="96",
        target_approval_rate=0.0,
        duration_windows=1,
    )
    injected.activate_injection(broad)
    injected.activate_injection(severe)

    normal_batch = control.next_batch()
    changed_batch = injected.next_batch()
    newly_declined = 0

    for normal, changed in zip(
        normal_batch.transactions, changed_batch.transactions, strict=True
    ):
        if matches(normal, severe):
            assert changed.status == "declined"
            if normal.status == "approved":
                newly_declined += 1
                assert changed.decline_code == "96"

    assert newly_declined > 0


def test_serialized_batch_contains_zero_injection_metadata() -> None:
    simulator = LiveTransactionSimulator(
        start_time=START_TIME,
        transactions_per_window=100,
        seed=14,
    )
    simulator.activate_injection(
        InjectionConfig(
            merchant="Rappi",
            country="Brazil",
            target_approval_rate=0.35,
            duration_windows=2,
        )
    )

    payload = simulator.next_batch().model_dump(mode="json")
    serialized = json.dumps(payload)

    assert set(payload) == {"window_start", "window_end", "transactions"}
    assert "injection" not in serialized.lower()
