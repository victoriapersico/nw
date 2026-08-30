"""Unit coverage for opt-in Telegram incident delivery."""

from datetime import datetime, timezone

from backend.schemas import (
    Diagnosis,
    EvidenceItem,
    Incident,
    RemediationOption,
    RoutingRecommendation,
    SimulationResult,
)
from backend.telegram_notifications import TelegramIncidentNotifier


class _Response:
    def raise_for_status(self) -> None:
        return None


def _incident() -> Incident:
    return Incident(
        incident_id="inc-rappi-brazil-001",
        merchant="Rappi",
        country="Brazil",
        detected_at=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
        expected_conversion=0.91,
        actual_conversion=0.42,
        conversion_drop_pp=49,
        affected_volume=120,
        estimated_loss=500,
        estimated_loss_per_hour=6_000,
        severity="high",
        anomaly_score=8,
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        incident_id="inc-rappi-brazil-001",
        root_cause_dimensions=["provider"],
        evidence=[
            EvidenceItem(
                dimension="provider",
                value="Stripe",
                baseline_metric=0.91,
                live_metric=0.42,
                delta=-0.49,
                sample_size=120,
                explained_loss_share=0.84,
            )
        ],
        confidence=0.91,
        diagnosis_status="confirmed",
        explanation="Provider-level degradation is evidenced.",
        recommended_action="Review the local simulation.",
    )


def _recommendation() -> RoutingRecommendation:
    simulation = SimulationResult(
        option=RemediationOption(
            option_id="route-adyen-25",
            target_provider="Adyen",
            traffic_shift_pct=0.25,
        ),
        status="eligible",
        expected_approval_rate=0.90,
        expected_recovered_value_per_hour=4_200,
        expected_incremental_cost_per_hour=0,
        confidence=0.88,
    )
    return RoutingRecommendation(
        recommendation_id="rec-rappi-brazil-001",
        incident_id="inc-rappi-brazil-001",
        policy_id="policy-rappi-brazil",
        status="recommended",
        recommended_option_id=simulation.option.option_id,
        alternatives=[simulation],
        rationale="Eligible local dry-run.",
        confidence=simulation.confidence,
        proposed_traffic_cap=simulation.option.traffic_shift_pct,
        rollback_reference="rollback-rappi-brazil-001",
    )


def test_incident_notification_contains_dashboard_link_and_no_action() -> None:
    sent: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> _Response:
        sent.append({"url": url, **kwargs})
        return _Response()

    notifier = TelegramIncidentNotifier(
        token="telegram-token",
        chat_id="123",
        dashboard_url="https://demo.nextwave.example/control-tower",
        enabled=True,
        post=post,
    )

    assert notifier.notify_incident(
        _incident(),
        diagnosis=_diagnosis(),
        recommendation=_recommendation(),
    ) is True
    assert sent[0]["url"] == "https://api.telegram.org/bottelegram-token/sendMessage"
    payload = sent[0]["json"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "123"
    assert "Incident detected" in str(payload["text"])
    assert "Primary signal: provider = Stripe" in str(payload["text"])
    assert "Simulate shifting 25% of affected traffic to Adyen" in str(payload["text"])
    assert "local simulation only" in str(payload["text"])
    assert "approve or decline this suggestion" in str(payload["text"])
    assert payload["reply_markup"] == {
        "inline_keyboard": [
            [
                {
                    "text": "Open Control Tower",
                    "url": "https://demo.nextwave.example/control-tower",
                }
            ]
        ]
    }


def test_unconfigured_notifier_does_not_attempt_delivery() -> None:
    def post(*_args: object, **_kwargs: object) -> _Response:
        raise AssertionError("A disabled notifier must not call Telegram")

    notifier = TelegramIncidentNotifier(enabled=False, post=post)

    assert notifier.notify_incident(_incident()) is False


def test_local_dashboard_url_sends_alert_without_invalid_telegram_button() -> None:
    sent: list[dict[str, object]] = []

    def post(_url: str, **kwargs: object) -> _Response:
        sent.append(kwargs)
        return _Response()

    notifier = TelegramIncidentNotifier(
        token="telegram-token",
        chat_id="123",
        dashboard_url="http://localhost:8502",
        enabled=True,
        post=post,
    )

    assert notifier.notify_incident(_incident()) is True
    assert "reply_markup" not in sent[0]["json"]
