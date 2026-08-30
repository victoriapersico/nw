from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.live_control_tower import build_live_control_tower
from backend.live_control_tower import LiveControlTower
from backend.main import app, get_control_tower
from backend.evaluation.scenarios import SCENARIOS
from backend.schemas import (
    DetectionResponse,
    Diagnosis,
    Incident,
    InjectionConfig,
    Transaction,
    TransactionBatch,
)


LIVE_START = datetime(2025, 9, 2, 13, tzinfo=timezone.utc)
STRONG_INJECTION = InjectionConfig(
    merchant="Rappi",
    country="Brazil",
    provider="Stripe",
    target_approval_rate=0.0,
    duration_windows=4,
)


def test_reset_supports_three_clean_inject_detect_cycles() -> None:
    tower = build_live_control_tower()

    for _ in range(3):
        tower.reset()

        assert tower.incidents_for("Rappi").incidents == []
        first_window = tower.tick()
        assert first_window.window_start == LIVE_START
        assert first_window.incidents == []

        tower.inject(STRONG_INJECTION)

        incidents = tower.incidents_for("Rappi").incidents
        assert len(incidents) == 1
        assert incidents[0].incident.merchant == "Rappi"
        assert incidents[0].incident.country == "Brazil"


def test_reset_endpoint_clears_cached_live_state() -> None:
    get_control_tower.cache_clear()
    client = TestClient(app)
    client.post(
        "/injections",
        json={"config": STRONG_INJECTION.model_dump(mode="json")},
    )
    assert client.get("/merchants/Rappi/incidents").json()["incidents"]

    response = client.post("/monitor/reset")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert client.get("/merchants/Rappi/incidents").json()["incidents"] == []
    first_window = client.post("/monitor/tick").json()
    assert first_window["window_start"] == LIVE_START.isoformat().replace("+00:00", "Z")
    get_control_tower.cache_clear()


def test_latest_batch_endpoint_exposes_only_the_real_last_simulator_batch() -> None:
    get_control_tower.cache_clear()
    client = TestClient(app)

    assert client.get("/monitor/latest-batch").status_code == 404

    tick = client.post("/monitor/tick")
    latest = client.get("/monitor/latest-batch")

    assert tick.status_code == 200
    assert latest.status_code == 200
    assert latest.json()["window_start"] == tick.json()["window_start"]
    assert latest.json()["window_end"] == tick.json()["window_end"]
    assert len(latest.json()["transactions"]) == 1_200

    client.post("/monitor/reset")
    assert client.get("/monitor/latest-batch").status_code == 404
    get_control_tower.cache_clear()


class UnorderedLiveRuntime:
    def reset(self, _scenario) -> None:
        pass

    def next_batch(self) -> TransactionBatch:
        return TransactionBatch(
            window_start=LIVE_START,
            window_end=datetime(2025, 9, 2, 13, 5, tzinfo=timezone.utc),
            transactions=[
                Transaction(
                    transaction_id="priority-test",
                    merchant="Rappi",
                    provider="Stripe",
                    payment_method="PIX",
                    country="Brazil",
                    issuing_bank="Itaú",
                    decline_code=None,
                    status="approved",
                    amount=100.0,
                    timestamp=LIVE_START,
                )
            ],
        )

    def detect(self, _request) -> DetectionResponse:
        return DetectionResponse(
            incidents=[
                self._incident("inc-high-loss", "Rappi", "Brazil", "high", 10_000),
                self._incident("inc-critical", "Carrefour", "Mexico", "critical", 1_000),
            ]
        )

    def diagnose(self, incident: Incident) -> Diagnosis:
        return Diagnosis(
            incident_id=incident.incident_id,
            diagnosis_status="insufficient_evidence",
            confidence=0.0,
            explanation="No supported cause.",
            recommended_action="Collect more evidence.",
        )

    @staticmethod
    def _incident(
        incident_id: str,
        merchant: str,
        country: str,
        severity: str,
        loss: float,
    ) -> Incident:
        return Incident(
            incident_id=incident_id,
            merchant=merchant,
            country=country,
            detected_at=datetime(2025, 9, 2, 13, 5, tzinfo=timezone.utc),
            expected_conversion=0.9,
            actual_conversion=0.5,
            conversion_drop_pp=40.0,
            affected_volume=100,
            estimated_loss=loss,
            estimated_loss_per_hour=loss * 12,
            severity=severity,
            anomaly_score=5.0,
        )


def test_live_tick_preserves_incident_engine_priority_order() -> None:
    tower = LiveControlTower(UnorderedLiveRuntime(), SCENARIOS[0])

    response = tower.tick()

    assert [item.incident.incident_id for item in response.incidents] == [
        "inc-critical",
        "inc-high-loss",
    ]
