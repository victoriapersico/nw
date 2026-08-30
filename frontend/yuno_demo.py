"""Presentation-ready Yuno sandbox operations demo, separate from merchant UI."""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st

from scripts.yuno_sandbox import YUNO_ACCOUNT_ID, build_demo_webhook


API_BASE_URL = os.getenv("CONTROL_TOWER_API_URL", "http://127.0.0.1:8000")

SCENARIOS: list[tuple[str, str, str, str]] = [
    (
        "valid",
        "Valid payment",
        "A signed, valid payment event enters monitoring.",
        "safe",
    ),
    (
        "invalid-transaction",
        "Malformed transaction",
        "The transaction contains an invalid decline code.",
        "warning",
    ),
    (
        "invalid-amount",
        "Invalid amount",
        "The amount is zero and must be rejected safely.",
        "warning",
    ),
    (
        "merchant-mismatch",
        "Merchant mismatch",
        "The Yuno account does not match the transaction merchant.",
        "warning",
    ),
    (
        "invalid-payment-country",
        "Invalid payment method",
        "The payment method is not valid for the transaction country.",
        "warning",
    ),
    (
        "unsupported-schema",
        "Unsupported schema",
        "The event version is not supported by this integration.",
        "warning",
    ),
    (
        "invalid-signature",
        "Invalid signature",
        "Security check: an untrusted request is rejected with no alert.",
        "security",
    ),
]


def call_webhook(scenario: str) -> tuple[int, dict[str, Any]]:
    payload, signature = build_demo_webhook(scenario)
    response = requests.post(
        f"{API_BASE_URL}/v1/sandbox/yuno-webhooks",
        json=payload,
        headers={"x-hmac-signature": signature},
        timeout=10,
    )
    return response.status_code, response.json()


