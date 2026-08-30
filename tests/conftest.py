"""Test-wide safety defaults for optional external integrations."""

import pytest


@pytest.fixture(autouse=True)
def disable_telegram_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """No unit or API test is allowed to send a real Telegram message."""

    monkeypatch.setenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false")
