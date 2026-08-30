"""Contracts for the Streamlit notification API client."""

from typing import Any

import pytest
import requests

from frontend.notification_client import (
    NotificationClientError,
    acknowledge_alert,
    fetch_alerts,
    fetch_similar_cases,
    generate_post_incident_report,
)


class Response:
    def __init__(self, payload: dict[str, Any] | list[dict[str, Any]], ok: bool = True):
        self._payload = payload
        self.ok = ok
        self.text = "request failed"

    def json(self):
        return self._payload


def test_alert_client_uses_backend_contracts(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> Response:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/alerts"):
            return Response([{"alert_id": "alert-1"}])
        if url.endswith("/similar-cases"):
            return Response([{"incident_id": "inc-1"}])
        return Response({"incident_id": "inc-1"})

    monkeypatch.setattr(requests, "request", fake_request)

    assert fetch_alerts("http://api", acknowledged=False) == [{"alert_id": "alert-1"}]
    assert acknowledge_alert("http://api", "alert-1")["incident_id"] == "inc-1"
    assert fetch_similar_cases("http://api", "inc-1") == [{"incident_id": "inc-1"}]
    assert generate_post_incident_report("http://api", "inc-1")["incident_id"] == "inc-1"
    assert calls[0]["params"] == {"acknowledged": False}
    assert calls[1]["json"] == {"acknowledged_by": "merchant-operator"}
    assert calls[2]["url"].endswith("/incidents/inc-1/similar-cases")
    assert calls[3]["method"] == "POST"


def test_client_translates_connection_errors(monkeypatch) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise requests.RequestException("offline")

    monkeypatch.setattr(requests, "request", unavailable)

    with pytest.raises(NotificationClientError, match="unavailable"):
        fetch_alerts("http://api")
