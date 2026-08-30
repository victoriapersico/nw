"""Unit coverage for opt-in Telegram incident delivery."""

from datetime import datetime, timezone

from backend.schemas import Incident
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

    assert notifier.notify_incident(_incident()) is True
    assert sent[0]["url"] == "https://api.telegram.org/bottelegram-token/sendMessage"
    payload = sent[0]["json"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "123"
    assert "Incident detected" in str(payload["text"])
    assert "No routing change is automatic" in str(payload["text"])
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
