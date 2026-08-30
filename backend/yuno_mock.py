"""Local-only Yuno webhook simulator and safe ingestion adapter.

The payload shape intentionally mirrors the public Yuno webhook envelope while the
embedded transaction is a fixture for this project. Replace this adapter with an
approved Yuno mapping before connecting production credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.schemas import Diagnosis, Incident, Merchant, Severity, Transaction


DEFAULT_MOCK_YUNO_SECRET = "local-yuno-mock-secret"
MOCK_ACCOUNT_MERCHANTS: dict[str, Merchant] = {
    "yuno-rappi-sandbox": "Rappi",
    "yuno-carrefour-sandbox": "Carrefour",
    "yuno-despegar-sandbox": "Despegar",
}


class YunoMockWebhookError(ValueError):
    """Raised for invalid mock webhook signatures or payloads."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "transaction_validation_failed",
        field_path: str = "data.payment.transaction",
        trusted: bool = True,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.field_path = field_path
        self.trusted = trusted


@dataclass(frozen=True, slots=True)
class IngestedYunoWebhook:
    event_id: str
    duplicate: bool
    transaction: Transaction | None


class MockYunoWebhookReceipt(BaseModel):
    """Acknowledgement for local sandbox webhook testing only."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    accepted: bool
    duplicate: bool
    transaction_id: str | None = None
    error_code: str | None = None


class MockYunoAlert(BaseModel):
    """The safe, post-diagnosis alert a Yuno consumer would receive."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: str = "payment.incident.detected"
    occurred_at: datetime
    yuno_account_id: str = Field(min_length=1)
    merchant: Merchant
    severity: Severity
    incident: Incident
    diagnosis: Diagnosis


class MockYunoAlertInbox:
    """In-memory substitute for outbound partner webhook delivery."""

    def __init__(self, account_merchants: dict[str, Merchant] | None = None) -> None:
        self._account_merchants = account_merchants or MOCK_ACCOUNT_MERCHANTS
        self._merchant_accounts = {
            merchant: account_id
            for account_id, merchant in self._account_merchants.items()
        }
        self._alerts: list[MockYunoAlert] = []
        self._notified_incident_ids: set[str] = set()

    def notify(self, incident: Incident, diagnosis: Diagnosis) -> MockYunoAlert | None:
        """Record one alert per incident, just as an idempotent webhook sender would."""

        if incident.incident_id in self._notified_incident_ids:
            return None
        account_id = self._merchant_accounts.get(incident.merchant)
        if account_id is None:
            raise YunoMockWebhookError("merchant has no configured sandbox account")

        alert = MockYunoAlert(
            event_id=f"nw-alert-{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            yuno_account_id=account_id,
            merchant=incident.merchant,
            severity=incident.severity,
            incident=incident,
            diagnosis=diagnosis,
        )
        self._alerts.append(alert)
        self._notified_incident_ids.add(incident.incident_id)
        return alert

    def alerts_for(self, account_id: str) -> tuple[MockYunoAlert, ...]:
        return tuple(
            alert for alert in self._alerts if alert.yuno_account_id == account_id
        )


