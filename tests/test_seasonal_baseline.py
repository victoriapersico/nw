from datetime import datetime, timezone

from backend.baseline.seasonal import SeasonalBaseline
from backend.schemas import Transaction


def transaction(transaction_id: str, timestamp: datetime, status: str) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        merchant="Rappi",
        provider="Stripe",
        payment_method="PIX",
        country="Brazil",
        issuing_bank="Itaú",
        decline_code=None if status == "approved" else "91",
        status=status,
        amount=100.0,
        timestamp=timestamp,
    )


def test_baseline_uses_training_months_only() -> None:
    timestamp = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    validation_timestamp = datetime(2026, 5, 4, 9, tzinfo=timezone.utc)
    baseline = SeasonalBaseline(minimum_volume=2).fit(
        [
            transaction("train-approved", timestamp, "approved"),
            transaction("train-declined", timestamp, "declined"),
            transaction("validation-approved", validation_timestamp, "approved"),
            transaction("validation-approved-2", validation_timestamp, "approved"),
        ]
    )

    metric = baseline.expected_for("Rappi", "Brazil", timestamp)

    assert metric is not None
    assert metric.sample_size == 2
    assert metric.approval_rate == 0.5


def test_baseline_returns_none_without_minimum_volume() -> None:
    timestamp = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    baseline = SeasonalBaseline(minimum_volume=2).fit(
        [transaction("one", timestamp, "approved")]
    )

    assert baseline.expected_for("Rappi", "Brazil", timestamp) is None

def test_baseline_keeps_hour_of_week_buckets_separate() -> None:
    morning = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    afternoon = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)

    baseline = SeasonalBaseline(minimum_volume=2).fit(
        [
            transaction("morning-1", morning, "approved"),
            transaction("morning-2", morning, "approved"),
            transaction("afternoon-1", afternoon, "approved"),
            transaction("afternoon-2", afternoon, "declined"),
        ]
    )

    morning_metric = baseline.expected_for("Rappi", "Brazil", morning)
    afternoon_metric = baseline.expected_for("Rappi", "Brazil",
    afternoon)

    assert morning_metric is not None
    assert afternoon_metric is not None
    assert morning_metric.hour_of_week != afternoon_metric.hour_of_week
    assert morning_metric.approval_rate == 1.0
    assert afternoon_metric.approval_rate == 0.5