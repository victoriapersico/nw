"""Small HTTP client and presentation helpers for the local alert inbox."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

import requests


class AlertsClientError(RuntimeError):
    """Raised when the local notifications API cannot serve a safe response."""


def _error_message(response: requests.Response) -> str:
    """Avoid exposing arbitrary server response bodies in the operator UI."""

    if response.status_code == 404:
        return "This notification is no longer available."
    return "Notifications are temporarily unavailable."


def fetch_alerts(
    base_url: str, acknowledged: bool | None = None
) -> list[dict[str, Any]]:
    """Fetch backend-owned alerts, optionally filtered by acknowledgement state."""

    params = (
        {"acknowledged": str(acknowledged).lower()}
        if acknowledged is not None
        else None
    )
    try:
        response = requests.get(f"{base_url}/alerts", params=params, timeout=5)
    except requests.RequestException as exc:
        raise AlertsClientError("Notifications are temporarily unavailable.") from exc
    if not response.ok:
        raise AlertsClientError(_error_message(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise AlertsClientError("Notifications returned an invalid response.") from exc
    if not isinstance(payload, list):
        raise AlertsClientError("Notifications returned an invalid response.")
    return payload


def acknowledge_alert(
    base_url: str,
    alert_id: str,
    acknowledged_by: str = "merchant-operator",
) -> dict[str, Any]:
    """Acknowledge one backend-owned alert without optimistic local mutation."""

    try:
        response = requests.post(
            f"{base_url}/alerts/{alert_id}/acknowledge",
            json={"acknowledged_by": acknowledged_by},
            timeout=5,
        )
    except requests.RequestException as exc:
        raise AlertsClientError("Notifications are temporarily unavailable.") from exc
    if not response.ok:
        raise AlertsClientError(_error_message(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise AlertsClientError("Notifications returned an invalid response.") from exc
    if not isinstance(payload, dict):
        raise AlertsClientError("Notifications returned an invalid response.")
    return payload


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    return escape(str(value), quote=True)


def format_alert_timestamp(value: object) -> str:
    """Format API timestamps defensively without making up a fallback date."""

    if not isinstance(value, str):
        return "Time unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Time unavailable"
    timezone_label = parsed.tzname() or "local time"
    return f"{parsed:%b %d, %Y · %H:%M} {timezone_label}"


def alert_title(alert_type: object) -> str:
    return {
        "incident_detected": "Incident detected",
        "approval_required": "Approval required",
        "rollback_triggered": "Simulation rolled back",
    }.get(str(alert_type), "Operational notification")


def alert_icon(alert_type: object) -> str:
    return {
        "incident_detected": ":material/error:",
        "approval_required": ":material/approval:",
        "rollback_triggered": ":material/undo:",
    }.get(str(alert_type), ":material/notifications:")


def build_alert_view_model(alert: dict[str, Any]) -> dict[str, Any]:
    """Turn an alert contract into display-only, HTML-safe deterministic text."""

    payload = alert.get("payload") if isinstance(alert.get("payload"), dict) else {}
    alert_type = str(alert.get("type", ""))
    details: list[str] = []
    metadata: list[str] = []

    if alert_type == "incident_detected":
        for label, key in (("Merchant", "merchant"), ("Country", "country"), ("Severity", "severity")):
            value = _safe_text(payload.get(key))
            if value is not None:
                details.append(f"{label}: {value}")
        incident_id = _safe_text(alert.get("incident_id"))
        if incident_id is not None:
            metadata.append(f"Incident: {incident_id}")
    elif alert_type == "approval_required":
        merchant = _safe_text(payload.get("merchant"))
        if merchant is not None:
            details.append(f"Merchant: {merchant}")
        details.append("A routing recommendation is waiting for human review.")
        recommendation_id = _safe_text(alert.get("recommendation_id"))
        if recommendation_id is not None:
            metadata.append(f"Recommendation: {recommendation_id}")
    elif alert_type == "rollback_triggered":
        reason = _safe_text(payload.get("reason"))
        actor = _safe_text(payload.get("actor"))
        if reason is not None:
            details.append(f"Reason: {reason}")
        if actor is not None:
            details.append(f"Actor: {actor}")
        details.append("This was a simulated routing change, not a production rollback.")
        change_id = _safe_text(alert.get("change_id"))
        if change_id is not None:
            metadata.append(f"Change: {change_id}")

    acknowledged_by = _safe_text(alert.get("acknowledged_by"))
    acknowledged_at = alert.get("acknowledged_at")
    acknowledgement = None
    if bool(alert.get("acknowledged")):
        acknowledgement = "Acknowledged"
        if acknowledged_by is not None:
            acknowledgement += f" by {acknowledged_by}"
        if acknowledged_at is not None:
            acknowledgement += f" · {format_alert_timestamp(acknowledged_at)}"

    severity = str(payload.get("severity", "")).lower()
    tone = (
        "critical"
        if alert_type == "incident_detected" and severity in {"high", "critical"}
        else "approval"
        if alert_type == "approval_required"
        else "neutral"
    )
    return {
        "alert_id": str(alert.get("alert_id", "unknown")),
        "title": alert_title(alert_type),
        "icon": alert_icon(alert_type),
        "details": details,
        "metadata": metadata,
        "created_at": format_alert_timestamp(alert.get("created_at")),
        "acknowledged": bool(alert.get("acknowledged")),
        "acknowledgement": acknowledgement,
        "tone": tone,
    }
