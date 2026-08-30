"""Separate, local-only Yuno API Manager presentation dashboard."""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv


load_dotenv()
API_BASE_URL = os.getenv("CONTROL_TOWER_API_URL", "http://127.0.0.1:8000").rstrip("/")
YUNO_ACCOUNT_ID = "yuno-rappi-sandbox"

SCENARIOS = [
    (
        "valid",
        "Valid payment",
        "A signed, valid webhook is accepted into local monitoring.",
        "success",
    ),
    (
        "invalid-transaction",
        "Malformed transaction",
        "A trusted payload is rejected before it affects merchant metrics.",
        "warning",
    ),
    (
        "invalid-amount",
        "Invalid amount",
        "A trusted validation error creates an operations alert.",
        "warning",
    ),
    (
        "merchant-mismatch",
        "Merchant mismatch",
        "The sandbox account does not match the event owner.",
        "warning",
    ),
    (
        "invalid-payment-country",
        "Invalid payment method",
        "The source method is not valid for its transaction country.",
        "warning",
    ),
    (
        "unsupported-schema",
        "Unsupported schema",
        "A trusted webhook uses an unsupported contract version.",
        "warning",
    ),
    (
        "invalid-signature",
        "Invalid signature",
        "Untrusted traffic is rejected without creating operations noise.",
        "security",
    ),
]


