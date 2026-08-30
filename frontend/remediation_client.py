"""HTTP client for the human-approved simulated routing workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

import requests


class RemediationClientError(RuntimeError):
    """Raised when the local remediation API rejects or cannot serve a request."""


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
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
        raise RemediationClientError(
            "The remediation API is unavailable."
        ) from exc
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RemediationClientError(str(detail or "Remediation request failed."))
    return response.json()


def fetch_workflow(base_url: str, recommendation_id: str) -> dict[str, Any]:
    result = _request_json(
        "GET",
        base_url,
        f"/remediation/workflows/{recommendation_id}",
    )
    assert isinstance(result, dict)
    return result


def record_decision(
    base_url: str,
    recommendation_id: str,
    merchant: str,
    decision: Literal["approved", "rejected"],
    *,
    decided_by: str = "merchant-operator",
    note: str | None = None,
) -> dict[str, Any]:
    operation_id = uuid4().hex
    result = _request_json(
        "POST",
        base_url,
        "/remediation/approvals",
        payload={
            "decision_id": f"approval-{operation_id}",
            "recommendation_id": recommendation_id,
            "merchant": merchant,
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": f"approval-request-{operation_id}",
            "note": note,
        },
    )
    assert isinstance(result, dict)
    return result


def revoke_approval(
    base_url: str,
    decision_id: str,
    merchant: str,
    *,
    revoked_by: str = "merchant-operator",
) -> dict[str, Any]:
    result = _request_json(
        "POST",
        base_url,
        f"/remediation/approvals/{decision_id}/revoke",
        payload={
            "merchant": merchant,
            "revoked_by": revoked_by,
            "reason": "Operator revoked approval before simulation activation.",
        },
    )
    assert isinstance(result, dict)
    return result


def apply_simulated_change(
    base_url: str,
    recommendation_id: str,
    approval_decision_id: str,
    rollback_reference: str,
) -> dict[str, Any]:
    result = _request_json(
        "POST",
        base_url,
        "/remediation/changes",
        payload={
            "recommendation_id": recommendation_id,
            "approval_decision_id": approval_decision_id,
            "idempotency_key": f"change-{uuid4().hex}",
            "rollback_reference": rollback_reference,
        },
    )
    assert isinstance(result, dict)
    return result


def fetch_simulated_change(base_url: str, change_id: str) -> dict[str, Any]:
    result = _request_json(
        "GET",
        base_url,
        f"/remediation/changes/{change_id}",
    )
    assert isinstance(result, dict)
    return result


def rollback_simulated_change(
    base_url: str,
    change_id: str,
    *,
    decided_by: str = "merchant-operator",
) -> dict[str, Any]:
    result = _request_json(
        "POST",
        base_url,
        f"/remediation/changes/{change_id}/rollback",
        payload={
            "decided_by": decided_by,
            "reason": "Operator reverted the simulated routing change.",
        },
    )
    assert isinstance(result, dict)
    return result


def complete_simulated_change(
    base_url: str,
    change_id: str,
    *,
    decided_by: str = "merchant-operator",
) -> dict[str, Any]:
    result = _request_json(
        "POST",
        base_url,
        f"/remediation/changes/{change_id}/complete",
        payload={
            "decided_by": decided_by,
            "note": "Operator completed the healthy simulated rollout review.",
        },
    )
    assert isinstance(result, dict)
    return result


def fetch_audit(
    base_url: str,
    recommendation_id: str,
) -> list[dict[str, Any]]:
    result = _request_json(
        "GET",
        base_url,
        "/remediation/audit",
        params={"recommendation_id": recommendation_id},
    )
    assert isinstance(result, list)
    return result
