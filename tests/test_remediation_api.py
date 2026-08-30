"""End-to-end contracts for recommendation and human-approved dry-run routing."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app, get_control_tower


@pytest.fixture(autouse=True)
def clean_control_tower(tmp_path, monkeypatch):
    """Give each test an isolated persistent audit database and runtime."""

    monkeypatch.setenv(
        "REMEDIATION_AUDIT_DB",
        str(tmp_path / "remediation-audit.sqlite3"),
    )
    get_control_tower.cache_clear()
    yield
    get_control_tower.cache_clear()


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


def _approval_payload(
    recommendation: dict,
    decision_id: str,
    **overrides: object,
) -> dict:
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


def _record_approval(
    client: TestClient,
    recommendation: dict,
    decision_id: str,
    *,
    decision: str = "approved",
) -> dict:
    response = client.post(
        "/remediation/approvals",
        json=_approval_payload(
            recommendation,
            decision_id,
            decision=decision,
        ),
    )
    assert response.status_code == 200
    return response.json()


def _apply_change(
    client: TestClient,
    recommendation: dict,
    decision_id: str,
    idempotency_key: str,
):
    return client.post(
        "/remediation/changes",
        json={
            "recommendation_id": recommendation["recommendation_id"],
            "approval_decision_id": decision_id,
            "idempotency_key": idempotency_key,
            "rollback_reference": recommendation["rollback_reference"],
        },
    )


def test_recommendation_enters_pending_approval_and_is_persisted() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)

        assert recommendation["status"] == "recommended"
        assert recommendation["dry_run"] is True
        assert recommendation["required_approval"] == "merchant_operations"
        assert recommendation["confidence"] > 0
        assert recommendation["proposed_traffic_cap"] in (0.25, 0.50)
        assert recommendation["rollback_reference"]

        workflow = client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        )
        assert workflow.status_code == 200
        assert workflow.json()["status"] == "pending_approval"
        assert workflow.json()["approval_decision_id"] is None

        audit = client.get(
            "/remediation/audit",
            params={"recommendation_id": recommendation["recommendation_id"]},
        ).json()
        assert [event["event_type"] for event in audit] == [
            "recommendation_created"
        ]
        assert audit[0]["recommendation"] == recommendation


def test_legacy_execution_contract_stays_dry_run_and_idempotent() -> None:
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
        assert denied.json()["executed"] is False

        decision_id = "approval-rappi-stripe-001"
        _record_approval(client, recommendation, decision_id)
        payload = {
            "recommendation_id": recommendation["recommendation_id"],
            "approval_decision_id": decision_id,
            "idempotency_key": "execute-rappi-stripe-002",
            "rollback_reference": recommendation["rollback_reference"],
            "dry_run": True,
        }
        first = client.post("/remediation/executions", json=payload)
        repeated = client.post("/remediation/executions", json=payload)

        assert first.json()["status"] == "dry_run"
        assert first.json()["executed"] is False
        assert repeated.json()["execution_id"] == first.json()["execution_id"]


def test_approval_captures_evidence_and_is_idempotent() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        payload = _approval_payload(recommendation, "approval-linked-001")

        approval = client.post("/remediation/approvals", json=payload)
        duplicate = client.post("/remediation/approvals", json=payload)

        assert approval.status_code == 200
        data = approval.json()
        assert data["status"] == "approved"
        assert data["merchant"] == "Rappi"
        assert data["incident_id"] == recommendation["incident_id"]
        assert data["simulation_option_id"] == recommendation["recommended_option_id"]
        assert data["reviewed_simulation"]["status"] == "eligible"
        assert data["reviewed_evidence"]
        assert duplicate.status_code == 200
        assert duplicate.json()["decision_id"] == data["decision_id"]

        workflow = client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()
        assert workflow["status"] == "approved"
        assert workflow["approval_decision_id"] == data["decision_id"]


def test_approval_rejects_a_merchant_that_does_not_own_the_incident() -> None:
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


def test_human_approved_change_exposes_metrics_audit_and_manual_rollback() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        decision_id = "approval-rappi-change-001"

        denied = _apply_change(
            client,
            recommendation,
            "missing-decision",
            "change-rappi-missing-001",
        )
        assert denied.status_code == 403

        _record_approval(client, recommendation, decision_id)
        approved_workflow = client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()
        assert approved_workflow["status"] == "approved"
        assert approved_workflow["approval_decision_id"] == decision_id

        applied = _apply_change(
            client,
            recommendation,
            decision_id,
            "change-rappi-stripe-001",
        )
        assert applied.status_code == 200
        change = applied.json()
        assert change["status"] == "simulated_active"
        assert change["simulated"] is True
        assert 0 <= change["before_approval_rate"] <= 1
        assert change["expected_approval_rate"] is not None
        assert change["expected_recovered_value_per_hour"] > 0

        repeated = _apply_change(
            client,
            recommendation,
            decision_id,
            "change-rappi-stripe-001",
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

        audit = client.get(
            "/remediation/audit",
            params={"recommendation_id": recommendation["recommendation_id"]},
        ).json()
        assert [item["event_type"] for item in audit] == [
            "recommendation_created",
            "approval_recorded",
            "simulated_change_applied",
            "simulated_change_rolled_back",
        ]


def test_rejected_recommendation_cannot_be_applied() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        decision_id = "approval-rappi-rejected-001"
        _record_approval(
            client,
            recommendation,
            decision_id,
            decision="rejected",
        )

        workflow = client.get(
            f"/remediation/workflows/{recommendation['recommendation_id']}"
        ).json()
        assert workflow["status"] == "rejected"
        rejected = _apply_change(
            client,
            recommendation,
            decision_id,
            "change-rappi-rejected-001",
        )
        assert rejected.status_code == 403


def test_expired_approval_cannot_activate_a_change() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        response = client.post(
            "/remediation/approvals",
            json=_approval_payload(
                recommendation,
                "approval-expired-001",
                expires_at=(
                    datetime.now(timezone.utc) - timedelta(minutes=1)
                ).isoformat(),
            ),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "expired"
        assert _apply_change(
            client,
            recommendation,
            "approval-expired-001",
            "change-expired-001",
        ).status_code == 403


def test_approved_decision_can_be_revoked_before_activation() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        decision_id = "approval-revoked-001"
        _record_approval(client, recommendation, decision_id)

        revoked = client.post(
            f"/remediation/approvals/{decision_id}/revoke",
            json={
                "merchant": "Rappi",
                "revoked_by": "merchant-operator",
                "reason": "The operator changed the incident assessment.",
            },
        )

        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        assert _apply_change(
            client,
            recommendation,
            decision_id,
            "change-revoked-001",
        ).status_code == 403


def test_simulated_change_rolls_back_after_two_unhealthy_target_windows() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        selected = next(
            item
            for item in recommendation["alternatives"]
            if item["option"]["option_id"] == recommendation["recommended_option_id"]
        )
        decision_id = "approval-rappi-auto-rollback-001"
        _record_approval(client, recommendation, decision_id)
        change = _apply_change(
            client,
            recommendation,
            decision_id,
            "change-rappi-auto-rollback-001",
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
        ).json()
        assert final_change["status"] == "rolled_back"
        assert len(final_change["monitoring"]) >= 2
        assert all(
            window["error_rate"] is not None
            for window in final_change["monitoring"][-2:]
        )
        assert final_change["rollback_reason"].startswith(
            "Automatic simulated rollback"
        )


def test_human_can_complete_a_healthy_simulated_change() -> None:
    with TestClient(app) as client:
        recommendation = _create_recommendation(client)
        decision_id = "approval-rappi-complete-001"
        _record_approval(client, recommendation, decision_id)
        change = _apply_change(
            client,
            recommendation,
            decision_id,
            "change-rappi-complete-001",
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

        second_rollback = client.post(
            f"/remediation/changes/{change.json()['change_id']}/rollback",
            json={
                "decided_by": "merchant-operator",
                "reason": "Late rollback should be rejected.",
            },
        )
        assert second_rollback.status_code == 422
