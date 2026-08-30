"""Explicitly opt-in, best-effort Telegram delivery for the active local demo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import requests

from backend.schemas import Diagnosis, Incident, RoutingRecommendation, SimulationResult


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

    def notify_incident(
        self,
        incident: Incident,
        *,
        diagnosis: Diagnosis | None = None,
        recommendation: RoutingRecommendation | None = None,
    ) -> bool:
        """Deliver one incident event. Failures never interrupt monitoring.

        Telegram is deliberately read-only: it can describe the evidence and the
        proposed local simulation, but it never exposes approval or execution
        actions. Those remain in the Control Tower UI.
        """

        if not self.configured:
            return False

        payload: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": self._notification_text(incident, diagnosis, recommendation),
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

    @staticmethod
    def _selected_simulation(
        recommendation: RoutingRecommendation | None,
    ) -> SimulationResult | None:
        if recommendation is None or recommendation.recommended_option_id is None:
            return None
        return next(
            (
                simulation
                for simulation in recommendation.alternatives
                if simulation.option.option_id == recommendation.recommended_option_id
            ),
            None,
        )

    @classmethod
    def _notification_text(
        cls,
        incident: Incident,
        diagnosis: Diagnosis | None,
        recommendation: RoutingRecommendation | None,
    ) -> str:
        """Render only application-owned, read-only incident context."""

        lines = [
            "Incident detected",
            f"Merchant: {incident.merchant}",
            f"Country: {incident.country}",
            f"Severity: {incident.severity.title()}",
            (
                f"Approval: {incident.actual_conversion:.1%} vs "
                f"{incident.expected_conversion:.1%} expected"
            ),
            f"Estimated loss: US$ {incident.estimated_loss_per_hour:,.0f}/hour",
        ]

        if diagnosis is not None:
            lines.extend(["", "Evidence-backed diagnosis"])
            if diagnosis.evidence:
                strongest = diagnosis.evidence[0]
                lines.append(
                    f"Primary signal: {strongest.dimension} = {strongest.value}; "
                    f"approval {strongest.baseline_metric:.1%} to "
                    f"{strongest.live_metric:.1%} across "
                    f"{strongest.sample_size:,} attempts."
                )
            elif diagnosis.root_cause_dimensions:
                lines.append(
                    "Diagnosis is still collecting evidence for: "
                    f"{', '.join(diagnosis.root_cause_dimensions)}."
                )
            else:
                lines.append("No root-cause evidence is confirmed yet.")

        selected = cls._selected_simulation(recommendation)
        if recommendation is not None and recommendation.status == "recommended" and selected:
            lines.extend(
                [
                    "",
                    "Suggested dry-run",
                    (
                        "Simulate shifting "
                        f"{selected.option.traffic_shift_pct:.0%} of affected traffic "
                        f"to {selected.option.target_provider}."
                    ),
                    (
                        "Estimated recovery: US$ "
                        f"{selected.expected_recovered_value_per_hour:,.0f}/hour "
                        f"at {selected.confidence:.0%} simulation confidence."
                    ),
                    "This is a local simulation only. No production routing is changed.",
                    "Open Control Tower to approve or decline this suggestion.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "No routing simulation is currently recommended.",
                    "Open Control Tower to review the incident and its evidence.",
                ]
            )
        return "\n".join(lines)
