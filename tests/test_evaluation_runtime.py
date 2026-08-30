from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.baseline.seasonal import SeasonalBaseline
from backend.evaluation.scenarios import SCENARIOS
from backend.integration.evaluation_runtime import (
    ControlTowerEvaluationRuntime,
    _load_baseline,
)
from backend.schemas import DetectionRequest, Diagnosis, Incident, Transaction, TransactionBatch


UTC = timezone.utc


def test_runtime_loads_blank_decline_codes_from_persisted_csv(tmp_path) -> None:
    path = tmp_path / "history.csv"
    pd.DataFrame(
        [
            {
                "transaction_id": "approved",
                "merchant": "Rappi",
                "provider": "Stripe",
                "payment_method": "CARD",
                "country": "Mexico",
                "issuing_bank": "Banorte",
                "decline_code": None,
                "status": "approved",
                "amount": 10.0,
                "timestamp": datetime(2025, 1, 6, 9, tzinfo=UTC),
            },
            {
                "transaction_id": "declined",
                "merchant": "Rappi",
                "provider": "Stripe",
                "payment_method": "CARD",
                "country": "Mexico",
                "issuing_bank": "Banorte",
                "decline_code": "05",
                "status": "declined",
                "amount": 10.0,
                "timestamp": datetime(2025, 1, 6, 9, tzinfo=UTC),
            },
        ]
    ).to_csv(path, index=False)

    baseline = _load_baseline(str(path.resolve()), minimum_volume=1)

    metric = baseline.expected_for("Rappi", "Mexico", datetime(2025, 1, 6, 9, tzinfo=UTC))
    assert metric is not None
    assert metric.approval_rate == 0.5


class RecordingRootCauseAnalyzer:
    def __init__(self) -> None:
        self.recent_batches: tuple[TransactionBatch, ...] = ()

    def diagnose(
        self,
        incident: Incident,
        recent_batches: tuple[TransactionBatch, ...],
    ) -> Diagnosis:
        self.recent_batches = recent_batches
        return Diagnosis(
            incident_id=incident.incident_id,
            root_cause_dimensions=[],
            evidence=[],
            confidence=0.0,
            diagnosis_status="insufficient_evidence",
            explanation="Test recording diagnosis.",
            recommended_action="Investigate the affected payment route.",
        )


def live_batch(start: datetime, sequence: int) -> TransactionBatch:
    return TransactionBatch(
        window_start=start,
        window_end=start + timedelta(minutes=5),
        transactions=[
            Transaction(
                transaction_id=f"runtime-live-{sequence}",
                merchant="Rappi",
                provider="Stripe",
                payment_method="CARD",
                country="Mexico",
                issuing_bank="Banorte",
                decline_code="91",
                status="declined",
                amount=100.0,
                timestamp=start,
            )
        ],
    )


def runtime_incident(batch: TransactionBatch) -> Incident:
    return Incident(
        incident_id="inc-runtime",
        merchant="Rappi",
        country="Mexico",
        detected_at=batch.window_end,
        expected_conversion=0.90,
        actual_conversion=0.0,
        conversion_drop_pp=90.0,
        affected_volume=1,
        estimated_loss=90.0,
        estimated_loss_per_hour=1_080.0,
        severity="critical",
        anomaly_score=10.0,
    )


def test_runtime_supplies_two_consecutive_detector_windows_to_rca() -> None:
    analyzer = RecordingRootCauseAnalyzer()
    runtime = ControlTowerEvaluationRuntime(
        SeasonalBaseline(minimum_volume=1),
        root_cause_analyzer=analyzer,
    )
    runtime.reset(SCENARIOS[0])
    start = SCENARIOS[0].start_at
    first = live_batch(start, 1)
    second = live_batch(start + timedelta(minutes=5), 2)
    runtime.detect(DetectionRequest(batch=first))
    runtime.detect(DetectionRequest(batch=second))

    runtime.diagnose(runtime_incident(second))

    assert analyzer.recent_batches == (first, second)


def test_runtime_safely_falls_back_to_one_available_window() -> None:
    analyzer = RecordingRootCauseAnalyzer()
    runtime = ControlTowerEvaluationRuntime(
        SeasonalBaseline(minimum_volume=1),
        root_cause_analyzer=analyzer,
    )
    runtime.reset(SCENARIOS[0])
    only_batch = live_batch(SCENARIOS[0].start_at, 1)
    runtime.detect(DetectionRequest(batch=only_batch))

    runtime.diagnose(runtime_incident(only_batch))

    assert analyzer.recent_batches == (only_batch,)


class UnorderedIncidentDetector:
    def __init__(self, incidents: list[Incident]) -> None:
        self._incidents = incidents

    def detect(self, _batch: TransactionBatch) -> list[Incident]:
        return self._incidents


def test_runtime_processes_detector_output_through_incident_engine() -> None:
    runtime = ControlTowerEvaluationRuntime(SeasonalBaseline(minimum_volume=1))
    runtime.reset(SCENARIOS[0])
    batch = live_batch(SCENARIOS[0].start_at, 1)
    high_loss = runtime_incident(batch).model_copy(
        update={
            "incident_id": "inc-high-loss",
            "severity": "high",
            "estimated_loss": 10_000.0,
        }
    )
    critical = runtime_incident(batch).model_copy(
        update={
            "incident_id": "inc-critical",
            "merchant": "Carrefour",
            "country": "Mexico",
            "severity": "critical",
            "estimated_loss": 1_000.0,
        }
    )
    runtime._detector = UnorderedIncidentDetector([high_loss, critical])

    response = runtime.detect(DetectionRequest(batch=batch))

    assert [incident.incident_id for incident in response.incidents] == [
        "inc-critical",
        "inc-high-loss",
    ]
