from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import Transaction
from backend.yuno_mock import (
    MockYunoWebhookIngestor,
    YunoMockWebhookError,
    build_payment_webhook,
    sign_webhook,
)
from scripts.yuno_sandbox import SCENARIOS, build_demo_webhook


def _declined_rappi_transaction() -> Transaction:
    return Transaction(
        transaction_id="txn-yuno-mock-001",
        merchant="Rappi",
        provider="Stripe",
        payment_method="PIX",
        country="Brazil",
        issuing_bank="Itaú",
        decline_code="91",
        status="declined",
        amount=120.50,
        timestamp=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
    )


def test_mock_yuno_webhook_is_verified_normalized_and_deduplicated() -> None:
    payload = build_payment_webhook(
        _declined_rappi_transaction(),
        account_id="yuno-rappi-sandbox",
        event_id="yuno-event-001",
    )
    ingestor = MockYunoWebhookIngestor()

    first = ingestor.ingest(payload, sign_webhook(payload))
    duplicate = ingestor.ingest(payload, sign_webhook(payload))

    assert first.duplicate is False
    assert first.transaction is not None
    assert first.transaction.provider == "Stripe"
    assert duplicate.duplicate is True
    assert duplicate.transaction is None


def test_mock_yuno_webhook_rejects_invalid_signature() -> None:
    payload = build_payment_webhook(
        _declined_rappi_transaction(),
        account_id="yuno-rappi-sandbox",
        event_id="yuno-event-bad-signature",
    )

    with pytest.raises(YunoMockWebhookError, match="invalid x-hmac-signature"):
        MockYunoWebhookIngestor().ingest(payload, "not-a-real-signature")


def test_sandbox_webhook_endpoint_returns_a_receipt() -> None:
    payload = build_payment_webhook(
        _declined_rappi_transaction(),
        account_id="yuno-rappi-sandbox",
        event_id="yuno-event-api-001",
    )

    response = TestClient(app).post(
        "/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": sign_webhook(payload)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "yuno-event-api-001",
        "accepted": True,
        "duplicate": False,
        "transaction_id": "txn-yuno-mock-001",
        "error_code": None,
    }


def test_signed_invalid_transaction_creates_a_yuno_system_alert() -> None:
    payload = build_payment_webhook(
        _declined_rappi_transaction(),
        account_id="yuno-rappi-sandbox",
        event_id="yuno-event-invalid-transaction-001",
    )
    payload["data"]["payment"]["transaction"]["decline_code"] = "91@"

    client = TestClient(app)
    receipt = client.post(
        "/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": sign_webhook(payload)},
    )
    duplicate_receipt = client.post(
        "/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": sign_webhook(payload)},
    )
    alerts = client.get(
        "/v1/sandbox/yuno-system-alerts/yuno-rappi-sandbox"
    ).json()
    emails = client.get("/v1/sandbox/yuno-email-outbox").json()

    assert receipt.status_code == 200
    assert receipt.json()["accepted"] is False
    assert receipt.json()["error_code"] == "transaction_validation_failed"
    assert duplicate_receipt.json()["duplicate"] is True
    assert any(
        alert["source_event_id"] == "yuno-event-invalid-transaction-001"
        and alert["event_type"] == "system.integration_error"
        for alert in alerts
    )
    matching_emails = [
        email
        for email in emails
        if email["source_event_id"] == "yuno-event-invalid-transaction-001"
    ]
    assert len(matching_emails) == 1
    assert matching_emails[0]["to"] == "payments-ops@yuno-sandbox.local"
    assert "transaction_validation_failed" in matching_emails[0]["text_body"]


@pytest.mark.parametrize(
    ("scenario", "expected_error", "expected_field"),
    [
        ("missing_id", "missing_required_field", "transaction_id"),
        ("invalid_amount", "invalid_amount", "amount"),
        ("merchant_mismatch", "merchant_mapping_failed", "merchant"),
        (
            "invalid_method_country",
            "invalid_payment_method_country",
            "payment_method",
        ),
        ("unsupported_schema", "unsupported_webhook_schema", "type/version"),
    ],
)
def test_signed_integration_failures_create_one_alert_and_email(
    scenario: str,
    expected_error: str,
    expected_field: str,
) -> None:
    event_id = f"yuno-event-{scenario}-001"
    payload = build_payment_webhook(
        _declined_rappi_transaction(),
        account_id="yuno-rappi-sandbox",
        event_id=event_id,
    )
    transaction_payload = payload["data"]["payment"]["transaction"]
    if scenario == "missing_id":
        del transaction_payload["transaction_id"]
    elif scenario == "invalid_amount":
        transaction_payload["amount"] = 0
    elif scenario == "merchant_mismatch":
        transaction_payload["merchant"] = "Carrefour"
    elif scenario == "invalid_method_country":
        transaction_payload["payment_method"] = "PSE"
    elif scenario == "unsupported_schema":
        payload["version"] = "99"

    client = TestClient(app)
    first = client.post(
        "/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": sign_webhook(payload)},
    )
    duplicate = client.post(
        "/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": sign_webhook(payload)},
    )
    alerts = client.get(
        "/v1/sandbox/yuno-system-alerts/yuno-rappi-sandbox"
    ).json()
    emails = client.get("/v1/sandbox/yuno-email-outbox").json()

    assert first.status_code == 200
    assert first.json()["accepted"] is False
    assert first.json()["error_code"] == expected_error
    assert duplicate.json()["duplicate"] is True
    matching_alerts = [
        alert for alert in alerts if alert["source_event_id"] == event_id
    ]
    assert len(matching_alerts) == 1
    assert matching_alerts[0]["field_path"].endswith(expected_field)
    assert len([email for email in emails if email["source_event_id"] == event_id]) == 1


def test_invalid_signature_is_rejected_without_alert_or_email() -> None:
    client = TestClient(app)
    alerts_before = client.get(
        "/v1/sandbox/yuno-system-alerts/yuno-rappi-sandbox"
    ).json()
    emails_before = client.get("/v1/sandbox/yuno-email-outbox").json()
    payload = build_payment_webhook(
        _declined_rappi_transaction(),
        account_id="yuno-rappi-sandbox",
        event_id="yuno-event-invalid-signature-001",
    )

    response = client.post(
        "/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": "not-a-real-signature"},
    )

    assert response.status_code == 401
    assert client.get(
        "/v1/sandbox/yuno-system-alerts/yuno-rappi-sandbox"
    ).json() == alerts_before
    assert client.get("/v1/sandbox/yuno-email-outbox").json() == emails_before


def test_demo_scenarios_build_signed_fixtures() -> None:
    for scenario in SCENARIOS:
        payload, signature = build_demo_webhook(scenario)

        assert payload["idempotency_key"] == f"yuno-demo-{scenario}"
        if scenario == "invalid-signature":
            assert signature == "not-a-real-signature"
        else:
            assert signature == sign_webhook(payload)
