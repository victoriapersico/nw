from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.live_control_tower import (
    LIVE_CHART_WINDOWS,
    LIVE_HISTORY_DAYS,
    LiveControlTower,
    build_live_control_tower,
)
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


def test_live_history_retains_a_full_simulated_month() -> None:
    assert LIVE_HISTORY_DAYS == 30
    assert LIVE_CHART_WINDOWS == 30 * 24 * 12


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


def test_combined_method_and_bank_injection_is_diagnosed_as_an_intersection() -> None:
    tower = build_live_control_tower()
    tower.inject(
        InjectionConfig(
            merchant="Rappi",
            country="Brazil",
            payment_method="PIX",
            issuing_bank="Itaú",
            target_approval_rate=0.0,
            duration_windows=30,
        )
    )

    diagnosis = tower.incidents_for("Rappi").incidents[0].diagnosis

    assert diagnosis.diagnosis_status == "confirmed"
    assert set(diagnosis.root_cause_dimensions) >= {
        "payment_method",
        "issuing_bank",
    }
    assert any(
        item.dimension == "intersection"
        and "PIX" in item.value
        and "Itaú" in item.value
        for item in diagnosis.evidence
    )


def test_mexico_card_and_provider_injection_is_detected_and_explained() -> None:
    """Protect the Judge Lab path that was reported as intermittently invisible."""

    tower = build_live_control_tower()
    for provider in ("Stripe", "Adyen", "dLocal"):
        tower.reset()
        tower.inject(
            InjectionConfig(
                merchant="Rappi",
                country="Mexico",
                provider=provider,
                payment_method="CARD",
                target_approval_rate=0.0,
                duration_windows=30,
            )
        )

        incidents = tower.incidents_for("Rappi").incidents

        assert len(incidents) == 1
        assert incidents[0].incident.country == "Mexico"
        assert incidents[0].diagnosis.diagnosis_status == "confirmed"
        assert set(incidents[0].diagnosis.root_cause_dimensions) >= {
            "provider",
            "payment_method",
        }


def test_mexico_issuing_bank_injection_is_detected_and_explained() -> None:
    """A bank-only outage must not abstain because it affects card/provider slices."""

    tower = build_live_control_tower()
    tower.inject(
        InjectionConfig(
            merchant="Rappi",
            country="Mexico",
            issuing_bank="Banorte",
            target_approval_rate=0.0,
            duration_windows=30,
        )
    )

    incidents = tower.incidents_for("Rappi").incidents

    assert len(incidents) == 1
    assert incidents[0].incident.country == "Mexico"
    assert incidents[0].diagnosis.diagnosis_status == "confirmed"
    assert incidents[0].diagnosis.root_cause_dimensions == ["issuing_bank"]
    assert incidents[0].diagnosis.evidence[0].value == "Banorte"


def test_bank_injection_is_explained_for_a_smaller_merchant_slice() -> None:
    """Bank-only Judge Lab injections must not be hidden by correlated CARD loss."""

    tower = build_live_control_tower()
    tower.inject(
        InjectionConfig(
            merchant="Despegar",
            country="Colombia",
            issuing_bank="Banco de Bogotá",
            target_approval_rate=0.30,
            duration_windows=30,
        )
    )

    incidents = tower.incidents_for("Despegar").incidents

    assert incidents
    assert any(
        item.diagnosis.diagnosis_status == "confirmed"
        and "issuing_bank" in item.diagnosis.root_cause_dimensions
        for item in incidents
    )


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
