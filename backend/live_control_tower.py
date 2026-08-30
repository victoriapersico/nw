
"""Stateful live Control Tower orchestration for the FastAPI demo."""

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from backend.ai.diagnosis import narrate_diagnosis
from backend.evaluation.scenarios import (
    DEFAULT_LIVE_VOLUME_PER_WINDOW,
    ScenarioDefinition,
    ScenarioExpectation,
)
from backend.integration.evaluation_runtime import (
    ControlTowerEvaluationRuntime,
    build_runtime,
)
from backend.incidents.engine import IncidentEngine
from backend.schemas import (
    DetectionRequest,
    DiagnosedIncident,
    InjectionConfig,
    LiveTickResponse,
    Merchant,
    MerchantIncidentsResponse,
    TransactionBatch,
)


class LiveControlTower:
    """Owns the demo runtime and exposes safe merchant-scoped results."""

    def __init__(
        self,
        runtime: ControlTowerEvaluationRuntime,
        initial_scenario: ScenarioDefinition,
    ) -> None:
        self._runtime = runtime
        self._initial_scenario = initial_scenario
        self._incident_engine = IncidentEngine()
        self._lock = RLock()
        self._incidents: dict[str, DiagnosedIncident] = {}
        self._latest_batch: TransactionBatch | None = None
        self.reset()

    def reset(self) -> None:
        """Restore the deterministic initial demo state without stale incidents."""

        with self._lock:
            self._runtime.reset(self._initial_scenario)
            self._incidents.clear()
            self._latest_batch = None

    def latest_batch(self) -> TransactionBatch | None:
        """Return a defensive copy of the latest real simulator batch."""

        with self._lock:
            return (
                self._latest_batch.model_copy(deep=True)
                if self._latest_batch is not None
                else None
            )

    def inject(self, config: InjectionConfig) -> str:
        """Apply an injection only to the simulator, then advance two
        windows."""

        with self._lock:
            self._runtime.apply_injection(config)

            # The detector requires two consecutive anomalous time windows.
            self._advance_locked()
            self._advance_locked()

            return f"inj-{uuid4().hex}"

    def tick(self) -> LiveTickResponse:
        """Advance one simulated five-minute monitoring window."""

        with self._lock:
            return self._advance_locked()

    def incidents_for(self, merchant: Merchant) -> MerchantIncidentsResponse:
        """Return active incidents only for the requested merchant."""

        with self._lock:
            diagnosed_incidents = [
                item
                for item in self._incidents.values()
                if item.incident.merchant == merchant
                and item.incident.status == "active"
            ]
            ordered = self._incident_engine.process(
                [item.incident for item in diagnosed_incidents]
            )
            by_id = {
                item.incident.incident_id: item for item in diagnosed_incidents
            }
            return MerchantIncidentsResponse(
                merchant=merchant,
                incidents=[by_id[incident.incident_id] for incident in ordered],
            )

    def _advance_locked(self) -> LiveTickResponse:
        batch = self._runtime.next_batch()
        self._latest_batch = batch.model_copy(deep=True)
        detection = self._runtime.detect(DetectionRequest(batch=batch))

        diagnosed_incidents = []
        for incident in self._incident_engine.process(detection.incidents):
            diagnosis = narrate_diagnosis(self._runtime.diagnose(incident))
            diagnosed = DiagnosedIncident(
                incident=incident,
                diagnosis=diagnosis,
            )
            self._incidents[incident.incident_id] = diagnosed
            diagnosed_incidents.append(diagnosed)

        return LiveTickResponse(
            window_start=batch.window_start,
            window_end=batch.window_end,
            incidents=diagnosed_incidents,
        )


def build_live_control_tower() -> LiveControlTower:
    """Build the default accelerated demo runtime from local history."""

    runtime = build_runtime()
    initial_scenario = ScenarioDefinition(
        scenario_id=0,
        name="Live Control Tower demo",
        seed=20_260,
        start_at=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
        expectation=ScenarioExpectation(outcome="no_alert"),
        volume_per_window=DEFAULT_LIVE_VOLUME_PER_WINDOW,
    )
    return LiveControlTower(runtime, initial_scenario)
