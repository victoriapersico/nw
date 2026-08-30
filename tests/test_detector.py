from datetime import datetime, timedelta, timezone

from backend.baseline.seasonal import SeasonalBaseline
from backend.detector.config import DetectorConfig
from backend.detector.detector import AnomalyDetector
from backend.schemas import Transaction, TransactionBatch


def transaction(
    transaction_id: str,
    timestamp: datetime,
    status: str,
    amount: float = 100.0,
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        merchant="Rappi",
        provider="Stripe",
        payment_method="PIX",
        country="Brazil",
        issuing_bank="Itaú",
        decline_code=None if status == "approved" else "91",
        status=status,
        amount=amount,
        timestamp=timestamp,
    )


def batch(
    start: datetime,
    statuses: list[str],
) -> TransactionBatch:
    return TransactionBatch(
        window_start=start,
        window_end=start + timedelta(minutes=5),
        transactions=[
            transaction(
                transaction_id=f"live-{index}",
                timestamp=start,
                status=status,
            )
            for index, status in enumerate(statuses)
        ],
    )


def detector() -> AnomalyDetector:
    training_time = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)

    baseline = SeasonalBaseline(minimum_volume=2).fit(
        [
            transaction("train-1", training_time, "approved"),
            transaction("train-2", training_time, "approved"),
        ]
    )

    config = DetectorConfig(
        minimum_volume=2,
        minimum_absolute_drop=0.08,
        z_score_threshold=-3.0,
        consecutive_windows=2,
    )

    return AnomalyDetector(
        baseline=baseline,
        config=config,
        window_minutes=5,
    )

def test_normal_window_does_not_create_incident() -> None:
    live_time = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)

    incidents = detector().detect(
        batch(live_time, ["approved", "approved"])
    )

    assert incidents == []


def test_first_anomalous_window_waits_for_confirmation() -> None:
    live_time = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)

    incidents = detector().detect(
        batch(live_time, ["declined", "declined"])
    )

    assert incidents == []

def test_second_consecutive_anomaly_creates_incident() -> None:
    anomaly_detector = detector()
    first_window = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
    second_window = first_window + timedelta(minutes=5)

    first_incidents = anomaly_detector.detect(
        batch(first_window, ["declined", "declined"])
    )
    second_incidents = anomaly_detector.detect(
        batch(second_window, ["declined", "declined"])
    )

    assert first_incidents == []
    assert len(second_incidents) == 1

    incident = second_incidents[0]
    assert incident.merchant == "Rappi"
    assert incident.country == "Brazil"
    assert incident.expected_conversion == 1.0
    assert incident.actual_conversion == 0.0
    assert incident.conversion_drop_pp == 100.0
    assert incident.affected_volume == 2
    assert incident.estimated_loss == 200.0
    assert incident.estimated_loss_per_hour == 2400.0
    assert incident.severity == "critical"

def test_low_volume_anomaly_does_not_create_incident() -> None:
    anomaly_detector = detector()
    first_window = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
    second_window = first_window + timedelta(minutes=5)

    first_incidents = anomaly_detector.detect(
        batch(first_window, ["declined"])
    )
    second_incidents = anomaly_detector.detect(
        batch(second_window, ["declined"])
    )

    assert first_incidents == []
    assert second_incidents == []

def test_normal_window_resets_anomaly_persistence() -> None:
    anomaly_detector = detector()
    first_window = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
    normal_window = first_window + timedelta(minutes=5)
    later_anomaly_window = normal_window + timedelta(minutes=5)

    first_incidents = anomaly_detector.detect(
        batch(first_window, ["declined", "declined"])
    )
    normal_incidents = anomaly_detector.detect(
        batch(normal_window, ["approved", "approved"])
    )
    later_incidents = anomaly_detector.detect(
        batch(later_anomaly_window, ["declined", "declined"])
    )

    assert first_incidents == []
    assert normal_incidents == []
    assert later_incidents == []


def test_sparse_seasonal_baseline_does_not_false_positive_normal_traffic() -> None:
    """A noisy seasonal bucket must borrow support from its stable parent."""

    training_time = datetime(2025, 1, 6, 9, tzinfo=timezone.utc)
    parent_time = training_time + timedelta(hours=1)
    training = [
        transaction(
            f"seasonal-{index}",
            training_time,
            "approved" if index < 55 else "declined",
        )
        for index in range(57)
    ] + [
        transaction(
            f"parent-{index}",
            parent_time,
            "approved" if index < 450 else "declined",
        )
        for index in range(500)
    ]
    anomaly_detector = AnomalyDetector(
        baseline=SeasonalBaseline(minimum_volume=50).fit(training),
        config=DetectorConfig(
            minimum_volume=50,
            minimum_absolute_drop=0.08,
            z_score_threshold=-3.0,
            consecutive_windows=2,
        ),
        window_minutes=5,
    )
    live_time = datetime(2025, 9, 1, 9, tzinfo=timezone.utc)
    normal_statuses = ["approved"] * 135 + ["declined"] * 18

    first = anomaly_detector.detect(batch(live_time, normal_statuses))
    second = anomaly_detector.detect(
        batch(live_time + timedelta(minutes=5), normal_statuses)
    )

    assert first == []
    assert second == []
