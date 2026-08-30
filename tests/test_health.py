from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_monitoring_endpoint_exposes_real_simulator_metrics() -> None:
    response = client.get("/merchants/Rappi/monitoring")

    assert response.status_code == 200
    payload = response.json()
    assert payload["merchant"] == "Rappi"
    assert payload["attempted_transactions"] > 0
    assert 0 <= payload["actual_approval_rate"] <= 1
    assert {item["country"] for item in payload["countries"]} == {
        "Mexico",
        "Brazil",
        "Colombia",
    }
    assert all(item["approval_history"] for item in payload["countries"])
