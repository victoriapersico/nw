from __future__ import annotations

import pytest
from frontend.alerts_client import (
    AlertsClientError,
    acknowledge_alert,
    alert_icon,
    alert_title,
    build_alert_view_model,
    fetch_alerts,
)


class FakeResponse:
    def __init__(self, payload, *, ok: bool = True, status_code: int = 200) -> None:
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


def test_fetch_alerts_uses_the_unread_filter(monkeypatch) -> None:
    captured = {}

    def fake_get(url, *, params, timeout):
        captured.update(url=url, params=params, timeout=timeout)
        return FakeResponse([])

    monkeypatch.setattr("frontend.alerts_client.requests.get", fake_get)

    assert fetch_alerts("http://api", acknowledged=False) == []
    assert captured == {
        "url": "http://api/alerts",
        "params": {"acknowledged": "false"},
        "timeout": 5,
    }


def test_acknowledge_alert_posts_the_operator_payload(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse({"alert_id": "alert-1", "acknowledged": True})

    monkeypatch.setattr("frontend.alerts_client.requests.post", fake_post)

    assert acknowledge_alert("http://api", "alert-1") == {
        "alert_id": "alert-1",
        "acknowledged": True,
    }
    assert captured == {
        "url": "http://api/alerts/alert-1/acknowledge",
        "json": {"acknowledged_by": "merchant-operator"},
        "timeout": 5,
    }


def test_http_errors_become_safe_client_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        "frontend.alerts_client.requests.get",
        lambda *_, **__: FakeResponse(
            {"detail": "internal database path"}, ok=False, status_code=500
        ),
    )

    with pytest.raises(AlertsClientError, match="temporarily unavailable"):
        fetch_alerts("http://api")


@pytest.mark.parametrize(
    ("alert_type", "expected_title", "expected_icon"),
    [
        ("incident_detected", "Incident detected", ":material/error:"),
        ("approval_required", "Approval required", ":material/approval:"),
        ("rollback_triggered", "Simulation rolled back", ":material/undo:"),
    ],
)
def test_known_alert_types_have_deterministic_titles_and_icons(
    alert_type: str, expected_title: str, expected_icon: str
) -> None:
    assert alert_title(alert_type) == expected_title
    assert alert_icon(alert_type) == expected_icon


def test_incomplete_or_unknown_alerts_do_not_break_the_view_model() -> None:
    view = build_alert_view_model({"alert_id": "alert-unknown", "payload": {}})

    assert view["title"] == "Operational notification"
    assert view["icon"] == ":material/notifications:"
    assert view["details"] == []
    assert view["created_at"] == "Time unavailable"


def test_payload_text_is_html_escaped_before_presentation() -> None:
    view = build_alert_view_model(
        {
            "alert_id": "alert-1",
            "type": "rollback_triggered",
            "created_at": "2025-09-02T13:00:00+00:00",
            "acknowledged": False,
            "payload": {"reason": "<img src=x onerror=alert(1)>", "actor": "<b>ops</b>"},
        }
    )

    assert "<img" not in " ".join(view["details"])
    assert "&lt;img" in " ".join(view["details"])
    assert "<b>" not in " ".join(view["details"])


def test_acknowledged_alerts_include_operator_metadata() -> None:
    view = build_alert_view_model(
        {
            "alert_id": "alert-1",
            "type": "approval_required",
            "created_at": "2025-09-02T13:00:00+00:00",
            "acknowledged": True,
            "acknowledged_by": "merchant-operator",
            "acknowledged_at": "2025-09-02T13:05:00+00:00",
            "payload": {"merchant": "Rappi"},
        }
    )

    assert view["acknowledged"] is True
    assert "merchant-operator" in view["acknowledgement"]
    assert "Sep 02, 2025" in view["acknowledgement"]
