
"""Stateful live Control Tower orchestration for the FastAPI demo."""

from collections import defaultdict, deque
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
    CountryMonitoringMetric,
    MerchantMonitoringResponse,
    MerchantIncidentsResponse,
    TransactionBatch,
)


LIVE_CHART_WINDOWS = 24


class LiveControlTower:
    """Owns the demo runtime and exposes safe merchant-scoped results."""

    def __init__(self, runtime: ControlTowerEvaluationRuntime) -> None:
        self._runtime = runtime
        self._lock = RLock()
        self._incidents: dict[str, DiagnosedIncident] = {}
        self._latest_batch: TransactionBatch | None = None
        self._approval_history: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=LIVE_CHART_WINDOWS)
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

    def monitoring_for(self, merchant: Merchant) -> MerchantMonitoringResponse:
        """Return measured simulator metrics for the latest live window."""

        with self._lock:
            if self._latest_batch is None:
                self._advance_locked()
            assert self._latest_batch is not None
            batch = self._latest_batch
            countries: list[CountryMonitoringMetric] = []
            total_attempts = 0
            total_approved = 0
            total_expected_approved = 0.0

            for country in ("Mexico", "Brazil", "Colombia"):
                transactions = [
                    transaction
                    for transaction in batch.transactions
                    if transaction.merchant == merchant and transaction.country == country
                ]
                attempts = len(transactions)
                if not attempts:
                    continue
                approved = sum(
                    transaction.status == "approved" for transaction in transactions
                )
                actual_rate = approved / attempts
                expected_rate = self._runtime.expected_approval_rate(
                    merchant,
                    country,
                    batch.window_start,
                )
                expected_rate = actual_rate if expected_rate is None else expected_rate
                history = self._approval_history[(merchant, country)]
                countries.append(
                    CountryMonitoringMetric(
                        country=country,
                        actual_approval_rate=actual_rate,
                        expected_approval_rate=expected_rate,
                        attempted_transactions=attempts,
                        approval_history=list(history),
                    )
                )
                total_attempts += attempts
                total_approved += approved
                total_expected_approved += expected_rate * attempts

            return MerchantMonitoringResponse(
                merchant=merchant,
                window_start=batch.window_start,
                window_end=batch.window_end,
                actual_approval_rate=total_approved / total_attempts,
                expected_approval_rate=total_expected_approved / total_attempts,
                attempted_transactions=total_attempts,
                countries=countries,
            )

    def _advance_locked(self) -> LiveTickResponse:
        batch = self._runtime.next_batch()
        self._latest_batch = batch
        for transaction in batch.transactions:
            key = (transaction.merchant, transaction.country)
            # Count once per country after the whole batch is available below.
            self._approval_history.setdefault(key, deque(maxlen=LIVE_CHART_WINDOWS))

        for merchant in ("Rappi", "Carrefour", "Despegar"):
            for country in ("Mexico", "Brazil", "Colombia"):
                outcomes = [
                    transaction.status == "approved"
                    for transaction in batch.transactions
                    if transaction.merchant == merchant and transaction.country == country
                ]
                if outcomes:
                    history = self._approval_history[(merchant, country)]
                    if len(history) >= LIVE_CHART_WINDOWS:
                        history.clear()
                    history.append(sum(outcomes) / len(outcomes))
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
