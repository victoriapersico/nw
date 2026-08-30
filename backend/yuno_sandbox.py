"""Local-only Yuno API Manager sandbox used by the hackathon demo.

The sandbox models integration operations separately from merchant payment
monitoring. It records only safe, synthetic telemetry and never contacts Yuno,
an email provider, or a production payment system.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_MOCK_YUNO_SECRET = "local-yuno-mock-secret"
YUNO_ACCOUNT_ID = "yuno-rappi-sandbox"


class YunoSandboxError(ValueError):
    """A deterministic sandbox ingestion error with a trust boundary."""

    def __init__(self, message: str, *, error_code: str, trusted: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.trusted = trusted


class YunoWebhookReceipt(BaseModel):
    """Safe acknowledgement for a local sandbox webhook."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    accepted: bool
    duplicate: bool = False
    error_code: str | None = None


class YunoSystemAlert(BaseModel):
    """Trusted integration failure visible to the Yuno operations sandbox."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    occurred_at: datetime
    account_id: str
    source_event_id: str
    error_code: str
    summary: str


class YunoEmailMessage(BaseModel):
    """Rendered local email preview; nothing is sent externally."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    to: str
    subject: str
    text_body: str
    created_at: datetime
    source_event_id: str


class YunoApiEvent(BaseModel):
    """One redacted API-manager telemetry event."""

    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime
    source_event_id: str
    account_id: str | None = None
    outcome: Literal["accepted", "rejected", "duplicate", "unauthorized"]
    latency_ms: float = Field(ge=0)
    error_code: str | None = None


class YunoApiHealth(BaseModel):
    """Aggregate integration health for the Yuno sandbox dashboard."""

    model_config = ConfigDict(extra="forbid")

    account_id: str = "all_sandbox_accounts"
    status: Literal["idle", "healthy", "attention", "degraded"]
    total_requests: int = Field(ge=0)
    accepted_requests: int = Field(ge=0)
    rejected_requests: int = Field(ge=0)
    duplicate_requests: int = Field(ge=0)
    unauthorized_requests: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    p95_latency_ms: float = Field(ge=0)
    error_breakdown: dict[str, int] = Field(default_factory=dict)
    recent_events: list[YunoApiEvent] = Field(default_factory=list)


_SCENARIO_ERRORS: dict[str, str | None] = {
    "valid": None,
    "invalid-transaction": "transaction_validation_failed",
    "invalid-amount": "invalid_amount",
    "merchant-mismatch": "merchant_mapping_failed",
    "invalid-payment-country": "invalid_payment_method_country",
    "unsupported-schema": "unsupported_webhook_schema",
    "invalid-signature": "invalid_signature",
}