def get_json(path: str) -> Any | None:
    try:
        response = requests.get(f"{API_BASE_URL}{path}", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def post_json(path: str) -> tuple[int, dict[str, Any] | None]:
    try:
        response = requests.post(f"{API_BASE_URL}{path}", timeout=8)
        body = response.json() if response.content else {}
        return response.status_code, body if isinstance(body, dict) else None
    except (requests.RequestException, ValueError):
        return 0, None


def render_outcome() -> None:
    outcome = st.session_state.get("yuno_outcome")
    if not outcome:
        st.info("Choose a sandbox scenario to create observable API traffic.")
        return

    title = outcome["title"]
    status = outcome["status"]
    body = outcome.get("body") or {}
    if status == 0:
        st.error("The Yuno API Manager could not reach FastAPI. Start the local API.")
    elif outcome["scenario"] == "invalid-signature":
        st.error(f"Security check completed — {title}")
        st.caption("Untrusted traffic was rejected. No system alert or email was created.")
    elif body.get("accepted"):
        st.success(f"Webhook accepted — {title}")
        st.caption("The event is valid sandbox integration traffic. No notification is needed.")
    else:
        st.warning(f"Integration issue isolated — {title}")
        st.caption(
            "The signed payload was rejected before it could distort merchant monitoring. "
            "A local Yuno Operations alert and email preview were created."
        )
    if body.get("error_code"):
        st.code(f"Error code: {body['error_code']}", language=None)


st.set_page_config(
    page_title="NextWave x Yuno | API Manager",
    page_icon=":material/hub:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      [data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu,
      [data-testid="stDecoration"] { display:none; }
      .block-container { max-width:1240px; padding:1.4rem 2rem 2.2rem; }
      [data-testid="stAppViewContainer"] { background:#f5f7fb; }
      html, body, [class*="css"] { font-family:"Segoe UI",Arial,sans-serif; }
      .yuno-hero { border-radius:14px; padding:1.4rem 1.7rem; margin-bottom:1rem;
        color:#fff; background:linear-gradient(115deg,#13213b,#234c85 62%,#2b86a5);
        box-shadow:0 12px 30px rgba(25,52,91,.18); }
      .yuno-eyebrow { font-size:.72rem; letter-spacing:.12em; font-weight:700;
        text-transform:uppercase; opacity:.78; }
      .yuno-hero h1 { color:#fff; margin:.18rem 0 .35rem; font-size:2rem; }
      .yuno-hero p { margin:0; max-width:760px; color:#dcecff; }
      .yuno-panel { background:#fff; border:1px solid #e1e8f1; border-radius:12px;
        padding:1rem 1.1rem; height:100%; }
      div[data-testid="stButton"] button { min-height:74px; font-weight:650;
        text-align:left; white-space:normal; border:1px solid #ccd8e7;
        border-radius:10px; background:#fff; color:#172642; }
      div[data-testid="stButton"] button:hover { border-color:#2b86a5; color:#115a83;
        background:#f0fbff; }
      [data-testid="stMetric"] { background:#fff; border:1px solid #e1e8f1;
        padding:.55rem .8rem; border-radius:10px; }
    </style>
    <div class="yuno-hero">
      <div class="yuno-eyebrow">NextWave x Yuno · local sandbox</div>
      <h1>Yuno API Manager</h1>
      <p>Validate partner webhooks, isolate integration failures, and make API
      operations visible without confusing them with merchant payment incidents.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

api_health = get_json("/v1/sandbox/yuno-api-health")
top_left, top_right = st.columns([3, 1], vertical_alignment="center")
with top_left:
    st.caption("Sandbox account: `yuno-rappi-sandbox` · All activity is synthetic and local.")
with top_right:
    if api_health is None:
        st.error("API unavailable")
    else:
        st.success("API connected")

st.markdown("### API health")
if api_health is None:
    st.warning("Start FastAPI to load Yuno API Manager telemetry.")
else:
    status = api_health["status"]
    if status == "healthy":
        st.success("Healthy — observed sandbox requests are accepted.")
    elif status == "attention":
        st.warning("Attention — a trusted integration request needs review.")
    elif status == "degraded":
        st.error("Degraded — trusted API errors exceed the sandbox threshold.")
    else:
        st.info("Idle — load the baseline or send sandbox traffic to begin monitoring.")
    metrics = st.columns(4)
    metrics[0].metric("Requests", api_health["total_requests"])
    metrics[1].metric("Success rate", f"{api_health['success_rate']:.0%}")
    metrics[2].metric("P95 latency", f"{api_health['p95_latency_ms']:.1f} ms")
    metrics[3].metric("Trusted errors", api_health["rejected_requests"])
    if api_health["total_requests"] == 0:
        if st.button("Load healthy sandbox baseline", type="primary", width="content"):
            status_code, _ = post_json("/v1/sandbox/yuno-api-demo-seed")
            if status_code == 200:
                st.rerun()
            else:
                st.error("Could not load the sandbox baseline.")

st.markdown("### Sandbox traffic simulator")
st.caption("Each action creates local telemetry. Nothing is sent to Yuno or an email provider.")
for row_start in range(0, len(SCENARIOS), 3):
    columns = st.columns(3)
    for column, (scenario, title, description, _kind) in zip(
        columns, SCENARIOS[row_start : row_start + 3]
    ):
        with column:
            if st.button(f"{title}\n{description}", key=f"yuno_{scenario}", width="stretch"):
                status_code, body = post_json(
                    f"/v1/sandbox/yuno-api-demo-events/{scenario}"
                )
                st.session_state["yuno_outcome"] = {
                    "scenario": scenario,
                    "title": title,
                    "status": status_code,
                    "body": body,
                }
                st.rerun()

st.markdown("### Latest outcome")
render_outcome()

meaning, boundaries = st.columns(2)
with meaning:
    st.markdown("### What each result means")
    st.markdown(
        """
        <div class="yuno-panel">
          <p><b>Accepted:</b> the signed sandbox event is valid integration traffic.</p>
          <p><b>Integration issue:</b> a trusted payload is stopped before it affects
          payment monitoring, then recorded for operations review.</p>
          <p><b>Security rejection:</b> an invalid signature is rejected without alert noise.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
with boundaries:
    st.markdown("### Demo boundary")
    st.markdown(
        """
        <div class="yuno-panel">
          <p><b>Yuno API Manager</b> observes synthetic partner integration health.</p>
          <p><b>Control Tower</b> observes merchant approval-rate incidents.</p>
          <p>They are intentionally separate so malformed webhooks never contaminate
          the payment-monitoring evidence.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

alerts_tab, emails_tab, telemetry_tab, activity_tab, contract_tab = st.tabs(
    ["API alerts", "Notification emails", "Request telemetry", "Activity log", "API contract"]
)
with alerts_tab:
    alerts = get_json(f"/v1/sandbox/yuno-system-alerts/{YUNO_ACCOUNT_ID}")
    if alerts is None:
        st.info("Start the API to inspect alerts.")
    elif not alerts:
        st.info("No trusted integration failures have been recorded yet.")
    else:
        for alert in reversed(alerts):
            with st.expander(f"{alert['error_code']} · {alert['source_event_id']}"):
                st.write(alert["summary"])
                st.caption(f"Recorded at: {alert['occurred_at']}")
with emails_tab:
    emails = get_json("/v1/sandbox/yuno-email-outbox")
    if emails is None:
        st.info("Start the API to inspect email previews.")
    elif not emails:
        st.info("No sandbox operation emails have been rendered yet.")
    else:
        for email in reversed(emails):
            with st.expander(f"{email['subject']} · {email['created_at']}"):
                st.caption(f"To: {email['to']}")
                st.code(email["text_body"], language=None)
with telemetry_tab:
    api_health = get_json("/v1/sandbox/yuno-api-health")
    if api_health is None or not api_health["recent_events"]:
        st.info("No sandbox requests recorded yet.")
    else:
        for event in api_health["recent_events"]:
            st.markdown(
                f"**{event['outcome'].upper()}** · {event['latency_ms']:.1f} ms · "
                f"{event.get('error_code') or 'no_error'}"
            )
            st.caption(event["occurred_at"])
with activity_tab:
    activity = get_json("/v1/sandbox/yuno-api-log")
    if activity is None or not activity:
        st.info("No API movements recorded yet.")
    else:
        st.download_button(
            "Download audit log (JSON)",
            data=json.dumps(activity, indent=2),
            file_name="yuno-api-activity-log.json",
            mime="application/json",
            width="content",
        )
        for event in activity:
            with st.expander(f"{event['outcome'].upper()} · {event['source_event_id']}"):
                st.write(f"Account: {event.get('account_id') or 'untrusted/unknown'}")
                st.write(f"Latency: {event['latency_ms']:.1f} ms")
                st.write(f"Error: {event.get('error_code') or 'none'}")
with contract_tab:
    st.write("The interactive local contract is available at:")
    st.code(f"{API_BASE_URL}/docs", language=None)
    st.caption("This is a local sandbox. No real payment data, webhooks, or email are used.")