def get_json(path: str) -> Any | None:
    try:
        response = requests.get(f"{API_BASE_URL}{path}", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def load_healthy_api_baseline() -> bool:
    """Load only local, deterministic sandbox telemetry for the presentation."""

    try:
        response = requests.post(
            f"{API_BASE_URL}/v1/sandbox/yuno-api-demo-seed",
            timeout=5,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def render_result() -> None:
    result = st.session_state.get("yuno_last_result")
    if not result:
        st.info("Choose a scenario above to start the sandbox demonstration.")
        return

    status = result["status"]
    body = result["body"]
    title = result["title"]
    if status == 401:
        st.error(f"Security check complete — {title}")
        st.markdown(
            "**Signature:** rejected  \\\n+**Result:** the request was not trusted or processed.  \\\n+**Notification:** none; untrusted traffic never creates operational noise."
        )
        return

    if body.get("accepted"):
        st.success(f"Webhook accepted — {title}")
        st.markdown(
            "**Signature:** verified  \\\n+**Result:** payment normalized and ready for Control Tower monitoring.  \\\n+**Notification:** none required; this is a healthy integration event."
        )
        return

    st.warning(f"Integration issue safely isolated — {title}")
    duplicate_text = (
        "This retry was already notified; no duplicate email was created."
        if body.get("duplicate")
        else "A Yuno Operations notification was created in the sandbox outbox."
    )
    st.markdown(
        f"**Signature:** verified  \\\n+**Result:** rejected before entering payment monitoring.  \\\n+**Error code:** `{body.get('error_code')}`  \\\n+**Notification:** {duplicate_text}"
    )


st.set_page_config(
    page_title="NextWave × Yuno | Sandbox Operations",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      [data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu,
      [data-testid="stDecoration"] { display:none; }
      .block-container { max-width:1220px; padding:1.4rem 2rem 2rem; }
      [data-testid="stAppViewContainer"] { background:#f5f7fb; }
      html, body, [class*="css"] { font-family:"Segoe UI",Arial,sans-serif; }
      h1, h2, h3 { color:#15233e; letter-spacing:-.025em; }
      .hero { border-radius:18px; padding:1.4rem 1.7rem; margin-bottom:1rem;
        color:#fff; background:linear-gradient(115deg,#13213b,#234c85 62%,#2b86a5);
        box-shadow:0 12px 30px rgba(25,52,91,.18); }
      .eyebrow { font-size:.75rem; letter-spacing:.12em; font-weight:700;
        text-transform:uppercase; opacity:.75; }
      .hero h1 { color:#fff; margin:.18rem 0 .35rem; font-size:2.1rem; }
      .hero p { margin:0; max-width:760px; color:#dcecff; }
      .panel { background:#fff; border:1px solid #e1e8f1; border-radius:14px;
        padding:1rem 1.1rem; height:100%; }
      .meaning { border-left:3px solid #2b86a5; padding-left:.75rem; margin:.65rem 0; }
      div[data-testid="stButton"] button { min-height:78px; font-weight:650;
        text-align:left; white-space:normal; border:1px solid #ccd8e7;
        border-radius:11px; background:#fff; color:#172642; }
      div[data-testid="stButton"] button:hover { border-color:#2b86a5; color:#115a83;
        background:#f0fbff; }
      .caption { color:#62718a; font-size:.86rem; }
      [data-testid="stMetric"] { background:#fff; border:1px solid #e1e8f1;
        padding:.55rem .8rem; border-radius:11px; }
    </style>
    <div class="hero">
      <div class="eyebrow">NextWave × Yuno · sandbox integration</div>
      <h1>Yuno API Operations</h1>
      <p>Validate partner webhooks, isolate technical failures, and notify the right
      operations team — without confusing integration issues with merchant performance.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

api_healthy = get_json("/health") is not None
api_health = get_json("/v1/sandbox/yuno-api-health")
top_left, top_right = st.columns([3, 1])
with top_left:
    st.caption("Demo account: `yuno-rappi-sandbox` · Local sandbox only")
with top_right:
    st.success("API connected" if api_healthy else "API unavailable")

st.markdown("### API health")
if api_health is None:
    st.warning("API telemetry is unavailable. Start FastAPI to load the API Manager.")
else:
    status = api_health["status"]
    if status == "healthy":
        st.success("Healthy — all observed requests were accepted.")
    elif status == "attention":
        st.warning("Attention — trusted requests were rejected and need review.")
    elif status == "degraded":
        st.error("Degraded — API error rate is above the sandbox threshold.")
    else:
        st.info("Idle — send sandbox traffic to begin API health monitoring.")
    metric_one, metric_two, metric_three, metric_four = st.columns(4)
    metric_one.metric("Requests", api_health["total_requests"])
    metric_two.metric("Success rate", f"{api_health['success_rate']:.0%}")
    metric_three.metric("P95 latency", f"{api_health['p95_latency_ms']:.1f} ms")
    metric_four.metric("Trusted API errors", api_health["rejected_requests"])
    if api_health["total_requests"] == 0:
        if st.button("Load healthy sandbox baseline", type="primary"):
            if load_healthy_api_baseline():
                st.rerun()
            st.error("Could not load the sandbox baseline. Check FastAPI.")

st.markdown("### Sandbox traffic simulator")
st.caption("Use these controls to create observable API traffic and verify alert behavior.")
for row_start in range(0, len(SCENARIOS), 3):
    columns = st.columns(3)
    for column, (scenario, title, description, kind) in zip(
        columns, SCENARIOS[row_start : row_start + 3]
    ):
        with column:
            if st.button(f"{title}\n{description}", key=f"scenario_{scenario}", width="stretch"):
                try:
                    status, body = call_webhook(scenario)
                    st.session_state["yuno_last_result"] = {
                        "status": status,
                        "body": body,
                        "title": title,
                        "scenario": scenario,
                    }
                except requests.RequestException:
                    st.session_state["yuno_last_result"] = None
                    st.error("The local API is unavailable. Start the FastAPI server and try again.")

st.markdown("### Latest outcome")
render_result()

left, right = st.columns([1.05, 1])
with left:
    st.markdown("### What each result means")
    st.markdown(
        """
        <div class="panel">
          <div class="meaning"><b>Accepted</b><br><span class="caption">The event is signed,
          valid, and can become payment-monitoring evidence.</span></div>
          <div class="meaning"><b>Integration issue</b><br><span class="caption">The origin is
          trusted, but the payload is inconsistent. It is stopped before it distorts merchant metrics.</span></div>
          <div class="meaning"><b>Security rejection</b><br><span class="caption">The signature
          is invalid. We return 401 and do not send an alert based on untrusted traffic.</span></div>
          <div class="meaning"><b>Duplicate protection</b><br><span class="caption">A retry of
          the same event does not create a second notification.</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with right:
    st.markdown("### Why this matters to Yuno")
    st.markdown(
        """
        <div class="panel">
          <p><b>Correct owner:</b> a bad webhook is an integration-operations issue for Yuno,
          while an approval-rate drop is a merchant-performance issue.</p>
          <p><b>Clean monitoring:</b> invalid events never contaminate the statistical detector.</p>
          <p><b>Safe scale:</b> stable error codes, HMAC validation and idempotency provide the
          basis for real notification delivery later.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

alerts_tab, emails_tab, telemetry_tab, activity_tab, contract_tab = st.tabs(
    [
        "API alerts",
        "Notification emails",
        "Request telemetry",
        "Activity log",
        "API contract",
    ]
)
with alerts_tab:
    alerts = get_json(f"/v1/sandbox/yuno-system-alerts/{YUNO_ACCOUNT_ID}")
    if alerts is None:
        st.info("Start the API to inspect alerts.")
    elif not alerts:
        st.info("No trusted integration failures have been recorded yet.")
    else:
        for alert in reversed(alerts):
            with st.expander(
                f"{alert['error_code']} · {alert['source_event_id']}", expanded=False
            ):
                st.markdown(f"**Field:** `{alert['field_path']}`")
                st.markdown(alert["summary"])
                st.caption(f"Recorded at: {alert['occurred_at']}")
with emails_tab:
    emails = get_json("/v1/sandbox/yuno-email-outbox")
    if emails is None:
        st.info("Start the API to inspect notification emails.")
    elif not emails:
        st.info("No sandbox operation emails have been rendered yet.")
    else:
        for email in reversed(emails):
            with st.expander(f"{email['subject']} · {email['created_at']}"):
                st.caption(f"To: {email['to']}")
                st.code(email["text_body"], language=None)
with telemetry_tab:
    api_health = get_json("/v1/sandbox/yuno-api-health")
    if api_health is None:
        st.info("Start the API to inspect request telemetry.")
    elif not api_health["recent_events"]:
        st.info("No sandbox requests recorded yet.")
    else:
        for event in api_health["recent_events"]:
            st.markdown(
                f"**{event['outcome'].upper()}** · "
                f"{event['latency_ms']:.1f} ms · "
                f"{event.get('error_code') or 'no_error'}"
            )
            st.caption(event["occurred_at"])
with activity_tab:
    activity_log = get_json("/v1/sandbox/yuno-api-log")
    if activity_log is None:
        st.info("Start the API to inspect the activity log.")
    elif not activity_log:
        st.info("No API movements recorded yet. Send a sandbox request to begin the log.")
    else:
        st.download_button(
            "Download audit log (JSON)",
            data=json.dumps(activity_log, indent=2),
            file_name="yuno-api-activity-log.json",
            mime="application/json",
        )
        for event in activity_log:
            with st.expander(
                f"{event['outcome'].upper()} · {event['source_event_id']}",
                expanded=False,
            ):
                st.markdown(f"**Timestamp:** {event['occurred_at']}")
                st.markdown(f"**Account:** {event.get('account_id') or 'untrusted/unknown'}")
                st.markdown(f"**Latency:** {event['latency_ms']:.1f} ms")
                st.markdown(f"**Error:** `{event.get('error_code') or 'none'}`")
with contract_tab:
    st.markdown("Open the interactive FastAPI documentation for technical review:")
    st.code(f"{API_BASE_URL}/docs", language=None)
    st.caption("The demo uses local fixtures. No real payment data or real email is sent.")
