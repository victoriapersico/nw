
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
from backend.schemas import (
    DetectionRequest,
    DiagnosedIncident,
    InjectionConfig,
    LiveTickResponse,
    Merchant,
    MerchantIncidentsResponse,
)


class LiveControlTower:
    """Owns the demo runtime and exposes safe merchant-scoped results."""

    def __init__(self, runtime: ControlTowerEvaluationRuntime) -> None:
        self._runtime = runtime
        self._lock = RLock()
        self._incidents: dict[str, DiagnosedIncident] = {}

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
            incidents = [
                item
                for item in self._incidents.values()
                if item.incident.merchant == merchant
                and item.incident.status == "active"
            ]
            incidents.sort(
                key=lambda item: (
                    item.incident.estimated_loss,
                    item.incident.anomaly_score,
                ),
                reverse=True,
            )
            return MerchantIncidentsResponse(
                merchant=merchant,
                incidents=incidents,
            )

    def _advance_locked(self) -> LiveTickResponse:
        batch = self._runtime.next_batch()
        detection = self._runtime.detect(DetectionRequest(batch=batch))

        diagnosed_incidents = []
        for incident in detection.incidents:
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
    runtime.reset(
        ScenarioDefinition(
            scenario_id=0,
            name="Live Control Tower demo",
            seed=20_260,
            start_at=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
            expectation=ScenarioExpectation(outcome="no_alert"),
            volume_per_window=DEFAULT_LIVE_VOLUME_PER_WINDOW,
        )
    )
    return LiveControlTower(runtime)