class MockYunoSystemAlert(BaseModel):
    """Safe integration failure notification addressed to Yuno operations."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: str = "system.integration_error"
    occurred_at: datetime
    yuno_account_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    error_code: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class MockYunoSystemAlertOutbox:
    """In-memory stand-in for an email or operations-webhook sender."""

    def __init__(self) -> None:
        self._alerts: list[MockYunoSystemAlert] = []
        self._dedupe_keys: set[tuple[str, str]] = set()

    def notify_failure(
        self,
        *,
        account_id: str,
        source_event_id: str,
        error_code: str,
        field_path: str,
        summary: str,
    ) -> MockYunoSystemAlert | None:
        dedupe_key = (source_event_id, error_code)
        if dedupe_key in self._dedupe_keys:
            return None
        alert = MockYunoSystemAlert(
            event_id=f"nw-system-{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            yuno_account_id=account_id,
            source_event_id=source_event_id,
            error_code=error_code,
            field_path=field_path,
            summary=summary,
        )
        self._alerts.append(alert)
        self._dedupe_keys.add(dedupe_key)
        return alert

    def alerts_for(self, account_id: str) -> tuple[MockYunoSystemAlert, ...]:
        return tuple(
            alert for alert in self._alerts if alert.yuno_account_id == account_id
        )


def build_payment_webhook(
    transaction: Transaction,
    *,
    account_id: str,
    event_id: str,
    retry: int = 0,
) -> dict[str, Any]:
    """Build a deterministic sandbox fixture resembling a Yuno payment event."""

    return {
        "account_id": account_id,
        "idempotency_key": event_id,
        "type": "payment",
        "type_event": "payment.purchase",
        "version": "2",
        "retry": retry,
        "data": {
            "payment": {
                "id": f"yuno-{transaction.transaction_id}",
                "status": transaction.status.upper(),
                "sub_status": transaction.decline_code or "APPROVED",
                "connection_data": {
                    "id": f"mock-{transaction.provider.lower()}-{transaction.country.lower()}",
                    "name": transaction.provider,
                },
                "transaction": transaction.model_dump(mode="json"),
            }
        },
    }


def sign_webhook(payload: dict[str, Any], secret: str = DEFAULT_MOCK_YUNO_SECRET) -> str:
    """Return a base64 HMAC-SHA256 signature for a simulated webhook."""

    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), _canonical_json(payload), hashlib.sha256).digest()
    ).decode("ascii")


class MockYunoWebhookIngestor:
    """Verify, deduplicate and normalize simulated Yuno payment webhooks."""

    def __init__(
        self,
        *,
        secret: str = DEFAULT_MOCK_YUNO_SECRET,
        account_merchants: dict[str, Merchant] | None = None,
    ) -> None:
        self._secret = secret
        self._account_merchants = account_merchants or MOCK_ACCOUNT_MERCHANTS
        self._seen_event_ids: set[str] = set()

    def ingest(
        self, payload: dict[str, Any], signature: str | None
    ) -> IngestedYunoWebhook:
        self._verify_signature(payload, signature)
        try:
            event_id = str(payload["idempotency_key"])
            account_id = str(payload["account_id"])
            transaction_payload = payload["data"]["payment"]["transaction"]
        except (KeyError, TypeError) as exc:
            raise YunoMockWebhookError(
                "missing required simulated Yuno payment fields",
                error_code="missing_required_field",
                field_path="data.payment.transaction",
            ) from exc

        if not event_id:
            raise YunoMockWebhookError(
                "idempotency_key must not be blank",
                error_code="missing_required_field",
                field_path="idempotency_key",
            )
        if event_id in self._seen_event_ids:
            return IngestedYunoWebhook(event_id=event_id, duplicate=True, transaction=None)

        if payload.get("type") != "payment" or payload.get("version") != "2":
            raise YunoMockWebhookError(
                "unsupported simulated Yuno webhook schema",
                error_code="unsupported_webhook_schema",
                field_path="type/version",
            )

        merchant = self._account_merchants.get(account_id)
        if merchant is None:
            raise YunoMockWebhookError(
                "unknown sandbox account_id",
                error_code="merchant_mapping_failed",
                field_path="account_id",
            )

        try:
            transaction = Transaction.model_validate(transaction_payload)
        except ValidationError as exc:
            raise _transaction_validation_error(exc) from exc
        if transaction.merchant != merchant:
            raise YunoMockWebhookError(
                "account_id does not match transaction merchant",
                error_code="merchant_mapping_failed",
                field_path="data.payment.transaction.merchant",
            )

        self._seen_event_ids.add(event_id)
        return IngestedYunoWebhook(
            event_id=event_id,
            duplicate=False,
            transaction=transaction,
        )

    def _verify_signature(self, payload: dict[str, Any], signature: str | None) -> None:
        if not signature:
            raise YunoMockWebhookError(
                "missing x-hmac-signature",
                error_code="invalid_signature",
                field_path="x-hmac-signature",
                trusted=False,
            )
        expected = sign_webhook(payload, self._secret)
        if not hmac.compare_digest(signature, expected):
            raise YunoMockWebhookError(
                "invalid x-hmac-signature",
                error_code="invalid_signature",
                field_path="x-hmac-signature",
                trusted=False,
            )


def _transaction_validation_error(exc: ValidationError) -> YunoMockWebhookError:
    """Map schema failures to stable, operations-friendly notification codes."""

    errors = exc.errors()
    first_error = errors[0] if errors else {}
    location = first_error.get("loc", ())
    leaf = str(location[-1]) if location else "transaction"
    message = str(first_error.get("msg", "transaction validation failed"))
    field_path = f"data.payment.transaction.{leaf}"

    if leaf == "amount":
        return YunoMockWebhookError(
            message,
            error_code="invalid_amount",
            field_path=field_path,
        )
    if leaf == "transaction_id" and first_error.get("type") == "missing":
        return YunoMockWebhookError(
            message,
            error_code="missing_required_field",
            field_path=field_path,
        )
    if "payment_method" in message and "not valid" in message:
        return YunoMockWebhookError(
            message,
            error_code="invalid_payment_method_country",
            field_path="data.payment.transaction.payment_method",
        )
    return YunoMockWebhookError(
        message,
        error_code="transaction_validation_failed",
        field_path=field_path,
    )


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
