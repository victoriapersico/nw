"""Merchant-scoped client dashboard for the Control Tower MVP."""

import os
import requests

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
import csv
from typing import Any

import streamlit as st

from backend.schemas import InjectionConfig
from frontend.injection_scope import (
    clear_scope_state,
    render_scope_filter,
    render_scope_selector,
)
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

API_BASE_URL = os.getenv(
    "CONTROL_TOWER_API_URL",
    "http://127.0.0.1:8000",
)


def fetch_merchant_incidents(
    merchant: str,
) -> list[dict[str, Any]] | None:
    """Return None only when the local API is unavailable."""

    try:
        response = requests.get(
            f"{API_BASE_URL}/merchants/{merchant}/incidents",
            timeout=10,
        )
        response.raise_for_status()
        st.session_state.pop("live_api_error", None)
        return response.json()["incidents"]
    except requests.RequestException as exc:
        st.session_state["live_api_error"] = str(exc)
        return None


def select_display_incident(
    incidents: list[dict[str, Any]], merchant: str
) -> dict[str, Any]:
    """Prefer the Judge Lab's latest matching country without exposing it to detection."""

    latest_injection = st.session_state.get("last_injection")
    if latest_injection and latest_injection.get("merchant") == merchant:
        matching_country = [
            item
            for item in incidents
            if item["incident"]["country"] == latest_injection.get("country")
        ]
        if matching_country:
            return max(
                matching_country,
                key=lambda item: item["incident"]["detected_at"],
            )

    return next(
        (
            item
            for item in incidents
            if (item.get("remediation") or {}).get("status") == "recommended"
        ),
        incidents[0],
    )


def advance_and_fetch_monitoring(merchant: str) -> dict[str, Any] | None:
    """Advance one real simulator window, then read its merchant-scoped metrics."""

    try:
        tick = requests.post(f"{API_BASE_URL}/monitor/tick", timeout=20)
        tick.raise_for_status()
        response = requests.get(
            f"{API_BASE_URL}/merchants/{merchant}/monitoring",
            timeout=15,
        )
        response.raise_for_status()
        st.session_state.pop("live_api_error", None)
        return response.json()
    except requests.RequestException as exc:
        st.session_state["live_api_error"] = str(exc)
        return None


