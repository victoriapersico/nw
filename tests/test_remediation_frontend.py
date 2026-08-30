from unittest.mock import Mock, patch

import pytest
import requests
from streamlit.testing.v1 import AppTest

from frontend.remediation_client import (
    RemediationClientError,
    apply_simulated_change,
    complete_simulated_change,
    fetch_audit,
    fetch_simulated_change,
    fetch_workflow,
    record_decision,
    revoke_approval,
    rollback_simulated_change,
)
from frontend.remediation_ui import WORKFLOW_STATES


def _render_workflow_for_test() -> None:
    from frontend.remediation_ui import render_routing_workflow

    render_routing_workflow(
        "http://control-tower.test",
        {
            "recommendation_id": "rec-ui-test",
            "merchant": "Rappi",
            "status": "recommended",
            "rollback_reference": "rollback-ui-test",
        },
    )


def _render_incomplete_panel_for_test() -> None:
    from frontend.remediation_ui import render_remediation_panel

    render_remediation_panel(
        "http://control-tower.test",
        {
            "recommendation_id": "rec-incomplete",
            "merchant": "Rappi",
            "status": "recommended",
            "target_provider": None,
            "traffic_cap": None,
            "rationale": "The selected alternative is not ready.",
        },
        "Continue monitoring.",
    )


def _render_recommended_panel_for_test() -> None:
    from frontend.remediation_ui import render_remediation_panel

    render_remediation_panel(
        "http://control-tower.test",
        {
            "recommendation_id": "rec-ui-test",
            "merchant": "Rappi",
            "status": "recommended",
            "target_provider": "Adyen",
            "traffic_cap": 0.25,
            "expected_recovery_per_hour": 4200.0,
            "expected_approval_rate": 0.88,
            "confidence": 0.91,
            "rationale": "Adyen is the healthiest eligible route.",
            "rollback_reference": "rollback-ui-test",
        },
        "Continue monitoring.",
    )


def _workflow(status: str) -> dict[str, object]:
    workflow: dict[str, object] = {
        "recommendation_id": "rec-ui-test",
        "incident_id": "inc-ui-test",
        "status": status,
        "approval_decision_id": None,
        "change_id": None,
        "updated_at": "2026-08-30T12:00:00Z",
        "transition_reason": f"Workflow moved to {status}.",
    }
    if status in {
        "approved",
        "simulated_active",
        "rolled_back",
        "completed",
    }:
        workflow["approval_decision_id"] = "approval-ui-test"
    if status in {"simulated_active", "rolled_back", "completed"}:
        workflow["change_id"] = "change-ui-test"
    return workflow


def _change(status: str = "simulated_active") -> dict[str, object]:
    return {
        "change_id": "change-ui-test",
        "recommendation_id": "rec-ui-test",
        "approval_decision_id": "approval-ui-test",
        "merchant": "Rappi",
        "country": "Brazil",
        "target_provider": "Adyen",
        "traffic_shift_pct": 0.25,
        "before_approval_rate": 0.64,
        "expected_approval_rate": 0.88,
        "expected_recovered_value_per_hour": 4200.0,
        "status": status,
        "rollback_reason": (
            "Operator reverted the local simulation."
            if status == "rolled_back"
            else None
        ),
        "monitoring": [
            {
                "window_end": "2026-08-30T12:05:00Z",
                "attempted_transactions": 120,
                "approval_rate": 0.86,
                "error_rate": 0.03,
            }
        ],
    }


def _button_labels(app: AppTest) -> set[str]:
    return {button.label for button in app.button}


@pytest.mark.parametrize(
    ("status", "expected_buttons"),
    [
        ("pending_approval", {"Approve recommendation", "Reject"}),
        ("approved", {"Simulate application", "Revoke approval"}),
        ("rejected", set()),
        ("expired", set()),
        ("revoked", set()),
        (
            "simulated_active",
            {"Revert simulated change", "Complete review"},
        ),
        ("rolled_back", set()),
        ("completed", set()),
    ],
)
def test_all_workflow_states_render_only_valid_actions(
    status: str,
    expected_buttons: set[str],
) -> None:
    with (
        patch(
            "frontend.remediation_ui.fetch_workflow",
            return_value=_workflow(status),
        ),
        patch(
            "frontend.remediation_ui.fetch_simulated_change",
            return_value=_change(status),
        ),
        patch("frontend.remediation_ui.fetch_audit", return_value=[]),
    ):
        app = AppTest.from_function(_render_workflow_for_test).run(timeout=20)

    assert not app.exception
    assert _button_labels(app) == expected_buttons


