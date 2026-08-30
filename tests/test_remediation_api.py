"""Contract tests for POST-01 remediation simulation and execution guardrails."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.main import app, get_control_tower


def _create_recommendation(client: TestClient) -> dict:
    response = client.post(
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
    )
    assert response.status_code == 200
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


def test_remediation_contract_is_dry_run_and_requires_explicit_approval() -> None:
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        assert recommendation["dry_run"] is True
        assert recommendation["policy_id"].startswith("default-rappi-brazil")
        assert recommendation["rollback_reference"]
        assert recommendation["alternatives"]

        execution = client.post(
            "/remediation/executions",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "missing-decision",
                "idempotency_key": "execute-rappi-stripe-001",
                "rollback_reference": recommendation["rollback_reference"],
                "dry_run": False,
            },
        )
        assert execution.status_code == 200
        assert execution.json()["status"] == "denied"
        assert execution.json()["executed"] is False

        approval = client.post(
            "/remediation/approvals",
            json={
                "decision_id": "approval-rappi-stripe-001",
                "recommendation_id": recommendation["recommendation_id"],
                "decision": "approved",
                "decided_by": "merchant-operator",
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert approval.status_code == 200

        dry_run = client.post(
            "/remediation/executions",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rappi-stripe-001",
                "idempotency_key": "execute-rappi-stripe-002",
                "rollback_reference": recommendation["rollback_reference"],
                "dry_run": True,
            },
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["status"] == "dry_run"
        assert dry_run.json()["executed"] is False

        repeated = client.post(
            "/remediation/executions",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rappi-stripe-001",
                "idempotency_key": "execute-rappi-stripe-002",
                "rollback_reference": recommendation["rollback_reference"],
                "dry_run": True,
            },
        )
        assert repeated.json()["execution_id"] == dry_run.json()["execution_id"]
    get_control_tower.cache_clear()
