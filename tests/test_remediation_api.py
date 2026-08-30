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


def test_human_approved_simulated_change_has_audit_trail_and_manual_rollback() -> None:
    get_control_tower.cache_clear()


def test_simulated_change_rolls_back_after_two_unhealthy_target_windows() -> None:
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        workflow = client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        )
        assert workflow.status_code == 200
        assert workflow.json()["status"] == "pending_approval"
        selected = next(
            item
            for item in recommendation["alternatives"]
            if item["option"]["option_id"] == recommendation["recommended_option_id"]
        )
        client.post(
            "/remediation/approvals",
            json={
                "decision_id": "approval-rappi-auto-rollback-001",
                "recommendation_id": recommendation["recommendation_id"],
                "decision": "approved",
                "decided_by": "merchant-operator",
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
        ).raise_for_status()
        change = client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rappi-auto-rollback-001",
                "idempotency_key": "change-rappi-auto-rollback-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        )
        change.raise_for_status()

        unhealthy_target = client.post(
            "/injections",
            json={
                "config": {
                    "merchant": "Rappi",
                    "country": "Brazil",
                    "provider": selected["option"]["target_provider"],
                    "target_approval_rate": 0.0,
                    "duration_windows": 2,
                }
            },
        )
        unhealthy_target.raise_for_status()

        final_change = client.get(
            f"/remediation/changes/{change.json()['change_id']}"
        )
        assert final_change.json()["status"] == "rolled_back"
        assert len(final_change.json()["monitoring"]) >= 2
        assert final_change.json()["rollback_reason"].startswith(
            "Automatic simulated rollback"
        )
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)

        denied = client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "missing-decision",
                "idempotency_key": "change-rappi-stripe-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        )
        assert denied.status_code == 403

        approval = client.post(
            "/remediation/approvals",
            json={
                "decision_id": "approval-rappi-change-001",
                "recommendation_id": recommendation["recommendation_id"],
                "decision": "approved",
                "decided_by": "merchant-operator",
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert approval.status_code == 200
        assert client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()["status"] == "approved"

        applied = client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rappi-change-001",
                "idempotency_key": "change-rappi-stripe-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        )
        assert applied.status_code == 200
        change = applied.json()
        assert change["status"] == "simulated_active"
        assert change["simulated"] is True
        assert client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()["status"] == "simulated_active"

        repeated = client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rappi-change-001",
                "idempotency_key": "change-rappi-stripe-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        )
        assert repeated.json()["change_id"] == change["change_id"]

        rolled_back = client.post(
            f"/remediation/changes/{change['change_id']}/rollback",
            json={
                "decided_by": "merchant-operator",
                "reason": "Operator stopped the demo rollout.",
            },
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["status"] == "rolled_back"
        assert client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()["status"] == "rolled_back"

        audit = client.get(
            "/remediation/audit",
            params={"recommendation_id": recommendation["recommendation_id"]},
        )
        assert audit.status_code == 200
        assert [item["event_type"] for item in audit.json()] == [
            "approval_recorded",
            "simulated_change_applied",
            "simulated_change_rolled_back",
        ]
    get_control_tower.cache_clear()


def test_human_can_complete_a_healthy_simulated_change() -> None:
    get_control_tower.cache_clear()
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        client.post(
            "/remediation/approvals",
            json={
                "decision_id": "approval-rappi-complete-001",
                "recommendation_id": recommendation["recommendation_id"],
                "decision": "approved",
                "decided_by": "merchant-operator",
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
        ).raise_for_status()
        change = client.post(
            "/remediation/changes",
            json={
                "recommendation_id": recommendation["recommendation_id"],
                "approval_decision_id": "approval-rappi-complete-001",
                "idempotency_key": "change-rappi-complete-001",
                "rollback_reference": recommendation["rollback_reference"],
            },
        )
        change.raise_for_status()
        completed = client.post(
            f"/remediation/changes/{change.json()['change_id']}/complete",
            json={
                "decided_by": "merchant-operator",
                "note": "Healthy simulation review completed.",
            },
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        assert client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()["status"] == "completed"
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
