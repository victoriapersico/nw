"""Local email outbox used to demonstrate notification delivery safely."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.yuno_mock import MockYunoSystemAlert


class MockEmailMessage(BaseModel):
    """A rendered email that would be handed to an SMTP/email provider later."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    to: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    text_body: str = Field(min_length=1)
    created_at: datetime
    source_event_id: str = Field(min_length=1)


class MockEmailOutbox:
    """Idempotent local stand-in for sending operational emails."""

    def __init__(self) -> None:
        self._messages: list[MockEmailMessage] = []
        self._sent_source_events: set[str] = set()

    def send_yuno_system_alert(
        self, alert: MockYunoSystemAlert
    ) -> MockEmailMessage | None:
        if alert.source_event_id in self._sent_source_events:
            return None

        message = MockEmailMessage(
            message_id=f"mail-{uuid4().hex}",
            to="payments-ops@yuno-sandbox.local",
            subject=(
                "[SYSTEM] Yuno webhook ingestion error "
                f"— account {alert.yuno_account_id}"
            ),
            text_body=(
                "Control Tower detected a signed sandbox webhook that could not "
                "be normalized.\n\n"
                f"Account: {alert.yuno_account_id}\n"
                f"Source event: {alert.source_event_id}\n"
                f"Error: {alert.error_code}\n"
                f"Field: {alert.field_path}\n"
                f"Action: Review the source payload and encoding before retrying.\n"
            ),
            created_at=datetime.now(timezone.utc),
            source_event_id=alert.source_event_id,
        )
        self._messages.append(message)
        self._sent_source_events.add(alert.source_event_id)
        return message

    @property
    def messages(self) -> tuple[MockEmailMessage, ...]:
        return tuple(self._messages)
