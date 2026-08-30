"""Explicitly opt-in, best-effort Telegram delivery for the active local demo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import requests

from backend.schemas import Incident


_TRUE_VALUES = {"1", "true", "yes", "on"}
_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass(frozen=True)
class TelegramIncidentNotifier:
    """Send a compact incident notification without affecting Control Tower state."""

    token: str | None = None
    chat_id: str | None = None
    dashboard_url: str | None = None
    enabled: bool = False
    post: Callable[..., Any] = requests.post

    @classmethod
    def from_environment(cls) -> "TelegramIncidentNotifier":
        """Build an explicitly opt-in notifier; unset configuration is a no-op."""

        enabled = (
            os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false").strip().lower()
            in _TRUE_VALUES
        )
        return cls(
            token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None,
            chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip() or None,
            dashboard_url=os.getenv("TELEGRAM_DASHBOARD_URL", "").strip() or None,
            enabled=enabled,
        )

    @property
    def configured(self) -> bool:
        return self.enabled and self.token is not None and self.chat_id is not None

    def notify_incident(self, incident: Incident) -> bool:
        """Deliver one incident event. Failures never interrupt monitoring."""

        if not self.configured:
            return False

        payload: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": (
                "🚨 Incident detected\n"
                f"Merchant: {incident.merchant}\n"
                f"Country: {incident.country}\n"
                f"Severity: {incident.severity.title()}\n"
                f"Approval: {incident.actual_conversion:.1%} vs "
                f"{incident.expected_conversion:.1%} expected\n"
                f"Estimated loss: US$ {incident.estimated_loss_per_hour:,.0f}/hour\n\n"
                "Review the evidence in Control Tower. No routing change is automatic."
            ),
        }
        # Telegram rejects localhost and non-HTTPS URLs in inline keyboard buttons.
        # Still deliver the alert during local demos; a public HTTPS dashboard URL
        # automatically enables the deep link.
        if self.dashboard_url and self.dashboard_url.startswith("https://"):
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Open Control Tower",
                            "url": self.dashboard_url,
                        }
                    ]
                ]
            }
        try:
            response = self.post(
                _SEND_MESSAGE_URL.format(token=self.token),
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException:
            return False
        return True
