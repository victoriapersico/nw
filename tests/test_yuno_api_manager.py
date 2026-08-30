"""Contract tests for the separate local Yuno API Manager sandbox."""

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.yuno_sandbox import YUNO_ACCOUNT_ID, YunoSandbox, sign_webhook


@pytest.fixture(autouse=True)
def isolated_yuno_sandbox(monkeypatch):
    """Keep API Manager telemetry deterministic and isolated per test."""

    monkeypatch.setattr(main_module, "yuno_sandbox", YunoSandbox())


def test_yuno_api_manager_seeds_a_healthy_local_baseline() -> None:
    with TestClient(main_module.app) as client:
        seeded = client.post("/v1/sandbox/yuno-api-demo-seed")
        health = client.get("/v1/sandbox/yuno-api-health")

    assert seeded.status_code == 200
    assert seeded.json()["status"] == "healthy"
    assert seeded.json()["total_requests"] == 14
    assert health.json()["success_rate"] == 12 / 14
    assert health.json()["duplicate_requests"] == 2


def test_trusted_yuno_failure_creates_local_alert_email_and_telemetry() -> None:
    with TestClient(main_module.app) as client:
        result = client.post("/v1/sandbox/yuno-api-demo-events/invalid-amount")
        alerts = client.get(f"/v1/sandbox/yuno-system-alerts/{YUNO_ACCOUNT_ID}")
        emails = client.get("/v1/sandbox/yuno-email-outbox")
        health = client.get("/v1/sandbox/yuno-api-health")
        activity = client.get("/v1/sandbox/yuno-api-log")

    assert result.status_code == 200
    assert result.json()["accepted"] is False
    assert result.json()["error_code"] == "invalid_amount"
    assert alerts.json()[0]["error_code"] == "invalid_amount"
    assert "invalid_amount" in emails.json()[0]["subject"]
    assert health.json()["status"] == "degraded"
    assert activity.json()[0]["outcome"] == "rejected"


def test_untrusted_webhook_is_rejected_without_operations_alert_noise() -> None:
    payload = {
        "idempotency_key": "untrusted-yuno-event",
        "account_id": YUNO_ACCOUNT_ID,
    }
    with TestClient(main_module.app) as client:
        response = client.post("/v1/sandbox/yuno-webhooks", json=payload)
        alerts = client.get(f"/v1/sandbox/yuno-system-alerts/{YUNO_ACCOUNT_ID}")
        health = client.get("/v1/sandbox/yuno-api-health")

    assert response.status_code == 401
    assert alerts.json() == []
    assert health.json()["unauthorized_requests"] == 1
    assert health.json()["rejected_requests"] == 0


def test_signed_sandbox_webhook_is_accepted_and_deduplicated() -> None:
    payload = {
        "idempotency_key": "signed-yuno-event",
        "account_id": YUNO_ACCOUNT_ID,
    }
    headers = {"x-hmac-signature": sign_webhook(payload)}
    with TestClient(main_module.app) as client:
        accepted = client.post(
            "/v1/sandbox/yuno-webhooks", json=payload, headers=headers
        )
        duplicate = client.post(
            "/v1/sandbox/yuno-webhooks", json=payload, headers=headers
        )
        health = client.get("/v1/sandbox/yuno-api-health")

    assert accepted.json() == {
        "event_id": "signed-yuno-event",
        "accepted": True,
        "duplicate": False,
        "error_code": None,
    }
    assert duplicate.json()["duplicate"] is True
    assert health.json()["accepted_requests"] == 1
    assert health.json()["duplicate_requests"] == 1