def request_remediation_simulation(
    merchant: str, incident_id: str
) -> dict[str, Any] | None:
    """Ask the backend for bounded routing alternatives, never a live change."""

    try:
        response = requests.post(
            f"{API_BASE_URL}/remediation/simulations",
            json={
                "merchant": merchant,
                "incident_id": incident_id,
                "dry_run": True,
                "idempotency_key": f"dashboard-sim-{incident_id}"[:128],
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Could not simulate recovery options: {exc}")
        return None


def remember_incident_recovery(
    incident: dict[str, Any], merchant: str
) -> list[dict[str, Any]]:
    """Keep a small, browser-session audit trail for the live demo."""

    incident_id = incident.get("incident_id")
    if not incident_id:
        return []

    log_by_incident = st.session_state.setdefault("incident_recovery_log", {})
    remediation = incident.get("remediation") or {}
    alternatives = remediation.get("alternatives", [])
    recommended_id = remediation.get("recommended_option_id")
    recommended = next(
        (
            item
            for item in alternatives
            if item["option"]["option_id"] == recommended_id
        ),
        None,
    )
    causes = ", ".join(
        f"{label}: {value}" for label, value in incident["root_cause"].items()
    )
    observed_at = incident.get("detected_at") or datetime.now(timezone.utc).isoformat()
    existing = log_by_incident.get(incident_id, {})
    log_by_incident[incident_id] = {
        "incident_id": incident_id,
        "merchant": merchant,
        "country": incident["country"],
        "observed_at": existing.get("observed_at", observed_at),
        "cause": causes,
        "severity": incident["severity"],
        "estimated_loss": incident.get("estimated_loss", 0.0),
        "recommendation": (
            (
                f"Move {recommended['option']['traffic_shift_pct']:.0%} to "
                f"{recommended['option']['target_provider']} "
                f"(estimated US$ {recommended['expected_recovered_value_per_hour']:,.0f}/hour)"
            )
            if recommended is not None
            else remediation.get("rationale", "Simulation not requested yet.")
        ),
        "options": [
            (
                f"{item['option']['target_provider']} "
                f"{item['option']['traffic_shift_pct']:.0%}: {item['status']}"
            )
            for item in alternatives
        ],
    }
    return sorted(
        log_by_incident.values(), key=lambda entry: entry["observed_at"], reverse=True
    )


def format_usd(amount: float) -> str:
    """Format demo money consistently without implying a currency conversion."""

    return f"US$ {amount:,.0f}"


def build_monthly_incident_report(entries: list[dict[str, Any]]) -> str:
    """Create a portable, human-readable session report for the demo."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        try:
            observed_at = datetime.fromisoformat(
                entry["observed_at"].replace("Z", "+00:00")
            )
            month = observed_at.strftime("%Y-%m")
        except (TypeError, ValueError):
            month = "unknown-month"
        groups.setdefault(month, []).append(entry)

    report = ["# Control Tower — incident & recovery report", ""]
    for month, month_entries in sorted(groups.items(), reverse=True):
        total_loss = sum(float(entry["estimated_loss"]) for entry in month_entries)
        report.extend(
            [
                f"## {month}",
                f"- Incidents recorded: {len(month_entries)}",
                f"- Estimated loss at detection: {format_usd(total_loss)}",
                "",
            ]
        )
        for entry in month_entries:
            report.extend(
                [
                    f"### {entry['merchant']} — {entry['country']} ({entry['severity']})",
                    f"- Observed: {entry['observed_at']}",
                    f"- Cause: {entry['cause']}",
                    f"- Estimated loss: {format_usd(float(entry['estimated_loss']))}",
                    f"- Possible solution: {entry['recommendation']}",
                    "",
                ]
            )
    return "\n".join(report)


def render_incident_recovery_log(entries: list[dict[str, Any]]) -> None:
    """Show retained incidents and deterministic recovery options for the demo."""

    st.markdown("#### Incident & recovery log")
    st.caption(
        "Local demo audit trail. It retains detected incidents and evaluated "
        "recovery options while this dashboard session is open."
    )
    if not entries:
        st.info("No incidents have been recorded in this dashboard session yet.")
        return

    csv_buffer = StringIO()
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=(
            "incident_id", "merchant", "country", "observed_at", "severity",
            "estimated_loss", "cause", "recommendation", "options",
        ),
    )
    writer.writeheader()
    for entry in entries:
        writer.writerow({**entry, "options": " | ".join(entry["options"])})

    download_csv, download_report = st.columns(2)
    with download_csv:
        st.download_button(
            "Download incident log (CSV)", data=csv_buffer.getvalue(),
            file_name="control-tower-incident-log.csv", mime="text/csv", width="stretch",
        )
    with download_report:
        st.download_button(
            "Download monthly report (Markdown)", data=build_monthly_incident_report(entries),
            file_name="control-tower-monthly-report.md", mime="text/markdown", width="stretch",
        )

    for entry in entries:
        with st.expander(
            f"{entry['severity']} · {entry['merchant']} / {entry['country']} · "
            f"{entry['incident_id']}",
            expanded=False,
        ):
            st.markdown(f"**Observed:** {entry['observed_at']}")
            st.markdown(f"**Why it fell:** {entry['cause']}")
            st.markdown(
                f"**Estimated loss at detection:** {format_usd(float(entry['estimated_loss']))}"
            )
            st.markdown(f"**Recommended recovery:** {entry['recommendation']}")
            if entry["options"]:
                st.markdown("**Evaluated options:**")
                for option in entry["options"]:
                    st.markdown(f"- {option}")


def render_remediation_panel(
    merchant: str,
    incident_id: str,
    remediation: dict[str, Any] | None,
) -> None:
    """Present POST-01 as a human-approved dry-run, not provider automation."""

    state_key = f"remediation:{incident_id}"
    if remediation is not None:
        st.session_state[state_key] = remediation
    proposal = st.session_state.get(state_key)

    st.markdown("#### Recommended recovery")
    st.caption(
        "Counterfactual estimate based on observed transaction evidence. "
        "It does not contact a payment provider or change routing."
    )

    if st.button(
        "Simulate recovery options" if proposal is None else "Refresh simulation",
        key=f"simulate:{incident_id}",
        width="stretch",
    ):
        result = request_remediation_simulation(merchant, incident_id)
        if result is not None:
            st.session_state[state_key] = result
            proposal = result
            st.rerun()

    if proposal is None:
        return

    if proposal["status"] != "recommended":
        st.warning("A routing recommendation is not available for this incident yet.")
        st.caption(proposal["rationale"])
        return

    recommended_id = proposal.get("recommended_option_id")
    recommended = next(
        (
            item
            for item in proposal.get("alternatives", [])
            if item["option"]["option_id"] == recommended_id
        ),
        None,
    )
    if recommended is not None:
        option = recommended["option"]
        st.success(
            f"Recommended: shift {option['traffic_shift_pct']:.0%} of affected "
            f"traffic to {option['target_provider']}."
        )
        first, second, third = st.columns(3)
        first.metric(
            "Estimated recovery / hour",
            f"US$ {recommended['expected_recovered_value_per_hour']:,.0f}",
        )
        second.metric(
            "Expected approval",
            f"{recommended['expected_approval_rate']:.1%}",
        )
        third.metric("Confidence", f"{recommended['confidence']:.0%}")

    st.markdown("#### Simulation details")
    st.caption(
        "Each option is a bounded counterfactual estimate. No traffic is moved "
        "until an approved provider integration exists."
    )
    st.markdown("**Evaluated alternatives**")
    for alternative in proposal.get("alternatives", []):
        option = alternative["option"]
        label = (
            f"{option['target_provider']} · "
            f"{option['traffic_shift_pct']:.0%} traffic shift"
        )
        if alternative["status"] == "eligible":
            st.markdown(
                f"- **{label}** — estimated recovery "
                f"US$ {alternative['expected_recovered_value_per_hour']:,.0f}/hour "
                f"({alternative['confidence']:.0%} confidence)"
            )
        else:
            st.markdown(
                f"- ~~{label}~~ — {alternative.get('rejection_reason', 'Not eligible')}"
            )

    st.caption(f"Guardrail: {proposal['rollback_condition']}")
    st.caption("Human approval is required. This demo can only run a dry-run.")

    approval_key = f"approval:{proposal['recommendation_id']}"
    execution_key = f"execution:{proposal['recommendation_id']}"
    approval = st.session_state.get(approval_key)

    if approval is None:
        if st.button(
            "Approve dry-run", key=f"approve:{incident_id}", width="stretch"
        ):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/remediation/approvals",
                    json={
                        "decision_id": f"dashboard-approval-{incident_id}"[:128],
                        "recommendation_id": proposal["recommendation_id"],
                        "decision": "approved",
                        "decided_by": "merchant-operator-demo",
                        "decided_at": datetime.now(timezone.utc).isoformat(),
                        "note": "Dashboard demo approval for simulation only.",
                    },
                    timeout=5,
                )
                response.raise_for_status()
                st.session_state[approval_key] = response.json()
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Could not record approval: {exc}")
        return

    st.info("Human approval recorded. The next step remains a dry-run only.")
    execution = st.session_state.get(execution_key)
    if execution is None and st.button(
        "Run controlled dry-run", key=f"dry-run:{incident_id}", width="stretch"
    ):
        try:
            response = requests.post(
                f"{API_BASE_URL}/remediation/executions",
                json={
                    "recommendation_id": proposal["recommendation_id"],
                    "approval_decision_id": approval["decision_id"],
                    "idempotency_key": f"dashboard-execution-{incident_id}"[:128],
                    "rollback_reference": proposal["rollback_reference"],
                    "dry_run": True,
                },
                timeout=5,
            )
            response.raise_for_status()
            execution = response.json()
            st.session_state[execution_key] = execution
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Could not run the dry-run: {exc}")
    elif execution is not None:
        st.success(f"{execution['reason']} Executed: {execution['executed']}.")
def _render_recommendation_audit(recommendation_id: str) -> None:
    """Show the append-only events without exposing provider operations."""

    try:
        events = fetch_audit(API_BASE_URL, recommendation_id)
    except RemediationClientError as exc:
        st.caption(f"Audit unavailable: {exc}")
        return
    with st.expander(f"Audit log · {len(events)} events"):
        for event in reversed(events):
            label = event["event_type"].replace("_", " ").title()
            st.markdown(f"**{label}** · `{event['actor']}`")
            st.caption(event["detail"])


def _render_routing_workflow(routing: dict[str, Any]) -> None:
    """Render the human gate and simulated lifecycle for one recommendation."""

    recommendation_id = routing["recommendation_id"]
    try:
        workflow = fetch_workflow(API_BASE_URL, recommendation_id)
    except RemediationClientError as exc:
        st.error(f"Could not load the approval workflow: {exc}")
        _render_recommendation_audit(recommendation_id)
        return

    status = workflow["status"]
    st.markdown(f"**Workflow status:** `{status}`")
    st.caption(workflow["transition_reason"])

    if status == "pending_approval":
        approve_column, reject_column = st.columns(2)
        with approve_column:
            if st.button(
                "Approve recommendation",
                type="primary",
                use_container_width=True,
                key=f"approve-{recommendation_id}",
            ):
                try:
                    record_decision(
                        API_BASE_URL,
                        recommendation_id,
                        routing["merchant"],
                        "approved",
                    )
                    st.rerun()
                except RemediationClientError as exc:
                    st.error(str(exc))
        with reject_column:
            if st.button(
                "Reject",
                use_container_width=True,
                key=f"reject-{recommendation_id}",
            ):
                try:
                    record_decision(
                        API_BASE_URL,
                        recommendation_id,
                        routing["merchant"],
                        "rejected",
                    )
                    st.rerun()
                except RemediationClientError as exc:
                    st.error(str(exc))
    elif status == "approved":
        approval_decision_id = workflow.get("approval_decision_id")
        if approval_decision_id is None:
            st.error("The approved workflow is missing its safe application references.")
        else:
            apply_column, revoke_column = st.columns(2)
            with apply_column:
                if routing.get("rollback_reference") and st.button(
                    "Simulate application",
                    type="primary",
                    use_container_width=True,
                    key=f"apply-{recommendation_id}",
                ):
                    try:
                        apply_simulated_change(
                            API_BASE_URL,
                            recommendation_id,
                            approval_decision_id,
                            routing["rollback_reference"],
                        )
                        st.rerun()
                    except RemediationClientError as exc:
                        st.error(str(exc))
            with revoke_column:
                if st.button(
                    "Revoke approval",
                    use_container_width=True,
                    key=f"revoke-{recommendation_id}",
                ):
                    try:
                        revoke_approval(
                            API_BASE_URL,
                            approval_decision_id,
                            routing["merchant"],
                        )
                        st.rerun()
                    except RemediationClientError as exc:
                        st.error(str(exc))
    elif status == "rejected":
        st.warning("The operator rejected this recommendation.")
    elif status == "expired":
        st.warning("The approval expired before simulation activation.")
    elif status == "revoked":
        st.warning("The operator revoked approval before simulation activation.")
    elif status in {"simulated_active", "rolled_back", "completed"}:
        change_id = workflow.get("change_id")
        if change_id is None:
            st.error("The workflow is missing its simulated change reference.")
        else:
            try:
                change = fetch_simulated_change(API_BASE_URL, change_id)
            except RemediationClientError as exc:
                st.error(str(exc))
            else:
                latest = change["monitoring"][-1] if change["monitoring"] else None
                before, expected, observed = st.columns(3)
                before.metric("Before approval", f"{change['before_approval_rate']:.1%}")
                expected.metric(
                    "Expected after",
                    (
                        f"{change['expected_approval_rate']:.1%}"
                        if change["expected_approval_rate"] is not None
                        else "N/A"
                    ),
                )
                observed.metric(
                    "Observed target",
                    (
                        f"{latest['approval_rate']:.1%}"
                        if latest and latest["approval_rate"] is not None
                        else "Awaiting window"
                    ),
                )
                st.caption(
                    f"Expected recovery: US$ "
                    f"{change['expected_recovered_value_per_hour']:,.0f}/h"
                    + (
                        f" · Observed errors: {latest['error_rate']:.1%}"
                        if latest and latest["error_rate"] is not None
                        else ""
                    )
                )
                if status == "simulated_active":
                    rollback_column, complete_column = st.columns(2)
                    with rollback_column:
                        if st.button(
                            "Revert simulated change",
                            use_container_width=True,
                            key=f"rollback-{change_id}",
                        ):
                            try:
                                rollback_simulated_change(API_BASE_URL, change_id)
                                st.rerun()
                            except RemediationClientError as exc:
                                st.error(str(exc))
                    with complete_column:
                        if st.button(
                            "Complete review",
                            type="primary",
                            use_container_width=True,
                            key=f"complete-{change_id}",
                        ):
                            try:
                                complete_simulated_change(API_BASE_URL, change_id)
                                st.rerun()
                            except RemediationClientError as exc:
                                st.error(str(exc))
                elif status == "rolled_back":
                    st.warning(change["rollback_reason"] or "Simulated change reverted.")
                else:
                    st.success("Simulated rollout review completed. No provider was contacted.")

    _render_recommendation_audit(recommendation_id)


def render_approval_chart(
    trends: dict[str, list[float]],
    country_metrics: dict[str, dict[str, Any]],
    theme: dict[str, str],
    window_end: datetime | None = None,
) -> None:
    """Render a dependency-free SVG chart for Windows demo environments."""

    colors = [theme["primary"], theme["accent"], theme["dark"]]
    width, height = 920, 304
    left, right, top, bottom = 52, 24, 20, 66
    chart_width = width - left - right
    chart_height = height - top - bottom
    minimum, maximum = 55.0, 100.0

    def point(index: int, value: float, count: int) -> tuple[float, float]:
        x = left + (chart_width * index / max(count - 1, 1))
        y = top + (maximum - value) * chart_height / (maximum - minimum)
        return x, y

    grid = "".join(
        f'<line x1="{left}" x2="{width - right}" y1="{point(0, tick, 2)[1]:.1f}" '
        f'y2="{point(0, tick, 2)[1]:.1f}" stroke="rgba(90,105,135,.16)" />'
        f'<text x="8" y="{point(0, tick, 2)[1] + 4:.1f}" fill="#68758c" font-size="11">{tick}%</text>'
        for tick in (60, 70, 80, 90, 100)
    )
    largest_history = max((len(values) for values in trends.values()), default=1)

    def sampled_indexes(count: int, maximum_points: int = 180) -> list[int]:
        """Keep SVG rendering fast while preserving the full time range."""

        if count <= maximum_points:
            return list(range(count))
        return sorted(
            {
                round(index * (count - 1) / (maximum_points - 1))
                for index in range(maximum_points)
            }
        )

    lines: list[str] = []
    for color, (country, approvals) in zip(colors, trends.items()):
        indexes = sampled_indexes(len(approvals))
        points = " ".join(
            f"{x:.1f},{y:.1f}"
            for index in indexes
            for x, y in [point(index, approvals[index], largest_history)]
        )
        expected = country_metrics[country]["expected"]
        expected_y = point(0, expected, 2)[1]
        lines.append(
            f'<line x1="{left}" x2="{width - right}" y1="{expected_y:.1f}" '
            f'y2="{expected_y:.1f}" stroke="{color}" stroke-opacity=".32" '
            'stroke-dasharray="5 5" />'
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />'
        )
        for index in indexes:
            approval = approvals[index]
            x, y = point(index, approval, largest_history)
            critical = approval - expected <= -8
            marker = "#dc2638" if critical else color
            radius = "5" if critical else "3"
            lines.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{marker}" '
                'stroke="white" stroke-width="1.5" />'
            )

    reference_end = window_end or datetime(2025, 9, 2, 13, tzinfo=timezone.utc)
    label_indexes = sorted(
        {
            0,
            max(0, largest_history // 3),
            max(0, (largest_history * 2) // 3),
            largest_history - 1,
        }
    )
    time_labels = "".join(
        f'<text x="{point(index, 0, largest_history)[0]:.1f}" y="{height - 25}" '
        'fill="#68758c" font-size="10" text-anchor="middle">'
        f"{(reference_end - timedelta(minutes=5 * (largest_history - 1 - index))).strftime('%d %b · %H:%M')}"
        "</text>"
        for index in label_indexes
    )

    chart = f"""
    <div class="approval-chart">
        <svg viewBox="0 0 {width} {height}" role="img" aria-label="Live approval rate by country">
            {grid}{''.join(lines)}{time_labels}
            <text x="{width / 2 - 44:.1f}" y="{height - 7}" fill="#68758c" font-size="11">Simulated time</text>
        </svg>
    </div>
    """
    st.markdown(chart, unsafe_allow_html=True)


def render_approval_chart_legacy(*_args: Any, **_kwargs: Any) -> None:
    """Compatibility shim that avoids Streamlit's blocked pyarrow transport."""

    render_approval_chart(data["trend"], countries, theme)


# Contract-shaped mocks until the live backend is integrated. Each merchant owns
# a separate payload so switching companies can never mix their information.
MERCHANT_DATA: dict[str, dict[str, Any]] = {
    "Rappi": {
        "updated": "18 seconds ago",
        "countries": {
            "Mexico": {
                "approval": 91.8,
                "expected": 92.4,
                "transactions": 18420,
                "loss": 3240,
                "status": "Stable",
            },
            "Brazil": {
                "approval": 71.2,
                "expected": 93.1,
                "transactions": 26180,
                "loss": 48700,
                "status": "Critical",
            },
            "Colombia": {
                "approval": 90.6,
                "expected": 91.5,
                "transactions": 13940,
                "loss": 4100,
                "status": "Stable",
            },
        },
        "providers": [
            {"name": "Stripe", "approval": 92.7, "status": "Operational"},
            {"name": "Adyen", "approval": 91.9, "status": "Operational"},
            {"name": "dLocal", "approval": 62.4, "status": "Degraded"},
        ],
        "trend": {
            "Mexico": [92.0, 92.5, 92.1, 91.9, 92.2, 91.8],
            "Brazil": [93.0, 92.8, 91.4, 84.1, 76.9, 71.2],
            "Colombia": [91.2, 91.0, 91.6, 91.1, 90.9, 90.6],
        },
        # Start the presentation clean. Real incidents come only from the live API
        # after an injection or detector event, never from a visual placeholder.
        "incident": None,
    },
    "Carrefour": {
        "updated": "24 seconds ago",
        "countries": {
            "Mexico": {
                "approval": 89.7,
                "expected": 90.2,
                "transactions": 12110,
                "loss": 1900,
                "status": "Stable",
            },
            "Brazil": {
                "approval": 91.4,
                "expected": 91.7,
                "transactions": 15430,
                "loss": 1600,
                "status": "Stable",
            },
            "Colombia": {
                "approval": 88.9,
                "expected": 89.5,
                "transactions": 9780,
                "loss": 2100,
                "status": "Stable",
            },
        },
        "providers": [
            {"name": "Stripe", "approval": 90.8, "status": "Operational"},
            {"name": "Adyen", "approval": 89.9, "status": "Operational"},
            {"name": "dLocal", "approval": 89.5, "status": "Operational"},
        ],
        "trend": {
            "Mexico": [89.9, 90.1, 89.8, 90.0, 89.6, 89.7],
            "Brazil": [91.5, 91.8, 91.6, 91.4, 91.7, 91.4],
            "Colombia": [89.2, 89.4, 89.1, 89.0, 89.3, 88.9],
        },
        "incident": None,
    },
    "Despegar": {
        "updated": "11 seconds ago",
        "countries": {
            "Mexico": {
                "approval": 87.1,
                "expected": 89.8,
                "transactions": 8420,
                "loss": 9800,
                "status": "Attention",
            },
            "Brazil": {
                "approval": 90.4,
                "expected": 90.9,
                "transactions": 11260,
                "loss": 2700,
                "status": "Stable",
            },
            "Colombia": {
                "approval": 89.8,
                "expected": 90.1,
                "transactions": 7340,
                "loss": 1400,
                "status": "Stable",
            },
        },
        "providers": [
            {"name": "Stripe", "approval": 90.6, "status": "Operational"},
            {"name": "Adyen", "approval": 85.1, "status": "Under observation"},
            {"name": "dLocal", "approval": 89.8, "status": "Operational"},
        ],
        "trend": {
            "Mexico": [89.6, 89.4, 89.0, 88.1, 87.5, 87.1],
            "Brazil": [90.8, 90.5, 90.9, 90.6, 90.5, 90.4],
            "Colombia": [90.0, 90.2, 90.1, 89.9, 90.0, 89.8],
        },
        "incident": {
            "severity": "Medium",
            "country": "Mexico",
            "title": "Increased declines on Adyen",
            "root_cause": {"Country": "Mexico", "Provider": "Adyen", "Method": "CARD"},
            "diagnosis": "The degradation is concentrated in CARD payments processed by Adyen.",
            "diagnosis_points": [
                "The drop mainly affects CARD payments.",
                "Adyen accounts for most of the deterioration.",
                "Other providers remain stable.",
            ],
            "recommendation": "Monitor two additional windows and inspect Adyen decline codes.",
            "confidence": 0.78,
        },
    },
}

MERCHANT_THEMES = {
    "Rappi": {
        "primary": "#ff5a5f",
        "dark": "#8f2730",
        "soft": "#ffe8e5",
        "background": "#ffbeb8",
        "accent": "#ff9d82",
    },
    "Carrefour": {
        "primary": "#1554a3",
        "dark": "#082d64",
        "soft": "#e5efff",
        "background": "#bdd5fa",
        "accent": "#e52329",
    },
    "Despegar": {
        "primary": "#6f32c9",
        "dark": "#3e197c",
        "soft": "#eee4ff",
        "background": "#d5bbfa",
        "accent": "#f6c945",
    },
}

MERCHANT_LOGOS = {
    "Rappi": "https://upload.wikimedia.org/wikipedia/commons/0/06/Rappi_logo.svg",
    "Carrefour": "https://fr.wikipedia.org/wiki/Special:Redirect/file/Logo_Carrefour.svg",
    "Despegar": "https://upload.wikimedia.org/wikipedia/commons/d/db/Despegar.com_logo.svg",
}

st.markdown(
    """
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
    :root {
        --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px; --space-5:20px; --space-6:24px; --space-8:32px;
        --surface:#ffffff; --surface-muted:#f7f8fa; --page:#f2f4f7; --border:#d9dee7;
        --text:#111827; --muted:#667085; --danger:#b42318; --danger-soft:#fff7f6;
        --radius-card:2px; --radius-control:2px; --shadow:none;
    }
    /* Hide Streamlit's development chrome: Deploy, menu and top decoration. */
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display: none !important; }
    .stApp { color:var(--text); background:var(--page); }
    [data-testid="stMain"] { background:#eef2f6; }
    [data-testid="stMainBlockContainer"],
    .block-container {
        width:min(100%,1280px); max-width:1280px; margin-left:auto !important; margin-right:auto !important;
        padding:var(--space-2) var(--space-5) var(--space-4);
        background:transparent !important; border:0 !important; border-radius:0 !important; box-shadow:none !important;
        transition:width .2s ease,margin .2s ease;
    }
    html, body, [class*="css"] { font-family:"IBM Plex Sans","Segoe UI",Arial,sans-serif; font-size:14px; }
    h1, h2, h3, h4, .hero-title, .team-name, .toolbar-title { font-family:"IBM Plex Sans","Segoe UI",Arial,sans-serif !important; }
    [data-testid="stMetricValue"], .kpi-value, .country-rate, .alert-facts { font-family:"IBM Plex Mono","Cascadia Mono","Consolas",monospace; font-variant-numeric:tabular-nums; }
    [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap:var(--space-1); }
    h3 { color:var(--text) !important; font-size:15px !important; line-height:20px !important; font-weight:650 !important; letter-spacing:-.01em !important; margin:var(--space-2) 0 var(--space-1) !important; }
    h3::before { content:""; display:inline-block; width:2px; height:16px; margin-right:var(--space-2); background:var(--danger); vertical-align:-2px; }
    h4 { font-weight:760 !important; letter-spacing:-.025em !important; }
    [data-testid="stSidebarNav"] { display:none !important; }
    [data-testid="stSidebar"] { border-right:1px solid var(--border); height:100dvh; overflow:hidden !important; box-shadow:none; }
    [data-testid="stSidebar"][aria-expanded="true"] { min-width:152px; max-width:152px; }
    [data-testid="stAppViewContainer"]:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMain"] {
        width:100% !important;
        margin-left:0 !important;
    }
    [data-testid="stAppViewContainer"]:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMainBlockContainer"] {
        margin-left:auto !important;
        margin-right:auto !important;
    }
    [data-testid="stSidebar"] > div:first-child { padding-top:0; }
    [data-testid="stSidebarContent"] { width:100%; height:100dvh; overflow:hidden !important; background:transparent !important; }
    [data-testid="stSidebarUserContent"] { width:100%; height:100%; overflow:hidden !important; padding:var(--space-2) var(--space-2) !important; }
    [data-testid="stSidebar"] [data-testid="stImage"] { display:flex; justify-content:center; background:transparent; border:0; padding:0; margin:0; box-shadow:none; }
    [data-testid="stSidebar"] [data-testid="stImage"] img { display:block; margin:0 auto; }
    [data-testid="stPopoverBody"] { min-width:340px; border:1px solid #cfd6e1; border-radius:var(--radius-card); box-shadow:0 12px 28px rgba(16,24,40,.14); }
    [data-testid="stPopover"] { position:fixed; right:0; top:42%; z-index:999999; width:auto !important; }
    [data-testid="stPopover"] > button { min-height:112px; width:34px; padding:.65rem .35rem !important; color:white !important; background:#17233a !important; border:0 !important; border-left:3px solid var(--merchant-primary) !important; border-radius:0 !important; box-shadow:none; writing-mode:vertical-rl; transform:rotate(180deg); font-size:.68rem; letter-spacing:.08em; }
    [data-testid="stMetric"] { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:10px var(--space-3); box-shadow:none; }
    [data-testid="stMetricValue"] { color:#172033; font-size:24px; line-height:28px; }
    [data-testid="stVegaLiteChart"] { background:transparent !important; border:0; border-radius:0; padding:var(--space-1) var(--space-6) 0 0; margin-bottom:0 !important; box-shadow:none; }
    [data-testid="stVegaLiteChart"] .vega-embed,
    [data-testid="stVegaLiteChart"] canvas,
    [data-testid="stVegaLiteChart"] svg { background:transparent !important; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background:transparent !important;
        background-color:transparent !important;
        box-shadow:none !important;
        border:none !important;
        border-radius:0 !important;
    }
    [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stForm"] [data-testid="stVerticalBlockBorderWrapper"] {
        background:var(--surface) !important;
        background-color:var(--surface) !important;
        border:1px solid var(--border) !important;
        border-radius:var(--radius-card) !important;
        box-shadow:none !important;
    }
    [data-testid="stColumn"] [data-testid="stVerticalBlock"] { gap:var(--space-1); }
    .product-name { color:#29324a; font-size:1.22rem; line-height:1.15; font-weight:750; letter-spacing:-.025em; margin:.35rem 0 .25rem; }
    .product-copy { color:#748096; font-size:.76rem; margin-bottom:.8rem; }
    [data-testid="stSidebar"] div[data-baseweb="select"] > div { background:transparent; border:0; box-shadow:none; font-weight:700; color:#29324a; padding-left:0; }
    .eyebrow { color:var(--muted); font-size:11px; line-height:16px; font-weight:650; text-transform:uppercase; letter-spacing:.08em; margin-top:0; }
    .status-ok,.status-watch,.status-critical { display:inline-block; padding:2px 6px; border-radius:1px; font-size:10px; font-weight:750; letter-spacing:.04em; text-transform:uppercase; }
    .status-ok { color:#08775d; background:#dff7ef; }
    .status-watch { color:#9b5d00; background:#fff0cc; }
    .status-critical { color:#b42318; background:#fee4e2; }
    .incident-card { background:white; border:1px solid #e4eaf2; border-left:4px solid #e5484d; border-radius:0; padding:1rem 1.1rem; margin-bottom:.8rem; }
    .primary-alert { position:static; display:grid; grid-template-columns:minmax(220px,.8fr) minmax(0,1.2fr); min-height:88px; gap:var(--space-4); align-items:start; color:#852431; background:var(--danger-soft); border:1px solid #f0cbd0; border-left:3px solid var(--danger); border-radius:var(--radius-card); padding:10px var(--space-3); margin:0 0 18px; box-shadow:none; }
    .alert-kicker { font-family:"Bahnschrift SemiCondensed","Arial Narrow",sans-serif; font-size:.74rem; font-weight:750; letter-spacing:.12em; }
    .alert-country { opacity:.8; font-size:11px; line-height:15px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; margin-top:2px; }
    .alert-title { font-size:15px; line-height:19px; font-weight:700; margin:1px 0 0; overflow-wrap:anywhere; }
    .alert-side { display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:var(--space-2) var(--space-3); min-width:0; }
    .alert-facts { flex:1 1 310px; min-width:0; opacity:.9; font-size:12px; line-height:18px; text-align:left; white-space:normal; overflow-wrap:anywhere; }
    .alert-action { color:white !important; background:var(--danger); text-decoration:none !important; border-radius:var(--radius-control); padding:8px var(--space-3); font-size:12px; font-weight:650; white-space:nowrap; }
    .healthy-alert { position:static; color:#08775d; background:#f3fbf7; border:1px solid #bfe7d4; border-left:3px solid #08775d; border-radius:0; padding:10px var(--space-3); margin:0 0 18px; }
    .provider-stack { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:var(--space-1) var(--space-3); box-shadow:none; }
    .provider-row { display:flex; align-items:center; gap:.7rem; background:transparent; border-bottom:1px solid rgba(95,110,140,.15); padding:.85rem .15rem; }
    .provider-row:last-child { border-bottom:0; }
    .provider-dot { width:.55rem; height:.55rem; flex:0 0 .55rem; border-radius:0; background:#25b879; box-shadow:none; }
    .provider-dot.warn { background:#f06a47; box-shadow:none; }
    .provider-meta { color:#65728a; font-size:.86rem; margin-top:.08rem; }
    .root-cause-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-1); margin:var(--space-1) 0; }
    .cause-item { background:var(--surface-muted); border:1px solid var(--border); border-radius:var(--radius-control); padding:var(--space-2); }
    .cause-label { color:#69758b; font-size:.68rem; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }
    .cause-value { color:#172033; font-size:1rem; font-weight:800; margin-top:.15rem; }
    .merchant-hero { position:static; color:var(--text); background:var(--surface) !important; border:1px solid var(--border); border-radius:var(--radius-card); padding:8px var(--space-3); margin-bottom:18px; box-shadow:none; }
    .hero-row { display:flex; align-items:center; gap:var(--space-2); min-width:0; }
    .hero-title { font-size:20px; line-height:24px; font-weight:700; letter-spacing:-.02em; margin:0; }
    .hero-subtitle { color:var(--muted); font-size:12px; line-height:16px; margin-top:var(--space-1); }
    .merchant-hero.rappi-hero { color:var(--text); background:var(--surface) !important; border:1px solid var(--border); }
    .rappi-hero .hero-subtitle { color:#697386; }
    .rappi-hero .live-pill { color:#c2412d; background:#fff0eb; border-color:#ffd7ca; }
    .live-pill { display:inline-block; color:#a92d39; background:#fcebed; border:1px solid #f3cdd2; border-radius:1px; padding:2px 6px; font-size:10px; line-height:16px; font-weight:750; letter-spacing:.05em; }
    .live-pill::first-letter { animation:live-pulse 1.4s ease-in-out infinite; }
    .live-note { color:var(--muted); font-size:12px; font-weight:500; margin-left:var(--space-2); text-transform:none; letter-spacing:0; }
    @keyframes live-pulse { 0%,100% { opacity:1; } 50% { opacity:.35; } }
    .executive-summary { position:static; display:block; clear:both; margin:0; padding:0; }
    .executive-summary .section-header { position:static; display:flex; align-items:baseline; gap:var(--space-2); margin:0 0 8px; }
    .executive-summary .section-header .eyebrow { margin:0; }
    .executive-summary .section-header .live-note { margin-left:0; }
    .kpi-row { position:static; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:var(--space-2); margin:0; padding:0; background:transparent; border:0; box-shadow:none; }
    .kpi-card { position:relative; overflow:hidden; min-height:68px; min-width:0; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:10px var(--space-3); box-shadow:none; }
    .kpi-card::before { display:none; }
    .kpi-label { color:var(--muted); font-size:12px; line-height:16px; font-weight:600; margin-bottom:var(--space-1); }
    .kpi-value { color:var(--text); font-size:26px; line-height:28px; font-weight:750; letter-spacing:-.03em; white-space:nowrap; }
    .kpi-card.incident { background:var(--surface) !important; border-color:#efc8cd !important; box-shadow:none; }
    .kpi-card.incident::after { content:""; position:absolute; top:var(--space-4); right:var(--space-4); width:8px; height:8px; border-radius:50%; background:var(--danger); }
    .kpi-card.incident .kpi-label { color:var(--muted) !important; }
    .kpi-card.incident .kpi-value { color:var(--danger) !important; }
    .kpi-link { color:inherit !important; text-decoration:none !important; display:block; }
    .kpi-link .kpi-card { transition:transform .18s ease,box-shadow .18s ease; }
    .kpi-link:hover .kpi-card { border-color:#dcaeb4 !important; box-shadow:var(--shadow); }
    .st-key-chart_section { position:static; display:block; clear:both; margin:0; padding:0; }
    .st-key-chart_section > [data-testid="stVerticalBlock"] { gap:6px; }
    .st-key-chart_section h3 { margin:0 !important; }
    .chart-top-spacer { height:20px; }
    .approval-chart { margin-bottom:-4px; }
    .approval-chart svg { display:block; }
    .country-row { display:flex; align-items:center; flex-wrap:wrap; gap:0; min-height:38px; margin:0 0 var(--space-2); padding:7px 10px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); }
    .country-anchor { height:0; margin-top:0; }
    .country-entry { display:flex; align-items:center; gap:6px; white-space:nowrap; font-size:13px; }
    .country-entry + .country-entry::before { content:"|"; margin:0 12px; color:#a5adba; }
    .country-name { font-weight:700; }
    .country-rate { color:var(--text); font-variant-numeric:tabular-nums; }
    .country-separator { color:#a5adba; }
    .injector-shell { background:#f8fafc; border:1px solid #d7dee9; border-left:3px solid var(--merchant-primary); border-radius:0; padding:1rem 1.2rem; margin:.5rem 0 1rem; }
    [data-testid="stExpander"] { border:1px solid var(--border) !important; border-radius:0 !important; background:var(--surface) !important; }
    [data-testid="stExpander"] details { border-radius:0 !important; }
    @media (max-width:900px) { .block-container { padding-inline:var(--space-6); } .kpi-row { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    @media (max-width:900px) { .primary-alert { grid-template-columns:1fr; } .alert-side { justify-content:space-between; } .alert-facts { text-align:left; white-space:normal; } }
    @media (max-width:640px) { .block-container { padding-inline:var(--space-4); } .kpi-row { grid-template-columns:1fr; } .alert-side { align-items:flex-start; flex-direction:column; } }
</style>
""",
    unsafe_allow_html=True,
)

st.session_state["live_playback"] = True

pending_merchant = st.session_state.pop("pending_monitored_company", None)
if pending_merchant in MERCHANT_DATA:
    # This is applied before the selectbox is created, which is the safe
    # Streamlit way to switch context after a Judge Lab submission.
    st.session_state["monitored_company"] = pending_merchant

if "monitored_company" not in st.session_state:
    st.session_state["monitored_company"] = "Rappi"
current_merchant = st.session_state["monitored_company"]

st.markdown(
    """
    <style>
      .st-key-demo_toolbar {
        background:#152238 !important;
        border:1px solid #243852 !important;
        border-top:3px solid var(--merchant-primary) !important;
        border-radius:0 !important;
        padding:10px 14px 12px !important;
        margin:2px 0 14px !important;
        box-shadow:none !important;
      }
      .st-key-demo_toolbar [data-testid="stSelectbox"] label {
        color:#b9cce7 !important; font-size:10px !important; font-weight:750 !important;
        letter-spacing:.08em !important; text-transform:uppercase !important;
      }
      .st-key-demo_toolbar div[data-baseweb="select"] > div {
        min-height:34px !important; background:rgba(255,255,255,.11) !important;
        border:1px solid rgba(255,255,255,.28) !important; border-radius:1px !important;
        color:#fff !important;
      }
      .st-key-demo_toolbar div[data-baseweb="select"] * { color:#fff !important; }
      .st-key-demo_toolbar .stButton button {
        min-height:36px !important; border-radius:1px !important; border:1px solid #fff !important;
        background:#fff !important; color:#183357 !important; font-weight:750 !important;
      }
      .toolbar-kicker { color:#a9c8e8; font-size:10px; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }
      .toolbar-title { color:#fff; font-size:16px; font-weight:760; letter-spacing:-.02em; margin-top:1px; }
      .toolbar-copy { color:#d7e6f7; font-size:12px; line-height:17px; margin-top:2px; }
      .toolbar-live { display:inline-flex; align-items:center; gap:6px; border-radius:1px; padding:5px 9px; font-size:10px; font-weight:750; letter-spacing:.06em; }
      .toolbar-live.on { color:#b8f7d5; background:rgba(29,171,108,.18); border:1px solid rgba(133,239,184,.28); }
      .toolbar-live.off { color:#ffe0aa; background:rgba(231,157,44,.16); border:1px solid rgba(255,210,130,.25); }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="demo_toolbar"):
    toolbar_logo, toolbar_brand, toolbar_merchant, toolbar_status = st.columns(
        [0.45, 2.05, 1.65, 3.15], vertical_alignment="center"
    )
    with toolbar_logo:
        st.image(MERCHANT_LOGOS[current_merchant], width=40)
    with toolbar_brand:
        st.markdown(
            "<div class='toolbar-kicker'>NextWave · payment operations</div>"
            "<div class='toolbar-title'>Control Tower</div>",
            unsafe_allow_html=True,
        )
    with toolbar_merchant:
        merchant = st.selectbox(
            "Merchant",
            list(MERCHANT_DATA),
            key="monitored_company",
        )
    with toolbar_status:
        st.markdown(
            "<span class='toolbar-live on'>● LIVE MONITORING</span>"
            "<div class='toolbar-copy'>One simulated payment window is processed every 5 seconds.</div>",
            unsafe_allow_html=True,
        )


live_playback = True

if st.session_state.pop("dashboard_judge_reset_pending", False):
    clear_scope_state(key_prefix="dashboard_judge")
    clear_scope_state(key_prefix="judge_lab")

with st.popover("Judge Lab"):
    st.markdown("#### Inject test incident")
    st.caption("Configure a simulated degradation without leaving the dashboard.")
    # This must stay outside the form. Streamlit submits forms atomically, so a
    # country change inside it would leave the bank and method choices from the
    # previous country on screen until after submission.
    lab_country = st.selectbox(
        "Country",
        ["Mexico", "Brazil", "Colombia"],
        key="judge_injection_country",
    )
    lab_scope = render_scope_selector(key_prefix="dashboard_judge")
    with st.form("judge_injection_form"):
        merchant_names = list(MERCHANT_DATA)
        lab_merchant = st.selectbox(
            "Merchant", merchant_names, index=merchant_names.index(merchant)
        )
        lab_slice = render_scope_filter(
            country=lab_country,
            scope=lab_scope,
            key_prefix="dashboard_judge",
        )
        target_rate = st.slider("Target approval rate", 0, 100, 30, 5)
        duration_windows = st.slider(
            "Duration (simulated windows)",
            min_value=6,
            max_value=60,
            value=30,
            step=6,
            help="Each window represents five simulated minutes. 30 windows keep a demo incident visible for about 2.5 real minutes.",
        )
        inject = st.form_submit_button(
            "Inject incident", type="primary", width="stretch"
        )

    if inject:
        config = InjectionConfig(
            merchant=lab_merchant,
            country=lab_country,
            provider=lab_slice.provider,
            payment_method=lab_slice.payment_method,
            issuing_bank=lab_slice.issuing_bank,
            target_approval_rate=target_rate / 100,
            duration_windows=duration_windows,
        )

        try:
            response = requests.post(
                f"{API_BASE_URL}/injections",
                json={"config": config.model_dump(mode="json")},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            incidents_after_injection = fetch_merchant_incidents(lab_merchant) or []
            detected_incident = next(
                (
                    item
                    for item in incidents_after_injection
                    if item["incident"]["country"] == lab_country
                ),
                None,
            )

            st.session_state["last_injection"] = {
                **config.model_dump(mode="json"),
                "injection_id": result["injection_id"],
                "detected_incident_id": (
                    detected_incident["incident"]["incident_id"]
                    if detected_incident is not None
                    else None
                ),
            }
            st.session_state["pending_monitored_company"] = lab_merchant
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Could not create the test injection: {exc}")

    last_injection = st.session_state.get("last_injection")
    if last_injection:
        st.success(f"Submitted to simulator: {last_injection['injection_id']}")
        selected_filters = [
            value
            for value in (
                last_injection.get("provider"),
                last_injection.get("payment_method"),
                last_injection.get("issuing_bank"),
            )
            if value is not None
        ]
        st.caption(
            "Injected slice: "
            + (" · ".join(selected_filters) if selected_filters else "all payment traffic")
        )
        if last_injection.get("detected_incident_id"):
            st.caption(
                "Detector confirmed the incident: "
                f"{last_injection['detected_incident_id']}"
            )
        else:
            st.warning(
                "The injection is active, but it has not met the detector "
                "thresholds yet. Keep live monitoring running."
            )
        st.caption(
            "The detector only receives the generated transactions, "
            "never this configuration."
        )
    active_injection = st.session_state.get("active_injection")
    if active_injection:
        active = active_injection
        st.error(
            f"Active: {active['merchant']} / {active['country']} / {active['target_approval_rate']:.0%}"
        )

    if last_injection or active_injection:
        if st.button("Reset demo", width="stretch"):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/monitor/reset",
                    timeout=30,
                )
                response.raise_for_status()
                st.session_state.pop("last_injection", None)
                st.session_state.pop("active_injection", None)
                st.session_state.pop("injection_id", None)
                st.session_state["dashboard_judge_reset_pending"] = True
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Backend reset failed: {exc}")


data = deepcopy(MERCHANT_DATA[merchant])
theme = MERCHANT_THEMES[merchant]
hero_class = "merchant-hero rappi-hero" if merchant == "Rappi" else "merchant-hero"

live_incidents = fetch_merchant_incidents(merchant) if live_playback else None

# When the API is available, it is the source of truth: no synthetic UI

if live_incidents is not None:
    data["updated"] = "just now"
    data["incident"] = None

    if live_incidents:
        primary = select_display_incident(live_incidents, merchant)
        raw_incident = primary["incident"]
        diagnosis = primary["diagnosis"]
        evidence = diagnosis["evidence"]
        remediation = primary.get("remediation")

        country_state = data["countries"][raw_incident["country"]]
        country_state["approval"] = raw_incident["actual_conversion"] * 100
        country_state["expected"] = raw_incident["expected_conversion"] * 100
        country_state["transactions"] = raw_incident["affected_volume"]
        country_state["loss"] = raw_incident["estimated_loss"]
        country_state["status"] = {
            "low": "Stable",
            "medium": "Attention",
            "high": "Critical",
            "critical": "Critical",
        }[raw_incident["severity"]]

        trend = data["trend"][raw_incident["country"]]
        trend[-2] = round(raw_incident["expected_conversion"] * 100, 1)
        trend[-1] = round(raw_incident["actual_conversion"] * 100, 1)

        dimension_labels = {
            "merchant": "Merchant",
            "country": "Country",
            "provider": "Provider",
            "payment_method": "Method",
            "issuing_bank": "Issuing bank",
            "decline_code": "Decline code",
            "intersection": "Intersection",
        }
        root_cause = {"Country": raw_incident["country"]}
        for item in evidence:
            # Evidence arrives ranked. Keep the strongest value for each
            # dimension instead of replacing it with a weaker secondary slice.
            root_cause.setdefault(
                dimension_labels[item["dimension"]], item["value"]
            )

        headline_evidence = [
            item
            for item in evidence
            if item["dimension"] in {"provider", "payment_method", "issuing_bank"}
        ][:2]
        affected_slice = " · ".join(
            item["value"] for item in headline_evidence
        ) or "payment traffic"

        routing_recommendation = None
        if remediation is not None:
            selected_simulation = next(
                (
                    item
                    for item in remediation["alternatives"]
                    if item["option"]["option_id"]
                    == remediation["recommended_option_id"]
                ),
                None,
            )
            routing_recommendation = {
                "recommendation_id": remediation["recommendation_id"],
                "merchant": raw_incident["merchant"],
                "status": remediation["status"],
                "rationale": remediation["rationale"],
                "confidence": remediation.get("confidence", 0.0),
                "traffic_cap": remediation.get("proposed_traffic_cap"),
                "abstention_reason": remediation.get("abstention_reason"),
                "required_approval": remediation["required_approval"],
                "rollback_reference": remediation.get("rollback_reference"),
                "target_provider": (
                    selected_simulation["option"]["target_provider"]
                    if selected_simulation is not None
                    else None
                ),
                "expected_recovery_per_hour": (
                    selected_simulation["expected_recovered_value_per_hour"]
                    if selected_simulation is not None
                    else 0.0
                ),
            }

        data["incident"] = {
            "incident_id": raw_incident["incident_id"],
            "detected_at": raw_incident["detected_at"],
            "estimated_loss": raw_incident["estimated_loss"],
            "severity": raw_incident["severity"].title(),
            "country": raw_incident["country"],
            "title": f"{affected_slice} approval degradation",
            "root_cause": root_cause,
            "diagnosis_status": diagnosis["diagnosis_status"],
            "diagnosis": diagnosis["explanation"],
            "diagnosis_points": [
                (
                    f"{dimension_labels[item['dimension']]}: "
                    f"{item['value']} "
                    f"({item['baseline_metric']:.1%} → "
                    f"{item['live_metric']:.1%})"
                )
                for item in evidence
            ],
            "recommendation": diagnosis["recommended_action"],
            "confidence": diagnosis["confidence"],
            "remediation": primary.get("remediation"),
            "routing_recommendation": routing_recommendation,
        }

countries = data["countries"]
total_transactions = sum(item["transactions"] for item in countries.values())
total_loss = sum(item["loss"] for item in countries.values())
weighted_approval = (
    sum(item["approval"] * item["transactions"] for item in countries.values())
    / total_transactions
)
weighted_expected = (
    sum(item["expected"] * item["transactions"] for item in countries.values())
    / total_transactions
)

incident = data["incident"]
recovery_log = (
    remember_incident_recovery(incident, merchant)
    if incident
    else sorted(
        st.session_state.get("incident_recovery_log", {}).values(),
        key=lambda entry: entry["observed_at"],
        reverse=True,
    )
)
active_incidents = (
    len(live_incidents) if live_incidents is not None else (1 if incident else 0)
)
st.markdown(
    f"""
    <style>
        :root {{ --merchant-primary: {theme['primary']}; --merchant-dark: {theme['dark']}; --merchant-soft: {theme['soft']}; --merchant-background: {theme['background']}; --merchant-accent: {theme['accent']}; }}
        .event-name,.team-name {{ color: var(--merchant-dark); }}
        .merchant-hero {{ background:var(--surface) !important; }}
        [data-testid="stAppViewContainer"] {{ background:#eef2f6; }}
        [data-testid="stSidebar"] {{ background:var(--surface); }}
        [data-testid="stMetric"]:hover {{ border-color:var(--border); }}
        div[data-baseweb="select"] > div:focus-within {{ border-color: var(--merchant-primary); box-shadow: 0 0 0 1px var(--merchant-primary); }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.fragment(run_every="2s")
def render_live_header() -> None:
    tick = st.session_state.get("header_live_tick", 0) + 1
    st.session_state["header_live_tick"] = tick
    seconds_ago = (tick * 2) % 6
    st.markdown(
        f"""
        <div id="overview"></div>
        <div class="{hero_class}">
            <div class="hero-row">
                <span class="live-pill">● LIVE MONITORING</span>
                <div class="hero-title">{merchant} Payment Control Tower</div>
            </div>
            <div class="hero-subtitle">Unified payment monitoring across Mexico, Brazil and Colombia — Updated {seconds_ago} seconds ago</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


render_live_header()

st.markdown('<div id="incidents"></div>', unsafe_allow_html=True)
if incident:
    incident_country = countries[incident["country"]]
    st.markdown(
        f"""
        <div class="primary-alert">
            <div>
                <div class="alert-kicker">🚨 ACTIVE INCIDENT</div>
                <div class="alert-country">{incident['country']}</div>
                <div class="alert-title">{incident['title']}</div>
            </div>
            <div class="alert-side">
                <div class="alert-facts">
                    Approval {incident_country['expected']:.1f}% → {incident_country['approval']:.1f}%
                    &nbsp; · &nbsp; Drop {incident_country['expected'] - incident_country['approval']:.1f} pp
                    &nbsp; · &nbsp; Estimated loss {format_usd(incident_country['loss'])}
                    &nbsp; · &nbsp; Confidence {incident['confidence']:.0%}
                </div>
                <a class="alert-action" href="#incident-detail">View diagnosis ↓</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="healthy-alert"><b>✓ No active incidents</b> · All monitored countries are operating within expected ranges.</div>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every="5s")
def render_live_summary() -> None:
    snapshot = st.session_state.get("monitoring_snapshot")
    if live_playback:
        snapshot = advance_and_fetch_monitoring(merchant)
        if snapshot is not None:
            st.session_state["monitoring_snapshot"] = snapshot

    if snapshot is None:
        detail = st.session_state.get("live_api_error")
        st.warning(
            "Waiting for the live Control Tower API. Start FastAPI to begin monitoring."
            + (f" Details: {detail}" if detail else "")
        )
        return

    active = fetch_merchant_incidents(merchant)
    active_items = (
        active
        if active is not None
        else st.session_state.get("latest_live_incidents", [])
    )
    if active is not None:
        st.session_state["latest_live_incidents"] = active_items
    incident_count = len(active_items)
    live_approval = snapshot["actual_approval_rate"] * 100
    expected_approval = snapshot["expected_approval_rate"] * 100
    approval_gap = expected_approval - live_approval
    live_transactions = snapshot["attempted_transactions"]
    live_estimated_loss = sum(
        item["incident"]["estimated_loss"] for item in active_items
    )
    incident_class = " incident" if incident_count else ""

    st.markdown(
        f"""
        <div id="report"></div>
        <section class="executive-summary">
            <div class="section-header">
                <div class="eyebrow">Executive summary</div>
                <span class="live-note">Real simulator · updates every 5 seconds</span>
            </div>
            <div class="kpi-row">
                <div class="kpi-card">
                    <div class="kpi-label">Approval rate · live</div>
                    <div class="kpi-value">{live_approval:.1f}%</div>
                    <div class="kpi-label">Expected {expected_approval:.1f}% · gap {approval_gap:.1f} pp</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Transactions · live</div>
                    <div class="kpi-value">{live_transactions:,}</div>
                </div>
                <div class="kpi-card{incident_class}">
                    <div class="kpi-label">Estimated loss · active incidents</div>
                    <div class="kpi-value">{format_usd(live_estimated_loss)}</div>
                </div>
                <a class="kpi-link" href="#incident-detail">
                    <div class="kpi-card{incident_class}">
                        <div class="kpi-label">Active incidents</div>
                        <div class="kpi-value">{incident_count}</div>
                    </div>
                </a>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


render_live_summary()


@st.fragment(run_every="5s")
def render_live_visuals() -> None:
    snapshot = st.session_state.get("monitoring_snapshot")
    if snapshot is None:
        st.info("Live chart will appear after the first simulator window.")
        return

    live_trends: dict[str, list[float]] = {}
    live_countries: dict[str, dict[str, Any]] = {}
    for country in snapshot["countries"]:
        country_name = country["country"]
        history = [rate * 100 for rate in country["approval_history"]]
        live_trends[country_name] = history or [country["actual_approval_rate"] * 100]
        live_countries[country_name] = {
            "expected": country["expected_approval_rate"] * 100,
        }
    try:
        window_end = datetime.fromisoformat(snapshot["window_end"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        window_end = None
    collected_windows = max((len(values) for values in live_trends.values()), default=0)
    st.caption(
        f"Rolling 30-day simulated window · {collected_windows:,} of 8,640 windows collected"
    )
    render_approval_chart(live_trends, live_countries, theme, window_end)

    incidents = st.session_state.get("latest_live_incidents", [])
    loss_by_country: dict[str, float] = {}
    severity_by_country: dict[str, str] = {}
    severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    for item in incidents:
        active_incident = item["incident"]
        country_name = active_incident["country"]
        loss_by_country[country_name] = (
            loss_by_country.get(country_name, 0.0)
            + active_incident["estimated_loss"]
        )
        existing = severity_by_country.get(country_name, "low")
        if severity_rank[active_incident["severity"]] >= severity_rank[existing]:
            severity_by_country[country_name] = active_incident["severity"]

    st.markdown('<div id="countries" class="country-anchor"></div>', unsafe_allow_html=True)
    st.markdown("### Country status")
    status_class_for = {
        "Stable": "status-ok",
        "Attention": "status-watch",
        "Critical": "status-critical",
    }
    country_entries = []
    for country in snapshot["countries"]:
        country_name = country["country"]
        severity = severity_by_country.get(country_name)
        status = (
            "Critical"
            if severity in {"high", "critical"}
            else "Attention"
            if severity in {"low", "medium"}
            else "Stable"
        )
        actual = country["actual_approval_rate"] * 100
        expected = country["expected_approval_rate"] * 100
        country_entries.append(
            f"<div class='country-entry'><span class='country-name'>{country_name}</span>"
            f"<span class='country-separator'>·</span><span class='country-rate'>{actual:.1f}%</span>"
            f"<span class='country-separator'>/</span><span class='country-rate'>{expected:.1f}% expected</span>"
            f"<span class='country-separator'>·</span><span class='country-rate'>{format_usd(loss_by_country.get(country_name, 0.0))}</span>"
            f"<span class='country-separator'>·</span>"
            f"<span class='{status_class_for[status]}'>{status}</span></div>"
        )
    st.markdown(
        f"<div class='country-row'>{''.join(country_entries)}</div>",
        unsafe_allow_html=True,
    )


if False:  # Kept as a Vega reference; pyarrow is blocked by the Windows policy.
    chart_rows = []
    for country, approvals in live_trends.items():
        expected = countries[country]["expected"]
        for index, approval in enumerate(approvals):
            drop = approval - expected
            chart_rows.append(
                {
                    "window": index + 1,
                    "country": country,
                    "approval": approval,
                    "expected": expected,
                    "difference": drop,
                    "status": "Critical drop" if drop <= -8 else "Normal",
                }
            )

    st.vega_lite_chart(
        chart_rows,
        {
            "background": "transparent",
            "layer": [
                {
                    "mark": {"type": "line", "strokeWidth": 2.5, "strokeCap": "round"},
                    "encoding": {
                        "x": {
                            "field": "window",
                            "type": "ordinal",
                            "title": "Latest windows",
                        },
                        "y": {
                            "field": "approval",
                            "type": "quantitative",
                            "scale": {"domain": [55, 100]},
                            "title": "Approval %",
                        },
                        "color": {
                            "field": "country",
                            "type": "nominal",
                            "title": "Country",
                            "scale": {
                                "range": [
                                    theme["primary"],
                                    theme["accent"],
                                    theme["dark"],
                                ]
                            },
                            "legend": {"symbolType": "stroke", "symbolStrokeWidth": 4},
                        },
                    },
                },
                {
                    "mark": {"type": "point", "size": 220, "opacity": 0},
                    "encoding": {
                        "x": {"field": "window", "type": "ordinal"},
                        "y": {"field": "approval", "type": "quantitative"},
                        "tooltip": [
                            {"field": "country", "type": "nominal", "title": "Country"},
                            {"field": "window", "type": "ordinal", "title": "Window"},
                            {
                                "field": "approval",
                                "type": "quantitative",
                                "title": "Approval",
                                "format": ".1f",
                            },
                            {
                                "field": "expected",
                                "type": "quantitative",
                                "title": "Expected",
                                "format": ".1f",
                            },
                            {
                                "field": "difference",
                                "type": "quantitative",
                                "title": "Difference (pp)",
                                "format": "+.1f",
                            },
                            {"field": "status", "type": "nominal", "title": "Status"},
                        ],
                    },
                },
                {
                    "transform": [{"filter": "datum.status === 'Critical drop'"}],
                    "mark": {
                        "type": "point",
                        "filled": True,
                        "size": 90,
                        "color": "#dc2638",
                        "stroke": "white",
                        "strokeWidth": 2,
                    },
                    "encoding": {
                        "x": {"field": "window", "type": "ordinal"},
                        "y": {"field": "approval", "type": "quantitative"},
                        "tooltip": [
                            {
                                "field": "country",
                                "type": "nominal",
                                "title": "⚠ Affected country",
                            },
                            {
                                "field": "approval",
                                "type": "quantitative",
                                "title": "Approval",
                                "format": ".1f",
                            },
                            {
                                "field": "expected",
                                "type": "quantitative",
                                "title": "Expected",
                                "format": ".1f",
                            },
                            {
                                "field": "difference",
                                "type": "quantitative",
                                "title": "Drop (pp)",
                                "format": "+.1f",
                            },
                        ],
                    },
                },
                {
                    "transform": [{"filter": "datum.status === 'Critical drop'"}],
                    "mark": {
                        "type": "text",
                        "text": "!",
                        "dy": -15,
                        "fontSize": 14,
                        "fontWeight": "bold",
                        "color": "#b91c2c",
                    },
                    "encoding": {
                        "x": {"field": "window", "type": "ordinal"},
                        "y": {"field": "approval", "type": "quantitative"},
                    },
                },
            ],
            "config": {
                "view": {"stroke": None},
                "axis": {
                    "gridColor": "rgba(90,105,135,.15)",
                    "domain": False,
                    "tickColor": "transparent",
                    "labelColor": "#68758c",
                    "titleColor": "#68758c",
                    "titlePadding": 4,
                },
                "legend": {"labelColor": "#68758c", "titleColor": "#68758c"},
            },
            "height": 290,
        },
        use_container_width=True,
    )


with st.container(key="chart_section"):
    st.markdown('<div class="chart-top-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div id="monitoring"></div>', unsafe_allow_html=True)
    st.markdown("### Approval rate — live")
    render_live_visuals()

st.markdown(
    '<div id="incident-detail"></div><div id="diagnosis"></div>', unsafe_allow_html=True
)
st.markdown("### Root cause, recommended recovery & simulation")
if incident is None:
    st.success("There are no active incidents to simulate.", icon="✅")
else:
    evidence_column, simulation_column = st.columns((1, 1.45))
    with evidence_column:
        with st.container(border=True):
            st.markdown("#### Why is approval falling?")
            root_cause_items = "".join(
                f"<div class='cause-item'><div class='cause-label'>{label}</div>"
                f"<div class='cause-value'>{value}</div></div>"
                for label, value in incident["root_cause"].items()
            )
            st.markdown(
                f"<div class='root-cause-grid'>{root_cause_items}</div>",
                unsafe_allow_html=True,
            )
            for point in incident["diagnosis_points"]:
                st.markdown(f"- {point}")
            st.caption(f"Evidence confidence: {incident['confidence']:.0%}")
    with simulation_column:
        with st.container(border=True):
            st.markdown("#### Recommended action")
            routing = incident.get("routing_recommendation")
            if routing is None:
                st.info(incident["recommendation"], icon="💡")
            elif routing["status"] == "recommended":
                st.info(
                    f"Shift {routing['traffic_cap']:.0%} of the affected traffic "
                    f"to {routing['target_provider']}.",
                    icon="💡",
                )
                st.caption(
                    f"Estimated recovery: US$ "
                    f"{routing['expected_recovery_per_hour']:,.0f}/h · "
                    f"Confidence: {routing['confidence']:.0%}"
                )
                st.write(routing["rationale"])
                st.caption(
                    "Recommendation only · Human approval required · "
                    "No routing change has occurred"
                )
                _render_routing_workflow(routing)
            else:
                st.warning("No routing change recommended. Continue monitoring.")
                st.caption(
                    routing["abstention_reason"] or routing["rationale"]
                )
                _render_recommendation_audit(routing["recommendation_id"])

render_incident_recovery_log(recovery_log)

st.caption("Control Tower MVP — Simulated data for validating the demo flow")