def sign_webhook(payload: dict[str, object]) -> str:
    """Sign a local fixture using the fixed, non-production sandbox secret."""

    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    digest = hmac.new(
        DEFAULT_MOCK_YUNO_SECRET.encode("utf-8"), canonical, hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("ascii")


class YunoSandbox:
    """In-memory integration telemetry and local alert outboxes."""

    def __init__(self) -> None:
        self._events: list[YunoApiEvent] = []
        self._alerts: list[YunoSystemAlert] = []
        self._emails: list[YunoEmailMessage] = []
        self._seen_event_ids: set[str] = set()

    def health(self) -> YunoApiHealth:
        total = len(self._events)
        counts = Counter(event.outcome for event in self._events)
        failures = counts["rejected"] + counts["unauthorized"]
        error_breakdown = Counter(
            event.error_code for event in self._events if event.error_code is not None
        )
        latencies = sorted(event.latency_ms for event in self._events)
        p95_index = max(0, int(len(latencies) * 0.95) - 1)
        if total == 0:
            status: Literal["idle", "healthy", "attention", "degraded"] = "idle"
        elif failures / total >= 0.10:
            status = "degraded"
        elif failures:
            status = "attention"
        else:
            status = "healthy"
        return YunoApiHealth(
            status=status,
            total_requests=total,
            accepted_requests=counts["accepted"],
            rejected_requests=counts["rejected"],
            duplicate_requests=counts["duplicate"],
            unauthorized_requests=counts["unauthorized"],
            success_rate=counts["accepted"] / total if total else 0.0,
            p95_latency_ms=latencies[p95_index] if latencies else 0.0,
            error_breakdown=dict(error_breakdown),
            recent_events=list(reversed(self._events[-10:])),
        )

    def events(self) -> list[YunoApiEvent]:
        return list(reversed(self._events))

    def alerts(self, account_id: str) -> list[YunoSystemAlert]:
        return [alert for alert in self._alerts if alert.account_id == account_id]

    def emails(self) -> list[YunoEmailMessage]:
        return list(self._emails)

    def seed_healthy_baseline(self) -> YunoApiHealth:
        """Load a clearly synthetic healthy baseline once per process."""

        if self._events:
            return self.health()
        for index in range(1, 13):
            self._record(
                source_event_id=f"yuno-demo-baseline-{index:03d}",
                account_id=YUNO_ACCOUNT_ID,
                outcome="accepted",
                latency_ms=30.0 + index * 2.5,
            )
        for index in range(1, 3):
            self._record(
                source_event_id=f"yuno-demo-retry-{index:03d}",
                account_id=YUNO_ACCOUNT_ID,
                outcome="duplicate",
                latency_ms=28.0 + index * 2.0,
            )
        return self.health()

    def record_demo_scenario(self, scenario: str) -> YunoWebhookReceipt:
        """Create one deterministic scenario for the visible sandbox controls."""

        if scenario not in _SCENARIO_ERRORS:
            raise KeyError(scenario)
        event_id = f"yuno-demo-{scenario}-{uuid4().hex[:12]}"
        if scenario == "invalid-signature":
            self._record(
                source_event_id=event_id,
                account_id=None,
                outcome="unauthorized",
                latency_ms=18.0,
                error_code="invalid_signature",
            )
            return YunoWebhookReceipt(
                event_id=event_id,
                accepted=False,
                error_code="invalid_signature",
            )
        error_code = _SCENARIO_ERRORS[scenario]
        if error_code is None:
            self._seen_event_ids.add(event_id)
            self._record(
                source_event_id=event_id,
                account_id=YUNO_ACCOUNT_ID,
                outcome="accepted",
                latency_ms=34.0,
            )
            return YunoWebhookReceipt(event_id=event_id, accepted=True)
        self._record_trusted_rejection(event_id, YUNO_ACCOUNT_ID, error_code)
        return YunoWebhookReceipt(
            event_id=event_id,
            accepted=False,
            error_code=error_code,
        )

    def ingest_webhook(
        self, payload: dict[str, object], signature: str | None
    ) -> YunoWebhookReceipt:
        """Verify a raw local fixture without ever sending external traffic."""

        event_id = str(payload.get("idempotency_key") or f"unidentified-{uuid4().hex}")
        if signature != sign_webhook(payload):
            self._record(
                source_event_id=event_id,
                account_id=None,
                outcome="unauthorized",
                latency_ms=18.0,
                error_code="invalid_signature",
            )
            raise YunoSandboxError(
                "invalid x-hmac-signature",
                error_code="invalid_signature",
                trusted=False,
            )
        account_id = str(payload.get("account_id") or "")
        if event_id in self._seen_event_ids:
            self._record(
                source_event_id=event_id,
                account_id=account_id or None,
                outcome="duplicate",
                latency_ms=12.0,
            )
            return YunoWebhookReceipt(event_id=event_id, accepted=True, duplicate=True)
        if account_id != YUNO_ACCOUNT_ID:
            self._record_trusted_rejection(event_id, account_id or YUNO_ACCOUNT_ID, "merchant_mapping_failed")
            return YunoWebhookReceipt(
                event_id=event_id,
                accepted=False,
                error_code="merchant_mapping_failed",
            )
        self._seen_event_ids.add(event_id)
        self._record(
            source_event_id=event_id,
            account_id=account_id,
            outcome="accepted",
            latency_ms=36.0,
        )
        return YunoWebhookReceipt(event_id=event_id, accepted=True)

    def _record_trusted_rejection(
        self, event_id: str, account_id: str, error_code: str
    ) -> None:
        self._seen_event_ids.add(event_id)
        self._record(
            source_event_id=event_id,
            account_id=account_id,
            outcome="rejected",
            latency_ms=42.0,
            error_code=error_code,
        )
        alert = YunoSystemAlert(
            event_id=f"yuno-system-{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            account_id=account_id,
            source_event_id=event_id,
            error_code=error_code,
            summary=(
                "A signed Yuno sandbox webhook could not be normalized: "
                f"{error_code}."
            ),
        )
        self._alerts.append(alert)
        self._emails.append(
            YunoEmailMessage(
                message_id=f"yuno-email-{uuid4().hex}",
                to="payments-ops@yuno-sandbox.local",
                subject=f"[SYSTEM] Yuno webhook error - {error_code}",
                text_body=(
                    "Control Tower isolated a trusted Yuno sandbox webhook before "
                    "it entered merchant monitoring.\n\n"
                    f"Account: {account_id}\nSource event: {event_id}\n"
                    f"Error: {error_code}\n"
                    "Action: review the source payload before retrying."
                ),
                created_at=datetime.now(timezone.utc),
                source_event_id=event_id,
            )
        )

    def _record(
        self,
        *,
        source_event_id: str,
        account_id: str | None,
        outcome: Literal["accepted", "rejected", "duplicate", "unauthorized"],
        latency_ms: float,
        error_code: str | None = None,
    ) -> None:
        self._events.append(
            YunoApiEvent(
                occurred_at=datetime.now(timezone.utc),
                source_event_id=source_event_id,
                account_id=account_id,
                outcome=outcome,
                latency_ms=latency_ms,
                error_code=error_code,
            )
        )
