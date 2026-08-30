"""HTTP client for the Control Tower notification, memory, and report APIs."""

from __future__ import annotations

from typing import Any

import requests


class NotificationClientError(RuntimeError):
    """Raised when the local notification API cannot complete a request."""


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    try:
        response = requests.request(
            method,
            f"{base_url}{path}",
            json=payload,
            params=params,
            timeout=5,
        )
    except requests.RequestException as exc:
        raise NotificationClientError("The notification API is unavailable.") from exc
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise NotificationClientError(str(detail or "Notification request failed."))
    return response.json()


def fetch_alerts(
    base_url: str, acknowledged: bool | None = None
) -> list[dict[str, Any]]:
    params = {"acknowledged": acknowledged} if acknowledged is not None else None
    result = _request_json("GET", base_url, "/alerts", params=params)
    assert isinstance(result, list)
    return result


def acknowledge_alert(
    base_url: str, alert_id: str, *, acknowledged_by: str = "merchant-operator"
) -> dict[str, Any]:
    result = _request_json(
        "POST",
        base_url,
        f"/alerts/{alert_id}/acknowledge",
        payload={"acknowledged_by": acknowledged_by},
    )
    assert isinstance(result, dict)
    return result


def fetch_similar_cases(base_url: str, incident_id: str) -> list[dict[str, Any]]:
    result = _request_json("GET", base_url, f"/incidents/{incident_id}/similar-cases")
    assert isinstance(result, list)
    return result


def generate_post_incident_report(base_url: str, incident_id: str) -> dict[str, Any]:
    result = _request_json(
        "POST", base_url, f"/incidents/{incident_id}/post-incident-report"
    )
    assert isinstance(result, dict)
    return result


def fetch_post_incident_report(base_url: str, incident_id: str) -> dict[str, Any]:
    result = _request_json(
        "GET", base_url, f"/incidents/{incident_id}/post-incident-report"
    )
    assert isinstance(result, dict)
    return result
