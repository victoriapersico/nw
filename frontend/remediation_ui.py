"""Streamlit UI for the human-approved simulated routing workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Literal
from uuid import uuid4

import streamlit as st

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


WorkflowStatus = Literal[
    "pending_approval",
    "approved",
    "rejected",
    "expired",
    "revoked",
    "simulated_active",
    "rolled_back",
    "completed",
]

WORKFLOW_STATES: tuple[WorkflowStatus, ...] = (
    "pending_approval",
    "approved",
    "rejected",
    "expired",
    "revoked",
    "simulated_active",
    "rolled_back",
    "completed",
)

_STATUS_PRESENTATION: dict[WorkflowStatus, tuple[str, str, str]] = {
    "pending_approval": ("Awaiting approval", "orange", ":material/pending_actions:"),
    "approved": ("Approved", "blue", ":material/verified_user:"),
    "rejected": ("Rejected", "red", ":material/cancel:"),
    "expired": ("Approval expired", "gray", ":material/timer_off:"),
    "revoked": ("Approval revoked", "gray", ":material/block:"),
    "simulated_active": ("Simulation active", "violet", ":material/science:"),
    "rolled_back": ("Simulation reverted", "orange", ":material/undo:"),
    "completed": ("Review completed", "green", ":material/check_circle:"),
}


def _format_percentage(value: Any) -> str:
    if value is None:
        return "Unavailable"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "Unavailable"


def _format_event_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "Time unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")


def _operation_id(action: str, resource_id: str) -> str:
    """Keep retries idempotent for the lifetime of this browser session."""

    state_key = f"remediation-operation:{action}:{resource_id}"
    return st.session_state.setdefault(state_key, uuid4().hex)


def _run_action(
    label: str,
    operation: Callable[[], dict[str, Any]],
) -> None:
    """Run one synchronous API mutation and surface a useful error in place."""

    try:
        with st.spinner(label, show_time=True):
            operation()
    except RemediationClientError as exc:
        st.error(str(exc), icon=":material/error:")
        return
    st.toast("Workflow updated", icon=":material/check_circle:")
    st.rerun()


def _render_recommendation_audit(
    api_base_url: str,
    recommendation_id: str,
) -> None:
    """Show the backend-owned audit history for one recommendation."""

    try:
        events = fetch_audit(api_base_url, recommendation_id)
    except RemediationClientError as exc:
        st.warning(f"Audit trail unavailable: {exc}", icon=":material/warning:")
        return

    with st.expander(
        f"Audit trail · {len(events)} events",
        icon=":material/history:",
    ):
        if not events:
            st.caption("No workflow events have been recorded yet.")
        for event in reversed(events):
            label = str(event.get("event_type", "event")).replace("_", " ").capitalize()
            with st.container(border=True, gap="xxsmall"):
                st.markdown(f"**{label}**")
                st.caption(
                    f"{_format_event_time(event.get('occurred_at'))} · "
                    f"{event.get('actor', 'unknown actor')}"
                )
                st.write(event.get("detail", "No event detail was supplied."))


def _render_change_metrics(change: dict[str, Any]) -> None:
    """Render only measurements returned by the simulated-change endpoint."""

    monitoring = change.get("monitoring") or []
    latest = monitoring[-1] if monitoring else None

    st.caption(
        f"Local simulation · {change.get('traffic_shift_pct', 0):.0%} to "
        f"{change.get('target_provider', 'unknown provider')} · "
        "No payment provider was contacted"
    )

    before, expected, observed = st.columns(3)
    before.metric(
        "Before simulation",
        _format_percentage(change.get("before_approval_rate")),
    )
    expected.metric(
        "Expected after",
        _format_percentage(change.get("expected_approval_rate")),
    )
    observed.metric(
        "Observed target",
        _format_percentage(latest.get("approval_rate") if latest else None),
    )

    details = [
        "Expected recovery: "
        f"US$ {float(change.get('expected_recovered_value_per_hour', 0)):,.0f}/h"
    ]
    if latest and latest.get("error_rate") is not None:
        details.append(f"Observed errors: {float(latest['error_rate']):.1%}")
    if latest:
        details.append(
            f"Latest window: {_format_event_time(latest.get('window_end'))}"
        )
        details.append(
            f"{int(latest.get('attempted_transactions', 0)):,} attempts"
        )
    else:
        details.append("Awaiting the first monitoring window")
    st.caption(" · ".join(details))


def _render_pending_actions(
    api_base_url: str,
    recommendation_id: str,
    merchant: str,
) -> None:
    st.info(
        "Merchant Operations must review this evidence before a simulation can start.",
        icon=":material/verified_user:",
    )
    with st.container(horizontal=True, gap="small"):
        approve = st.button(
            "Approve recommendation",
            type="primary",
            icon=":material/check:",
            width="stretch",
            key=f"approve-{recommendation_id}",
        )
        reject = st.button(
            "Reject",
            icon=":material/close:",
            width="stretch",
            key=f"reject-{recommendation_id}",
        )

    if approve:
        _run_action(
            "Recording approval",
            lambda: record_decision(
                api_base_url,
                recommendation_id,
                merchant,
                "approved",
                operation_id=_operation_id("approve", recommendation_id),
                note="Approved in the Control Tower for local simulation only.",
            ),
        )
    elif reject:
        _run_action(
            "Recording rejection",
            lambda: record_decision(
                api_base_url,
                recommendation_id,
                merchant,
                "rejected",
                operation_id=_operation_id("reject", recommendation_id),
                note="Rejected in the Control Tower by Merchant Operations.",
            ),
        )


def _render_approved_actions(
    api_base_url: str,
    routing: dict[str, Any],
    workflow: dict[str, Any],
) -> None:
    recommendation_id = routing["recommendation_id"]
    approval_decision_id = workflow.get("approval_decision_id")
    rollback_reference = routing.get("rollback_reference")

    st.success(
        "Human approval is recorded. The next action changes local demo state only.",
        icon=":material/check_circle:",
    )
    references_available = bool(approval_decision_id and rollback_reference)
    if not references_available:
        st.error(
            "The approved workflow is missing its safe simulation references.",
            icon=":material/error:",
        )

    with st.container(horizontal=True, gap="small"):
        apply_change = st.button(
            "Simulate application",
            type="primary",
            icon=":material/science:",
            width="stretch",
            disabled=not references_available,
            key=f"apply-{recommendation_id}",
        )
        revoke = st.button(
            "Revoke approval",
            icon=":material/block:",
            width="stretch",
            disabled=approval_decision_id is None,
            key=f"revoke-{recommendation_id}",
        )

    if apply_change and approval_decision_id and rollback_reference:
        _run_action(
            "Starting local simulation",
            lambda: apply_simulated_change(
                api_base_url,
                recommendation_id,
                approval_decision_id,
                rollback_reference,
                operation_id=_operation_id("apply", recommendation_id),
            ),
        )
    elif revoke and approval_decision_id:
        _run_action(
            "Revoking approval",
            lambda: revoke_approval(
                api_base_url,
                approval_decision_id,
                routing["merchant"],
            ),
        )


def _render_active_actions(api_base_url: str, change_id: str) -> None:
    st.info(
        "The approved change is active only in the local simulator.",
        icon=":material/science:",
    )
    with st.container(horizontal=True, gap="small"):
        rollback = st.button(
            "Revert simulated change",
            icon=":material/undo:",
            width="stretch",
            key=f"rollback-{change_id}",
        )
        complete = st.button(
            "Complete review",
            type="primary",
            icon=":material/task_alt:",
            width="stretch",
            key=f"complete-{change_id}",
        )

    if rollback:
        _run_action(
            "Reverting local simulation",
            lambda: rollback_simulated_change(api_base_url, change_id),
        )
    elif complete:
        _run_action(
            "Completing simulated review",
            lambda: complete_simulated_change(api_base_url, change_id),
        )


def render_routing_workflow(
    api_base_url: str,
    routing: dict[str, Any],
) -> None:
    """Render all eight server-owned states for one routing recommendation."""

    recommendation_id = routing["recommendation_id"]
    try:
        workflow = fetch_workflow(api_base_url, recommendation_id)
    except RemediationClientError as exc:
        st.error(
            f"Could not load the approval workflow: {exc}",
            icon=":material/error:",
        )
        _render_recommendation_audit(api_base_url, recommendation_id)
        return

    status = workflow.get("status")
    if status not in WORKFLOW_STATES:
        st.error(
            f"Unsupported workflow state: {status!r}",
            icon=":material/error:",
        )
        _render_recommendation_audit(api_base_url, recommendation_id)
        return

    label, color, icon = _STATUS_PRESENTATION[status]
    st.markdown("##### Human approval & simulated rollout")
    st.badge(label, color=color, icon=icon)
    st.caption(workflow.get("transition_reason", "No transition reason supplied."))
    st.caption(f"Updated {_format_event_time(workflow.get('updated_at'))}")

    if status == "pending_approval":
        _render_pending_actions(
            api_base_url,
            recommendation_id,
            routing["merchant"],
        )
    elif status == "approved":
        _render_approved_actions(api_base_url, routing, workflow)
    elif status == "rejected":
        st.warning(
            "Merchant Operations rejected this recommendation. No simulation started.",
            icon=":material/cancel:",
        )
    elif status == "expired":
        st.warning(
            "The approval expired before simulation activation.",
            icon=":material/timer_off:",
        )
    elif status == "revoked":
        st.warning(
            "Merchant Operations revoked approval before activation.",
            icon=":material/block:",
        )
    else:
        change_id = workflow.get("change_id")
        if not change_id:
            st.error(
                "The workflow is missing its simulated change reference.",
                icon=":material/error:",
            )
        else:
            try:
                change = fetch_simulated_change(api_base_url, change_id)
            except RemediationClientError as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                _render_change_metrics(change)
                if status == "simulated_active":
                    _render_active_actions(api_base_url, change_id)
                elif status == "rolled_back":
                    st.warning(
                        change.get("rollback_reason")
                        or "The local simulation was reverted.",
                        icon=":material/undo:",
                    )
                elif status == "completed":
                    st.success(
                        "The simulated rollout review is complete. "
                        "No provider was contacted.",
                        icon=":material/check_circle:",
                    )

    _render_recommendation_audit(api_base_url, recommendation_id)


def render_remediation_panel(
    api_base_url: str,
    routing: dict[str, Any] | None,
    fallback_recommendation: str,
) -> None:
    """Render the recommendation summary and its human-gated lifecycle."""

    st.markdown("#### Recommended action")
    if routing is None:
        st.info(fallback_recommendation, icon=":material/lightbulb:")
        return

    recommendation_id = routing.get("recommendation_id")
    if routing.get("status") != "recommended":
        st.warning(
            "No routing change is recommended. Continue monitoring.",
            icon=":material/visibility:",
        )
        st.caption(routing.get("abstention_reason") or routing.get("rationale"))
        if recommendation_id:
            _render_recommendation_audit(api_base_url, recommendation_id)
        return

    target_provider = routing.get("target_provider")
    traffic_cap = routing.get("traffic_cap")
    if target_provider is None or traffic_cap is None:
        st.error(
            "This recommendation is incomplete. Refresh the simulation before approval.",
            icon=":material/error:",
        )
        st.caption(routing.get("rationale", "No recommendation rationale supplied."))
        if recommendation_id:
            _render_recommendation_audit(api_base_url, recommendation_id)
        return

    st.info(
        f"Simulate shifting {float(traffic_cap):.0%} of affected traffic "
        f"to {target_provider}.",
        icon=":material/route:",
    )

    recovery, expected, confidence = st.columns(3)
    recovery.metric(
        "Estimated recovery / hour",
        f"US$ {float(routing.get('expected_recovery_per_hour', 0)):,.0f}",
    )
    expected.metric(
        "Expected approval",
        _format_percentage(routing.get("expected_approval_rate")),
    )
    confidence.metric(
        "Confidence",
        _format_percentage(routing.get("confidence")),
    )
    st.write(routing.get("rationale", "No recommendation rationale supplied."))
    st.caption(
        "Recommendation only · Human approval required · "
        "All changes stay inside the local simulator"
    )

    render_routing_workflow(api_base_url, routing)
