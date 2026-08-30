"""Guided terminal demonstration for the NextWave x Yuno sandbox boundary."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.error import URLError

from scripts.yuno_sandbox import (
    DEFAULT_API_BASE_URL,
    YUNO_ACCOUNT_ID,
    build_demo_webhook,
    get_json,
    post_webhook,
)


MENU = {
    "1": ("valid", "Send a valid payment webhook"),
    "2": ("invalid-transaction", "Send malformed transaction data"),
    "3": ("invalid-amount", "Send an invalid transaction amount"),
    "4": ("merchant-mismatch", "Send an account-to-merchant mismatch"),
    "5": ("invalid-payment-country", "Send an incompatible payment method"),
    "6": ("unsupported-schema", "Send an unsupported webhook schema"),
    "7": ("invalid-signature", "Send an invalid signature (security check)"),
}


def _heading(text: str) -> None:
    print(f"\n{'=' * 66}\n{text}\n{'=' * 66}")


def _show_delivery(status: int, result: dict[str, Any]) -> None:
    _heading("WEBHOOK RESULT")
    print(f"HTTP status: {status}")
    if status == 401:
        print("Signature: rejected")
        print("Notification: not sent, because the origin is not trusted.")
        return

    if result.get("accepted"):
        print("Signature: verified")
        print("Result: accepted and normalized for payment monitoring.")
        print("Notification: no Yuno system alert is needed.")
        return

    print("Signature: verified")
    print("Result: safely rejected before it enters payment monitoring.")
    print(f"Error code: {result.get('error_code')}")
    print("Notification: Yuno Operations email created in the sandbox outbox.")
    if result.get("duplicate"):
        print("Duplicate protection: this retry did not create another notification.")


def _show_system_alerts(api_base_url: str) -> None:
    alerts = get_json(
        f"/v1/sandbox/yuno-system-alerts/{YUNO_ACCOUNT_ID}",
        api_base_url=api_base_url,
    )
    _heading("YUNO SYSTEM ALERTS")
    if not alerts:
        print("No system alerts yet.")
        return
    for alert in alerts:
        print(
            f"• {alert['error_code']} | {alert['field_path']}\n"
            f"  Event: {alert['source_event_id']}\n"
            f"  {alert['summary']}"
        )


def _show_emails(api_base_url: str) -> None:
    emails = get_json("/v1/sandbox/yuno-email-outbox", api_base_url=api_base_url)
    _heading("YUNO OPERATIONS - SANDBOX EMAIL OUTBOX")
    if not emails:
        print("No emails delivered yet.")
        return
    for email in emails:
        print(f"To: {email['to']}\nSubject: {email['subject']}\n\n{email['text_body']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_API_BASE_URL)
    args = parser.parse_args()

    _heading("NEXTWAVE x YUNO - SANDBOX INTEGRATION DEMO")
    print("Start the API first with: python -m uvicorn backend.main:app --reload")
    print("This console uses local fixtures only; it does not send real payment data.")

    while True:
        print("\nChoose a demo action:")
        for option, (_, label) in MENU.items():
            print(f"  {option}. {label}")
        print("  8. View Yuno system alerts")
        print("  9. View sandbox notification emails")
        print("  0. Exit")
        choice = input("\nSelection: ").strip()
        try:
            if choice == "0":
                print("Demo finished.")
                return
            if choice == "8":
                _show_system_alerts(args.url)
                continue
            if choice == "9":
                _show_emails(args.url)
                continue
            if choice not in MENU:
                print("Please choose one of the listed options.")
                continue

            scenario, label = MENU[choice]
            _heading(label.upper())
            payload, signature = build_demo_webhook(scenario)
            status, result = post_webhook(payload, signature, api_base_url=args.url)
            _show_delivery(status, result)
        except URLError:
            print("Could not reach the local API. Start uvicorn and try again.")


if __name__ == "__main__":
    main()
