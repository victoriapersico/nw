"""HTTP contract tests for incident-scoped assistant questions."""

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.schemas import IncidentAssistantResponse


class _AssistantTowerStub:
    def answer_incident_question(self, incident_id, request):
        if incident_id == "missing":
            raise KeyError(incident_id)
        if request.merchant != "Rappi":
            raise PermissionError("The requested merchant does not own this incident.")
        return IncidentAssistantResponse(
            incident_id=incident_id,
            answer="The deterministic evidence supports a provider-level cause.",
            answerable=True,
            evidence=[],
            mode="mock",
        )


def test_incident_assistant_endpoint_returns_structured_grounded_answer(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_control_tower",
        lambda: _AssistantTowerStub(),
    )

    with TestClient(main_module.app) as client:
        response = client.post(
            "/incidents/inc-api-test/assistant",
            json={"merchant": "Rappi", "question": "What is the root cause?"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "incident_id": "inc-api-test",
        "answer": "The deterministic evidence supports a provider-level cause.",
        "answerable": True,
        "evidence": [],
        "mode": "mock",
    }


def test_incident_assistant_endpoint_enforces_incident_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "get_control_tower",
        lambda: _AssistantTowerStub(),
    )

    with TestClient(main_module.app) as client:
        forbidden = client.post(
            "/incidents/inc-api-test/assistant",
            json={"merchant": "Carrefour", "question": "What happened?"},
        )
        missing = client.post(
            "/incidents/missing/assistant",
            json={"merchant": "Rappi", "question": "What happened?"},
        )

    assert forbidden.status_code == 403
    assert missing.status_code == 404
