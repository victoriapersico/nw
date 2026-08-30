"""Generic end-to-end evaluator for the deterministic scenario catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Literal, Protocol, Sequence

from backend.evaluation.scenarios import CauseExpectation, ScenarioDefinition
from backend.schemas import DetectionRequest, DetectionResponse, Diagnosis, Incident, InjectionConfig, TransactionBatch


DetectionStatus = Literal[
    "DETECTED",
    "MISSED",
    "NO_ALERT",
    "FALSE_POSITIVE",
    "SKIPPED",
]
EvaluationDiagnosisStatus = Literal[
    "CONFIRMED",
    "ABSTAINED",
    "MISDIAGNOSED",
    "NOT_APPLICABLE",
    "SKIPPED",
]


class EvaluationRuntime(Protocol):
    """Integration boundary implemented by the simulator, detector, and RCA stack.

    ``apply_injection`` belongs to the simulator. ``detect`` accepts only a
    DetectionRequest, guaranteeing that InjectionConfig cannot cross into the
    detector through this harness.
    """

    def reset(self, scenario: ScenarioDefinition) -> None: ...

    def apply_injection(self, config: InjectionConfig) -> None: ...

    def next_batch(self) -> TransactionBatch: ...

    def detect(self, request: DetectionRequest) -> DetectionResponse: ...

    def diagnose(self, incident: Incident) -> Diagnosis: ...


@dataclass(frozen=True)
class IncidentObservation:
    incident: Incident
    diagnosis: Diagnosis | None
    first_detected_window: int


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: int
    name: str
    passed: bool
    skipped: bool
    detection_status: DetectionStatus
    diagnosis_status: EvaluationDiagnosisStatus
    mismatches: tuple[str, ...]
    incident_count: int
    first_detection_latency_minutes: int | None
    observations: tuple[IncidentObservation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "passed": self.passed,
            "skipped": self.skipped,
            "detection_status": self.detection_status,
            "diagnosis_status": self.diagnosis_status,
            "mismatches": list(self.mismatches),
            "incident_count": self.incident_count,
            "first_detection_latency_minutes": self.first_detection_latency_minutes,
            "observations": [
                {
                    "incident": observation.incident.model_dump(mode="json"),
                    "diagnosis": (
                        observation.diagnosis.model_dump(mode="json")
                        if observation.diagnosis
                        else None
                    ),
                    "first_detected_window": observation.first_detected_window,
                }
                for observation in self.observations
            ],
        }


@dataclass(frozen=True)
class EvaluationReport:
    generated_at: datetime
    results: tuple[ScenarioResult, ...]
    metrics: dict[str, float | int | None]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "metrics": self.metrics,
            "results": [result.to_dict() for result in self.results],
        }

    def to_markdown(self) -> str:
        metrics = self.metrics
        lines = [
            "# Synthetic evaluation report",
            "",
            f"Generated: `{self.generated_at.isoformat()}`",
            "",
            "## Metrics",
            "",
            f"- Evaluated scenarios: {metrics['evaluated_scenarios']}",
            f"- Passed scenarios: {metrics['passed_scenarios']}",
            f"- Detection recall: {_format_metric(metrics['detection_recall'])}",
            f"- False-positive rate: {_format_metric(metrics['false_positive_rate'])}",
            f"- Confirmed root-cause accuracy: {_format_metric(metrics['confirmed_root_cause_accuracy'])}",
            f"- Multi-incident separation accuracy: {_format_metric(metrics['multi_incident_separation_accuracy'])}",
            f"- Abstention accuracy: {_format_metric(metrics['abstention_accuracy'])}",
            f"- Mean detection latency: {_format_metric(metrics['mean_detection_latency_minutes'])} minutes",
            "- Estimated-loss error: unavailable until the live runtime exposes ground-truth loss.",
            "",
            "## Scenario results",
            "",
            "| # | Scenario | Result | Detection | Diagnosis | Incidents | Latency | Notes |",
            "|---:|---|---|---|---|---:|---:|---|",
        ]
        for result in self.results:
            status = "SKIPPED" if result.skipped else "PASS" if result.passed else "FAIL"
            notes = "; ".join(result.mismatches) or "—"
            latency = result.first_detection_latency_minutes or 0
            lines.append(
                f"| {result.scenario_id} | {result.name} | {status} | "
                f"{result.detection_status} | {result.diagnosis_status} | "
                f"{result.incident_count} | {latency} | {notes} |"
            )
        return "\n".join(lines) + "\n"

    def write(self, output_directory: str | Path) -> tuple[Path, Path]:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "evaluation_results.json"
        markdown_path = directory / "evaluation_summary.md"
        json_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        markdown_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path, markdown_path


class EvaluationHarness:
    """Runs scenarios through simulator → detector → RCA without leaking injection data."""

    def __init__(self, runtime: EvaluationRuntime, *, window_minutes: int = 5) -> None:
        if window_minutes <= 0:
            raise ValueError("window_minutes must be greater than zero")
        self.runtime = runtime
        self.window_minutes = window_minutes

    def run(self, scenarios: Sequence[ScenarioDefinition]) -> EvaluationReport:
        results = tuple(self.run_scenario(scenario) for scenario in scenarios)
        return EvaluationReport(
            generated_at=datetime.now().astimezone(),
            results=results,
            metrics=_calculate_metrics(scenarios, results),
        )

    def run_scenario(self, scenario: ScenarioDefinition) -> ScenarioResult:
        self.runtime.reset(scenario)
        for config in scenario.injections:
            self.runtime.apply_injection(config)

        observations: dict[str, IncidentObservation] = {}
        for window_index in range(scenario.evaluation_windows):
            batch = self.runtime.next_batch()
            response = self.runtime.detect(DetectionRequest(batch=batch))
            for incident in response.incidents:
                if incident.incident_id in observations:
                    continue
                observations[incident.incident_id] = IncidentObservation(
                    incident=incident,
                    diagnosis=self.runtime.diagnose(incident),
                    first_detected_window=window_index,
                )

        ordered_observations = tuple(observations.values())
        mismatches, skipped = _evaluate_expectation(scenario, ordered_observations)
        detection_status, diagnosis_status = _classify_result(
            scenario,
            ordered_observations,
            skipped=skipped,
        )
        latency = (
            min(item.first_detected_window + 1 for item in ordered_observations)
            * self.window_minutes
            if ordered_observations
            else None
        )
        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            name=scenario.name,
            passed=not mismatches,
            skipped=skipped,
            detection_status=detection_status,
            diagnosis_status=diagnosis_status,
            mismatches=tuple(mismatches),
            incident_count=len(ordered_observations),
            first_detection_latency_minutes=latency,
            observations=ordered_observations,
        )


def _evaluate_expectation(
    scenario: ScenarioDefinition, observations: tuple[IncidentObservation, ...]
) -> tuple[list[str], bool]:
    expectation = scenario.expectation
    if expectation.outcome == "optional":
        return [], True

    mismatches: list[str] = []
    if expectation.outcome == "no_alert":
        if observations:
            mismatches.append(f"expected no alert, observed {len(observations)} incident(s)")
        return mismatches, False

    if len(observations) < expectation.minimum_incidents:
        mismatches.append(
            f"expected at least {expectation.minimum_incidents} incident(s), "
            f"observed {len(observations)}"
        )

    diagnoses = [item.diagnosis for item in observations if item.diagnosis is not None]
    if expectation.outcome == "insufficient_evidence":
        # A low-volume slice may correctly be filtered before an Incident exists;
        # that is an abstention, not a failed expectation. If an incident reaches
        # RCA, it must explicitly abstain through Diagnosis.
        if not observations:
            return mismatches, False
        if not any(
            diagnosis.diagnosis_status == "insufficient_evidence" for diagnosis in diagnoses
        ):
            mismatches.append("expected diagnosis_status=insufficient_evidence")
        return mismatches, False

    for cause in expectation.causes:
        if not any(
            _confirmed_diagnosis_matches_cause(cause, diagnosis)
            for diagnosis in diagnoses
        ):
            mismatches.append(
                f"missing confirmed expected cause {cause.dimension}={cause.value}"
            )

    if expectation.primary_cause is not None and observations:
        primary = expectation.primary_cause
        highest_severity = max(
            observations, key=lambda item: _severity_rank(item.incident.severity)
        )
        if (
            highest_severity.diagnosis is None
            or not _confirmed_diagnosis_matches_cause(
                primary,
                highest_severity.diagnosis,
            )
        ):
            mismatches.append(
                "highest-priority confirmed diagnosis did not contain "
                f"{primary.dimension}={primary.value}"
            )
    return mismatches, False


def _confirmed_diagnosis_matches_cause(
    expected: CauseExpectation,
    diagnosis: Diagnosis,
) -> bool:
    if diagnosis.diagnosis_status != "confirmed":
        return False
    if expected.dimension == "intersection":
        return len(diagnosis.root_cause_dimensions) >= 2 and any(
            evidence.dimension == "intersection"
            and evidence.value == expected.value
            for evidence in diagnosis.evidence
        )
    return (
        expected.dimension in diagnosis.root_cause_dimensions
        and any(
            evidence.dimension == expected.dimension
            and evidence.value == expected.value
            for evidence in diagnosis.evidence
        )
    )


def _classify_result(
    scenario: ScenarioDefinition,
    observations: tuple[IncidentObservation, ...],
    *,
    skipped: bool,
) -> tuple[DetectionStatus, EvaluationDiagnosisStatus]:
    if skipped:
        return "SKIPPED", "SKIPPED"

    expected_outcome = scenario.expectation.outcome
    if expected_outcome == "no_alert":
        return (
            ("FALSE_POSITIVE", "NOT_APPLICABLE")
            if observations
            else ("NO_ALERT", "NOT_APPLICABLE")
        )

    if expected_outcome == "insufficient_evidence":
        if not observations:
            return "NO_ALERT", "ABSTAINED"
        diagnoses = [item.diagnosis for item in observations if item.diagnosis]
        if any(
            diagnosis.diagnosis_status == "insufficient_evidence"
            for diagnosis in diagnoses
        ):
            return "DETECTED", "ABSTAINED"
        return "DETECTED", "MISDIAGNOSED"

    if not observations:
        return "MISSED", "NOT_APPLICABLE"

    diagnoses = [item.diagnosis for item in observations if item.diagnosis]
    causes_confirmed = all(
        any(
            _confirmed_diagnosis_matches_cause(cause, diagnosis)
            for diagnosis in diagnoses
        )
        for cause in scenario.expectation.causes
    )
    if causes_confirmed:
        return "DETECTED", "CONFIRMED"
    if any(
        diagnosis.diagnosis_status == "insufficient_evidence"
        for diagnosis in diagnoses
    ):
        return "DETECTED", "ABSTAINED"
    return "DETECTED", "MISDIAGNOSED"


def _calculate_metrics(
    scenarios: Sequence[ScenarioDefinition], results: Sequence[ScenarioResult]
) -> dict[str, float | int | None]:
    paired = [
        (scenario, result)
        for scenario, result in zip(scenarios, results, strict=True)
        if not result.skipped
    ]
    positive = [item for item in paired if item[0].expectation.outcome == "incident"]
    negative = [item for item in paired if item[0].expectation.outcome == "no_alert"]
    abstentions = [
        item for item in paired if item[0].expectation.outcome == "insufficient_evidence"
    ]
    multi_incidents = [
        item
        for item in positive
        if item[0].expectation.minimum_incidents >= 2
    ]
    root_cause_cases = [item for item in positive if item[0].expectation.causes]
    detected_positive = [item for item in positive if item[1].incident_count > 0]
    latencies = [item[1].first_detection_latency_minutes for item in detected_positive]
    return {
        "evaluated_scenarios": len(paired),
        "passed_scenarios": sum(result.passed for _, result in paired),
        "detection_recall": _ratio(
            sum(result.incident_count > 0 for _, result in positive), len(positive)
        ),
        "false_positive_rate": _ratio(
            sum(result.incident_count > 0 for _, result in negative), len(negative)
        ),
        "confirmed_root_cause_accuracy": _ratio(
            sum(
                result.diagnosis_status == "CONFIRMED"
                for _, result in root_cause_cases
            ),
            len(root_cause_cases),
        ),
        "multi_incident_separation_accuracy": _ratio(
            sum(
                result.incident_count >= scenario.expectation.minimum_incidents
                for scenario, result in multi_incidents
            ),
            len(multi_incidents),
        ),
        "abstention_accuracy": _ratio(
            sum(
                result.diagnosis_status == "ABSTAINED"
                for _, result in abstentions
            ),
            len(abstentions),
        ),
        "mean_detection_latency_minutes": (
            sum(latencies) / len(latencies) if latencies else None
        ),
        "estimated_loss_error": None,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _severity_rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}[severity]


def _format_metric(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and 0 <= value <= 1:
        return f"{value:.1%}"
    return str(value)
