"""API coverage for the local notification and deterministic-memory slice."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from backend.incidents.memory_store import IncidentMemoryStore
from backend.main import app, get_control_tower
from backend.schemas import (
    DeclineCodePatternEntry,
    Diagnosis,
    Incident,
    IncidentFingerprint,
    IncidentMemoryCase,
)


@pytest.fixture(autouse=True)
def isolated_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_DB", str(tmp_path / "incident-memory.sqlite3"))
    monkeypatch.setenv("REMEDIATION_AUDIT_DB", str(tmp_path / "audit.sqlite3"))
    get_control_tower.cache_clear()
    yield
    get_control_tower.cache_clear()


def _inject_same_failure(client: TestClient) -> str:
    response = client.post(
        "/injections",
        json={
            "config": {
                "merchant": "Rappi",
                "country": "Brazil",
                "provider": "Stripe",
                "payment_method": "PIX",
                "decline_code": "91",
                "target_approval_rate": 0.0,
                "duration_windows": 4,
            }
        },
    )
    response.raise_for_status()
    incidents = client.get("/merchants/Rappi/incidents")
    incidents.raise_for_status()
    return incidents.json()["incidents"][0]["incident"]["incident_id"]


def test_incident_alerts_are_acknowledgeable_and_report_is_persisted() -> None:
    with TestClient(app) as client:
        incident_id = _inject_same_failure(client)

        alerts = client.get("/alerts", params={"acknowledged": False})
        alerts.raise_for_status()
        alert_types = {alert["type"] for alert in alerts.json()}
        assert {"incident_detected", "approval_required"} <= alert_types

        incident_alert = next(
            alert for alert in alerts.json() if alert["type"] == "incident_detected"
        )
        acknowledged = client.post(
            f"/alerts/{incident_alert['alert_id']}/acknowledge",
            json={"acknowledged_by": "merchant-operator"},
        )
        acknowledged.raise_for_status()
        assert acknowledged.json()["acknowledged"] is True
        assert client.get("/alerts", params={"acknowledged": False}).json()

        report = client.post(f"/incidents/{incident_id}/post-incident-report")
        report.raise_for_status()
        assert report.json()["incident_id"] == incident_id
        assert report.json()["incident"]["estimated_loss"] >= 0
        assert report.json()["recommendation"] is not None
        assert report.json()["outcome"] == "open"
        assert report.json()["monitoring_outcome"]["status"] == "not_simulated"
        assert report.json()["evidence"]
        assert client.get(f"/incidents/{incident_id}/post-incident-report").json() == report.json()


def test_demo_reset_clears_local_alert_and_audit_history() -> None:
    with TestClient(app) as client:
        _inject_same_failure(client)
        assert client.get("/alerts").json()
        assert client.get("/remediation/audit").json()

        reset = client.post("/monitor/reset")

        assert reset.status_code == 200
        assert client.get("/alerts").json() == []
        assert client.get("/remediation/audit").json() == []


def test_terminal_report_persists_decision_monitoring_and_recurrence() -> None:
    with TestClient(app) as client:
        incident_id = _inject_same_failure(client)
        diagnosed = next(
            item
            for item in client.get("/merchants/Rappi/incidents").json()["incidents"]
            if item["incident"]["incident_id"] == incident_id
        )
        recommendation = diagnosed["remediation"]
        assert recommendation is not None

        decision_id = "approval-incident-memory-001"
        approval = client.post(
            "/remediation/approvals",
            json={
                "decision_id": decision_id,
                "recommendation_id": recommendation["recommendation_id"],
                "merchant": "Rappi",
                "decision": "approved",
                "decided_by": "merchant-operator",
                "decided_at": datetime.now(timezone.utc).isoformat(),
                "idempotency_key": "approve-incident-memory-001",
            },
        )
        approval.raise_for_status()

        change = client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": decision_id,
                "idempotency_key": "change-incident-memory-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        )
        change.raise_for_status()
        client.post("/monitor/tick").raise_for_status()
        completed = client.post(
            f"/remediation/changes/{change.json()['change_id']}/complete",
            json={
                "decided_by": "merchant-operator",
                "note": "Monitoring matched the expected simulated outcome.",
            },
        )
        completed.raise_for_status()

        report_response = client.get(
            f"/incidents/{incident_id}/post-incident-report"
        )
        report_response.raise_for_status()
        report = report_response.json()
        assert report["outcome"] == "completed"
        assert report["incident"]["estimated_loss_per_hour"] > 0
        assert report["recommendation"]["recommendation_id"] == recommendation[
            "recommendation_id"
        ]
        assert report["decision"]["status"] == "approved"
        assert report["change"]["status"] == "completed"
        assert report["monitoring_outcome"]["status"] == "completed"
        assert report["monitoring_outcome"]["observed_windows"] >= 1
        assert report["monitoring_outcome"]["observed_attempts"] > 0
        assert report["monitoring_outcome"]["observed_approval_rate"] is not None
        assert "Estimated loss" in report["summary"]
        assert "Human decision" in report["summary"]
        report_id = report["report_id"]

        regenerated = client.post(
            f"/incidents/{incident_id}/post-incident-report"
        )
        regenerated.raise_for_status()
        assert regenerated.json()["report_id"] == report_id

    get_control_tower.cache_clear()
    with TestClient(app) as restarted_client:
        persisted = restarted_client.get(
            f"/incidents/{incident_id}/post-incident-report"
        )
        persisted.raise_for_status()
        assert persisted.json()["report_id"] == report_id
        assert persisted.json()["monitoring_outcome"]["status"] == "completed"

        restarted_client.post("/monitor/tick").raise_for_status()
        repeated_incident_id = _inject_same_failure(restarted_client)
        assert repeated_incident_id != incident_id
        similar_response = restarted_client.get(
            f"/incidents/{repeated_incident_id}/similar-cases"
        )
        similar_response.raise_for_status()
        prior = next(
            item
            for item in similar_response.json()
            if item["incident_id"] == incident_id
        )
        assert prior["estimated_loss_per_hour"] > 0
        assert prior["recommendation"]["recommendation_id"] == recommendation[
            "recommendation_id"
        ]
        assert prior["decision"]["status"] == "approved"
        assert prior["monitoring_outcome"]["status"] == "completed"
        assert prior["monitoring_outcome"]["observed_windows"] >= 1
        assert prior["outcome"] == "completed"


def test_memory_returns_only_exact_deterministic_fingerprint_matches(tmp_path) -> None:
    store = IncidentMemoryStore(tmp_path / "memory.sqlite3")
    fingerprint = IncidentFingerprint(
        merchant="Rappi",
        country="Brazil",
        provider="Stripe",
        payment_method="PIX",
        decline_pattern=[DeclineCodePatternEntry(code="91", decline_count=20)],
    )

    def case(incident_id: str, pattern_code: str) -> IncidentMemoryCase:
        incident = Incident(
            incident_id=incident_id,
            merchant="Rappi",
            country="Brazil",
            detected_at=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
            expected_conversion=0.9,
            actual_conversion=0.5,
            conversion_drop_pp=40,
            affected_volume=100,
            estimated_loss=1_000,
            estimated_loss_per_hour=12_000,
            severity="high",
            anomaly_score=5,
        )
        diagnosis = Diagnosis(
            incident_id=incident_id,
            diagnosis_status="insufficient_evidence",
            confidence=0,
            explanation="No supported cause.",
            recommended_action="Collect more evidence.",
        )
        return IncidentMemoryCase(
            incident=incident,
            diagnosis=diagnosis,
            fingerprint=fingerprint.model_copy(
                update={
                    "decline_pattern": [
                        DeclineCodePatternEntry(code=pattern_code, decline_count=20)
                    ]
                }
            ),
        )

    store.upsert_case(case("inc-exact", "91"))
    store.upsert_case(case("inc-different-pattern", "96"))

    assert [
        item.incident.incident_id
        for item in store.similar_cases(fingerprint, exclude_incident_id="inc-current")
    ] == ["inc-exact"]