def test_pending_approval_advances_to_simulated_active_from_the_ui() -> None:
    current_status = {"value": "pending_approval"}

    def fetch_current_workflow(*_args: object) -> dict[str, object]:
        return _workflow(current_status["value"])

    def approve(*_args: object, **_kwargs: object) -> dict[str, str]:
        current_status["value"] = "approved"
        return {"status": "approved"}

    def apply(*_args: object, **_kwargs: object) -> dict[str, str]:
        current_status["value"] = "simulated_active"
        return {"status": "simulated_active"}

    with (
        patch(
            "frontend.remediation_ui.fetch_workflow",
            side_effect=fetch_current_workflow,
        ),
        patch("frontend.remediation_ui.fetch_audit", return_value=[]),
        patch(
            "frontend.remediation_ui.fetch_simulated_change",
            return_value=_change(),
        ),
        patch("frontend.remediation_ui.record_decision", side_effect=approve) as decision,
        patch("frontend.remediation_ui.apply_simulated_change", side_effect=apply) as change,
    ):
        app = AppTest.from_function(_render_workflow_for_test).run(timeout=20)
        app.button(key="approve-rec-ui-test").click().run(timeout=20)
        assert "Simulate application" in _button_labels(app)

        app.button(key="apply-rec-ui-test").click().run(timeout=20)

    assert not app.exception
    assert "Complete review" in _button_labels(app)
    decision.assert_called_once()
    change.assert_called_once()
    assert decision.call_args.kwargs["operation_id"]
    assert change.call_args.kwargs["operation_id"]


def test_incomplete_recommendation_never_exposes_approval_actions() -> None:
    with (
        patch("frontend.remediation_ui.fetch_audit", return_value=[]),
        patch("frontend.remediation_ui.fetch_workflow") as workflow,
    ):
        app = AppTest.from_function(_render_incomplete_panel_for_test).run(timeout=20)

    assert not app.exception
    assert not app.button
    assert not workflow.called


def test_recommended_panel_shows_evidence_bound_summary_metrics() -> None:
    with (
        patch(
            "frontend.remediation_ui.fetch_workflow",
            return_value=_workflow("pending_approval"),
        ),
        patch("frontend.remediation_ui.fetch_audit", return_value=[]),
    ):
        app = AppTest.from_function(_render_recommended_panel_for_test).run(timeout=20)

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics == {
        "Estimated recovery / hour": "US$ 4,200",
        "Expected approval": "88.0%",
        "Confidence": "91.0%",
    }
    assert "Approve recommendation" in _button_labels(app)


def test_remediation_client_uses_the_safe_workflow_endpoints() -> None:
    response = Mock(ok=True)
    response.json.return_value = {}

    audit_response = Mock(ok=True)
    audit_response.json.return_value = []

    with patch(
        "frontend.remediation_client.requests.request",
        side_effect=[
            response,
            response,
            response,
            response,
            response,
            response,
            response,
            audit_response,
        ],
    ) as request:
        record_decision(
            "http://api.test",
            "rec-1",
            "Rappi",
            "approved",
            operation_id="decision-1",
        )
        apply_simulated_change(
            "http://api.test",
            "rec-1",
            "approval-1",
            "rollback-1",
            operation_id="apply-1",
        )
        revoke_approval("http://api.test", "approval-1", "Rappi")
        rollback_simulated_change("http://api.test", "change-1")
        complete_simulated_change("http://api.test", "change-1")
        fetch_workflow("http://api.test", "rec-1")
        fetch_simulated_change("http://api.test", "change-1")
        fetch_audit("http://api.test", "rec-1")

    calls = request.call_args_list
    assert [call.args[0] for call in calls] == [
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "GET",
        "GET",
    ]
    assert [call.args[1].removeprefix("http://api.test") for call in calls] == [
        "/remediation/approvals",
        "/remediation/changes",
        "/remediation/approvals/approval-1/revoke",
        "/remediation/changes/change-1/rollback",
        "/remediation/changes/change-1/complete",
        "/remediation/workflows/rec-1",
        "/remediation/changes/change-1",
        "/remediation/audit",
    ]
    assert calls[0].kwargs["json"]["idempotency_key"] == (
        "approval-request-decision-1"
    )
    assert calls[1].kwargs["json"]["idempotency_key"] == "change-apply-1"
    assert calls[-1].kwargs["params"] == {"recommendation_id": "rec-1"}


def test_fetch_simulated_change_surfaces_an_offline_backend() -> None:
    with patch(
        "frontend.remediation_client.requests.request",
        side_effect=requests.ConnectionError("offline"),
    ):
        with pytest.raises(RemediationClientError, match="API is unavailable"):
            fetch_simulated_change("http://api.test", "change-1")


def test_ui_contract_lists_exactly_the_eight_backend_states() -> None:
    assert set(WORKFLOW_STATES) == {
        "pending_approval",
        "approved",
        "rejected",
        "expired",
        "revoked",
        "simulated_active",
        "rolled_back",
        "completed",
    }
