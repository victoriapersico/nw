"""Reusable local fixtures and HTTP helpers for the Yuno sandbox demo."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.schemas import Transaction
from backend.yuno_mock import build_payment_webhook, sign_webhook


YUNO_ACCOUNT_ID = "yuno-rappi-sandbox"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
SCENARIOS = (
    "valid",
    "invalid-transaction",
    "missing-transaction-id",
    "invalid-amount",
    "merchant-mismatch",
    "invalid-payment-country",
    "unsupported-schema",
    "invalid-signature",
)


def build_demo_webhook(scenario: str) -> tuple[dict[str, Any], str]:
    """Return one named scenario and its appropriate signature."""

    if scenario not in SCENARIOS:
        raise ValueError(f"unsupported demo scenario: {scenario}")

    transaction = Transaction(
        transaction_id="txn-yuno-demo-001",
        merchant="Rappi",
        provider="Stripe",
        payment_method="PIX",
        country="Brazil",
        issuing_bank="Ita\u00fa",
        decline_code="91",
        status="declined",
        amount=120.50,
        timestamp=datetime(2025, 9, 2, 13, tzinfo=timezone.utc),
    )
    payload = build_payment_webhook(
        transaction,
        account_id=YUNO_ACCOUNT_ID,
        event_id=f"yuno-demo-{scenario}",
    )
    transaction_payload = payload["data"]["payment"]["transaction"]
    if scenario == "invalid-transaction":
        transaction_payload["decline_code"] = "91@"
    elif scenario == "missing-transaction-id":
        del transaction_payload["transaction_id"]
    elif scenario == "invalid-amount":
        transaction_payload["amount"] = 0
    elif scenario == "merchant-mismatch":
        transaction_payload["merchant"] = "Carrefour"
    elif scenario == "invalid-payment-country":
        transaction_payload["payment_method"] = "PSE"
    elif scenario == "unsupported-schema":
        payload["version"] = "99"

    signature = (
        "not-a-real-signature"
        if scenario == "invalid-signature"
        else sign_webhook(payload)
    )
    return payload, signature


def post_webhook(
    payload: dict[str, Any], signature: str, *, api_base_url: str = DEFAULT_API_BASE_URL
) -> tuple[int, dict[str, Any]]:
    """Submit a fixture and return an HTTP status plus decoded JSON body."""

    request = Request(
        f"{api_base_url}/v1/sandbox/yuno-webhooks",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-hmac-signature": signature},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_json(path: str, *, api_base_url: str = DEFAULT_API_BASE_URL) -> Any:
    """Read a JSON endpoint from the locally running demo API."""

    with urlopen(f"{api_base_url}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
