"""Concrete simulator → detector adapter used by the MVP-03 evaluation command."""

from __future__ import annotations

from collections import deque
from functools import lru_cache
from pathlib import Path

import pandas as pd

from backend.baseline.seasonal import SeasonalBaseline
from backend.config import settings
from backend.detector.config import DetectorConfig
from backend.detector.detector import AnomalyDetector
from backend.evaluation.scenarios import ScenarioDefinition
from backend.root_cause import RootCauseAnalyzer
from backend.schemas import (
    DetectionRequest,
    DetectionResponse,
    Diagnosis,
    Incident,
    InjectionConfig,
    Transaction,
    TransactionBatch,
)
from backend.simulator import LiveTransactionSimulator


DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "historical_transactions_2025_seed42.csv"
)


class ControlTowerEvaluationRuntime:
    """Compose the simulator, baseline, detector, and deterministic RCA."""

    def __init__(
        self,
        baseline: SeasonalBaseline,
        root_cause_analyzer: RootCauseAnalyzer | None = None,
    ) -> None:
        self._baseline = baseline
        self._root_cause_analyzer = root_cause_analyzer
        self._simulator: LiveTransactionSimulator | None = None
        self._detector: AnomalyDetector | None = None
        self._directives: tuple[str, ...] = ()
        self._recent_batches: deque[TransactionBatch] = deque(maxlen=2)

    def reset(self, scenario: ScenarioDefinition) -> None:
        self._directives = scenario.directives
        self._recent_batches.clear()
        self._simulator = LiveTransactionSimulator(
            start_time=scenario.start_at,
            transactions_per_window=scenario.volume_per_window,
            seed=scenario.seed,
        )
        self._detector = AnomalyDetector(
            baseline=self._baseline,
            config=DetectorConfig(
                minimum_volume=settings.detector_minimum_volume,
                minimum_absolute_drop=settings.detector_absolute_drop,
                z_score_threshold=settings.detector_z_score_threshold,
                consecutive_windows=settings.detector_consecutive_windows,
            ),
            window_minutes=settings.live_window_minutes,
        )

    def apply_injection(self, config: InjectionConfig) -> None:
        self._require_simulator().activate_injection(config)

    def next_batch(self) -> TransactionBatch:
        batch = self._require_simulator().next_batch()
        if "single_high_value_decline" not in self._directives:
            return batch

        transaction = batch.transactions[0]
        high_value_decline = transaction.model_copy(
            update={"amount": 10_000.0, "status": "declined", "decline_code": "51"}
        )
        return batch.model_copy(
            update={"transactions": [high_value_decline, *batch.transactions[1:]]}
        )

    def detect(self, request: DetectionRequest) -> DetectionResponse:
        # InjectionConfig is intentionally unavailable at this boundary.
        if (
            not self._recent_batches
            or self._recent_batches[-1].window_end != request.batch.window_end
        ):
            self._recent_batches.append(request.batch.model_copy(deep=True))
        return DetectionResponse(incidents=self._require_detector().detect(request.batch))

    def diagnose(self, incident: Incident) -> Diagnosis:
        if self._root_cause_analyzer is None:
            return _unavailable_diagnosis(incident)
        return self._root_cause_analyzer.diagnose(
            incident,
            tuple(self._recent_batches),
        )

    def _require_simulator(self) -> LiveTransactionSimulator:
        if self._simulator is None:
            raise RuntimeError("reset(scenario) must run before using the simulator")
        return self._simulator

    def _require_detector(self) -> AnomalyDetector:
        if self._detector is None:
            raise RuntimeError("reset(scenario) must run before using the detector")
        return self._detector


def build_runtime(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
) -> ControlTowerEvaluationRuntime:
    """Build the default runtime from the reproducible MVP-01 history artifact."""

    resolved_path = str(Path(history_path).resolve())
    baseline, root_cause_analyzer = _load_runtime_components(
        resolved_path,
        settings.baseline_minimum_volume,
    )
    return ControlTowerEvaluationRuntime(
        baseline=baseline,
        root_cause_analyzer=root_cause_analyzer,
    )


@lru_cache(maxsize=4)
def _load_baseline(history_path: str, minimum_volume: int) -> SeasonalBaseline:
    """Backward-compatible baseline loader used by existing integration tests."""

    return _load_runtime_components(history_path, minimum_volume)[0]


@lru_cache(maxsize=4)
def _load_runtime_components(
    history_path: str,
    minimum_volume: int,
) -> tuple[SeasonalBaseline, RootCauseAnalyzer]:
    path = Path(history_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Historical dataset not found at {path}. Run the MVP-01 generation command first."
        )

    frame = pd.read_csv(
        path,
        dtype={"decline_code": "string"},
        usecols=[
            "transaction_id",
            "merchant",
            "provider",
            "payment_method",
            "country",
            "issuing_bank",
            "decline_code",
            "status",
            "amount",
            "timestamp",
        ],
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    training_frame = frame.loc[frame["timestamp"].dt.month.isin((1, 2, 3, 4))].copy()
    # CSV empty cells are parsed as float NaN. Cast first so assigning None is
    # preserved in the records validated by Transaction.
    training_frame["decline_code"] = training_frame["decline_code"].astype(object)
    training_frame.loc[training_frame["decline_code"].isna(), "decline_code"] = None
    transactions = tuple(
        Transaction.model_validate(row)
        for row in training_frame.to_dict(orient="records")
    )
    return (
        SeasonalBaseline(minimum_volume=minimum_volume).fit(transactions),
        RootCauseAnalyzer(transactions),
    )


def _unavailable_diagnosis(incident: Incident) -> Diagnosis:
    return Diagnosis(
        incident_id=incident.incident_id,
        root_cause_dimensions=[],
        evidence=[],
        confidence=0.0,
        diagnosis_status="insufficient_evidence",
        explanation="Historical root-cause evidence is unavailable.",
        recommended_action="Investigate the affected payment route.",
    )
