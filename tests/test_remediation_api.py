"""Contract tests for POST-01 and POST-03 remediation safety guardrails."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.main import app, get_control_tower


def _create_recommendation(client: TestClient) -> dict:
    assert client.post(
        "/injections",
        json={
            "config": {
                "merchant": "Rappi",
                "country": "Brazil",
                "provider": "Stripe",
                "target_approval_rate": 0.0,
                "duration_windows": 4,
            }
        },
    ).status_code == 200
    incident = client.get("/merchants/Rappi/incidents").json()["incidents"][0]
    response = client.post(
        "/remediation/simulations",
        json={
            "merchant": "Rappi",
            "incident_id": incident["incident"]["incident_id"],
            "dry_run": True,
            "idempotency_key": "simulate-rappi-stripe-001",
        },
    )
    assert response.status_code == 200
    return response.json()


def _approval_payload(recommendation: dict, decision_id: str, **overrides: object) -> dict:
    payload = {
        "decision_id": decision_id,
        "recommendation_id": recommendation["recommendation_id"],
        "merchant": "Rappi",
        "decision": "approved",
        "decided_by": "merchant-operator",
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": f"idem-{decision_id}",
    }
    payload.update(overrides)
    return payload


def test_execution_requires_current_matching_approval_and_stays_dry_run() -> None:
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        denied = client.post(
            "/remediation/executions",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "missing-decision",
                "idempotency_key": "execute-rappi-stripe-001",
                "rollback_reference": recommendation["rollback_reference"],
                "dry_run": False,
            },
        )
        assert denied.json()["status"] == "denied"

        approval = client.post(
            "/remediation/approvals",
            json=_approval_payload(recommendation, "approval-execution-001"),
        )
        assert approval.status_code == 200
        dry_run = client.post(
            "/remediation/executions",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-execution-001",
                "idempotency_key": "execute-rappi-stripe-002",
                "rollback_reference": recommendation["rollback_reference"],
                "dry_run": True,
            },
        )
        assert dry_run.json()["status"] == "dry_run"
        assert dry_run.json()["executed"] is False
    get_control_tower.cache_clear()


def test_approval_captures_evidence_and_is_idempotent() -> None:
    get_control_tower.cache_clear()


def test_approval_rejects_a_merchant_that_does_not_own_the_incident() -> None:
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        response = client.post(
            "/remediation/approvals",
            json=_approval_payload(
                recommendation,
                "approval-wrong-merchant-001",
                merchant="Carrefour",
            ),
        )
        assert response.status_code == 403
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        payload = _approval_payload(recommendation, "approval-linked-001")
        approval = client.post("/remediation/approvals", json=payload)
        assert approval.status_code == 200
        data = approval.json()
        assert data["status"] == "approved"
        assert data["merchant"] == "Rappi"
        assert data["incident_id"] == recommendation["incident_id"]
        assert data["simulation_option_id"] == recommendation["recommended_option_id"]
        assert data["reviewed_simulation"]["status"] == "eligible"
        assert data["reviewed_evidence"]

        duplicate = client.post("/remediation/approvals", json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["decision_id"] == data["decision_id"]
        assert client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()["status"] == "approved"
    get_control_tower.cache_clear()


def test_rejected_expired_and_revoked_approvals_cannot_activate_change() -> None:
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        rejected = client.post(
            "/remediation/approvals",
            json=_approval_payload(
                recommendation, "approval-rejected-001", decision="rejected"
            ),
        )
        assert rejected.json()["status"] == "rejected"
        assert client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rejected-001",
                "idempotency_key": "change-rejected-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        ).status_code == 403
    get_control_tower.cache_clear()

    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        expired = client.post(
            "/remediation/approvals",
            json=_approval_payload(
                recommendation,
                "approval-expired-001",
                expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            ),
        )
        assert expired.json()["status"] == "expired"
        assert client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-expired-001",
                "idempotency_key": "change-expired-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        ).status_code == 403
    get_control_tower.cache_clear()

    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        client.post(
            "/remediation/approvals",
            json=_approval_payload(recommendation, "approval-revoked-001"),
        ).raise_for_status()
        revoked = client.post(
            "/remediation/approvals/approval-revoked-001/revoke",
            json={
                "merchant": "Rappi",
                "revoked_by": "merchant-operator",
                "reason": "The operator changed the incident assessment.",
            },
        )
        assert revoked.json()["status"] == "revoked"
        assert client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-revoked-001",
                "idempotency_key": "change-revoked-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        ).status_code == 403
    get_control_tower.cache_clear()
