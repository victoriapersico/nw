"""Send one named Yuno sandbox fixture to the local Control Tower API."""

from __future__ import annotations

import argparse
import json

from scripts.yuno_sandbox import SCENARIOS, build_demo_webhook, post_webhook


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="valid",
        help="All cases except invalid-signature are validly signed.",
    )
    parser.add_argument(
        "--invalid-transaction",
        action="store_true",
        help="Compatibility alias for --scenario invalid-transaction.",
    )
    args = parser.parse_args()
    if args.invalid_transaction:
        args.scenario = "invalid-transaction"

    payload, signature = build_demo_webhook(args.scenario)
    status, result = post_webhook(payload, signature, api_base_url=args.url)
    print(json.dumps({"http_status": status, **result}, indent=2))


if __name__ == "__main__":
    main()
