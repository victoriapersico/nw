from datetime import datetime, timedelta, timezone

from backend.evaluation.harness import EvaluationHarness
from backend.evaluation.scenarios import SCENARIOS
from backend.schemas import (
    DetectionRequest,
    DetectionResponse,
    Diagnosis,
    EvidenceItem,
    Incident,
    Transaction,
    TransactionBatch,
)


UTC = timezone.utc


class QuietRuntime:
    def __init__(self) -> None:
        self.injections = []
        self.detector_requests = []
        self.current_scenario = None

    def reset(self, scenario) -> None:
        self.current_scenario = scenario

    def apply_injection(self, config) -> None:
        self.injections.append(config)

    def next_batch(self) -> TransactionBatch:
        start = self.current_scenario.start_at
        transaction = Transaction(
            transaction_id=f"quiet-{start:%Y%m%d%H%M}",
            merchant="Rappi",
            provider="Stripe",
            payment_method="CARD",
            country="Mexico",
            issuing_bank="Banorte",
            decline_code=None,
            status="approved",
            amount=10.0,
            timestamp=start,
        )
        return TransactionBatch(
            window_start=start,
            window_end=start + timedelta(minutes=5),
            transactions=[transaction],
        )

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        self.detector_requests.append(request)
        return DetectionResponse(incidents=[])

    def diagnose(self, incident):  # pragma: no cover - no incident in this runtime
        raise AssertionError("diagnose should not be called")


class StripeIncidentRuntime(QuietRuntime):
    def detect(self, request: DetectionRequest) -> DetectionResponse:
        self.detector_requests.append(request)
        return DetectionResponse(
            incidents=[
                Incident(
                    incident_id="inc-stripe",
                    merchant="Rappi",
                    country="Brazil",
                    detected_at=request.batch.window_end,
                    expected_conversion=0.92,
                    actual_conversion=0.50,
                    conversion_drop_pp=42.0,
                    affected_volume=100,
                    estimated_loss=420.0,
                    estimated_loss_per_hour=5_040.0,
                    severity="high",
                    anomaly_score=-4.0,
                )
            ]
        )

    def diagnose(self, incident: Incident) -> Diagnosis:
        return Diagnosis(
            incident_id=incident.incident_id,
            root_cause_dimensions=["provider"],
            evidence=[
                EvidenceItem(
                    dimension="provider",
                    value="Stripe",
                    baseline_metric=0.92,
                    live_metric=0.50,
                    delta=-0.42,
                    sample_size=100,
                    explained_loss_share=0.9,
                )
            ],
            confidence=0.95,
            diagnosis_status="confirmed",
            explanation="Stripe is degraded.",
            recommended_action="Investigate Stripe.",
        )


def test_catalog_has_exactly_the_required_deterministic_scenarios() -> None:
    assert [scenario.scenario_id for scenario in SCENARIOS] == list(range(1, 31))
    assert len({scenario.seed for scenario in SCENARIOS}) == 30
    assert SCENARIOS[28].expectation.outcome == "optional"


def test_harness_passes_only_batches_to_detector_and_writes_reports(tmp_path) -> None:
    runtime = QuietRuntime()
    scenario = SCENARIOS[0]

    report = EvaluationHarness(runtime).run([scenario])
    json_path, markdown_path = report.write(tmp_path)

    assert report.results[0].passed
    assert runtime.injections == []
    assert all(isinstance(request, DetectionRequest) for request in runtime.detector_requests)
    assert json_path.exists()
    assert markdown_path.exists()


def test_random_unseen_slice_is_valid_and_repeatable() -> None:
    unseen = SCENARIOS[29]

    assert unseen.name == "Random unseen injected slice"
    assert len(unseen.injections) == 1
    assert unseen.injections[0].target_approval_rate == 0.30


def test_harness_evaluates_observed_cause_from_diagnosis_evidence() -> None:
    report = EvaluationHarness(StripeIncidentRuntime()).run([SCENARIOS[6]])

    result = report.results[0]
    assert result.passed
    assert result.incident_count == 1
    assert report.metrics["detection_recall"] == 1.0
    assert report.metrics["root_cause_accuracy"] == 1.0
