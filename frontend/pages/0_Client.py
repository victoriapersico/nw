"""Merchant-scoped live dashboard for the Payment Control Tower."""

from html import escape
import os
from typing import Any, get_args

import requests
import streamlit as st

from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    COUNTRY_PAYMENT_METHODS,
    InjectionConfig,
    Merchant,
    MerchantIncidentsResponse,
    TransactionBatch,
)
from frontend.live_data import (
    COUNTRIES,
    MerchantSnapshot,
    build_merchant_snapshot,
    diagnosis_presentation,
)


API_BASE_URL = os.getenv("CONTROL_TOWER_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("BACKEND_REQUEST_TIMEOUT_SECONDS", "90"))
MERCHANTS: tuple[Merchant, ...] = get_args(Merchant)
THEMES = {
    "Rappi": {"primary": "#d94a4e", "secondary": "#8f2730"},
    "Carrefour": {"primary": "#1554a3", "secondary": "#082d64"},
    "Despegar": {"primary": "#6f32c9", "secondary": "#3e197c"},
}


def api_json(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{API_BASE_URL}{path}",
        timeout=REQUEST_TIMEOUT_SECONDS,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def reset_demo() -> None:
    api_json("POST", "/monitor/reset")
    for key in tuple(st.session_state):
        if key.startswith("live_") or key in {"last_injection", "active_injection"}:
            del st.session_state[key]


def update_trends(
    merchant: Merchant,
    batch: TransactionBatch,
    snapshot: MerchantSnapshot,
) -> dict[str, list[float]]:
    key = f"live_trends_{merchant}"
    time_key = f"live_window_{merchant}"
    previous_end = st.session_state.get(time_key)
    if previous_end is not None and batch.window_end <= previous_end:
        st.session_state.pop(key, None)
    trends = st.session_state.setdefault(key, {country: [] for country in COUNTRIES})
    if previous_end != batch.window_end:
        for country in COUNTRIES:
            trends[country].append(snapshot.countries[country].approval_rate * 100)
            trends[country] = trends[country][-12:]
    st.session_state[time_key] = batch.window_end
    return trends


def render_chart(trends: dict[str, list[float]], theme: dict[str, str]) -> None:
    colors = [theme["primary"], "#df9c2c", theme["secondary"]]
    width, height = 920, 250
    left, right, top, bottom = 48, 18, 16, 34
    chart_width = width - left - right
    chart_height = height - top - bottom

    def point(index: int, value: float, count: int) -> tuple[float, float]:
        x = left + chart_width * index / max(count - 1, 1)
        y = top + (100 - value) * chart_height / 100
        return x, y

    grid = "".join(
        f'<line x1="{left}" x2="{width-right}" y1="{point(0, tick, 2)[1]:.1f}" '
        f'y2="{point(0, tick, 2)[1]:.1f}" stroke="#e4e8ef" />'
        f'<text x="6" y="{point(0, tick, 2)[1] + 4:.1f}" fill="#687386" '
        f'font-size="11">{tick}%</text>'
        for tick in (0, 25, 50, 75, 100)
    )
    lines: list[str] = []
    legend: list[str] = []
    for color, country in zip(colors, COUNTRIES):
        values = trends[country]
        points = " ".join(
            f"{x:.1f},{y:.1f}"
            for index, value in enumerate(values)
            for x, y in [point(index, value, len(values))]
        )
        if points:
            lines.append(
                f'<polyline points="{points}" fill="none" stroke="{color}" '
                'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />'
            )
        legend.append(
            f'<span><i style="background:{color}"></i>{country} '
            f'{values[-1]:.1f}%</span>'
        )
    st.markdown(
        f"""
        <div class="approval-chart">
          <svg viewBox="0 0 {width} {height}" role="img" aria-label="Actual live approval rate by country">
            {grid}{''.join(lines)}
          </svg>
          <div class="approval-legend">{''.join(legend)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_recent_payments(snapshot: MerchantSnapshot) -> None:
    rows = "".join(
        "<tr>"
        f"<td>{escape(item.timestamp.strftime('%H:%M:%S'))}</td>"
        f"<td>{escape(item.country)}</td>"
        f"<td>{escape(item.provider)}</td>"
        f"<td>{escape(item.payment_method)}</td>"
        f"<td>US$ {item.amount:,.2f}</td>"
        f"<td><span class='payment-{item.status}'>{escape(item.status.title())}</span></td>"
        "</tr>"
        for item in snapshot.recent_transactions
    )
    st.markdown(
        "<div class='payments-table'><table><thead><tr>"
        "<th>Time (UTC)</th><th>Country</th><th>Provider</th><th>Method</th>"
        f"<th>Amount</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>",
        unsafe_allow_html=True,
    )


st.markdown(
    """
    <style>
      :root { --surface:#fff; --page:#eef2f6; --border:#dfe5ed; --text:#172033; --muted:#687386; }
      [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display:none!important; }
      [data-testid="stAppViewContainer"] { background:var(--page); }
      [data-testid="stMainBlockContainer"], .block-container { max-width:1280px; padding:14px 24px 32px; }
      [data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--border); }
      [data-testid="stSidebarNav"] { display:none!important; }
      html, body, [class*="css"] { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--text); }
      h1,h2,h3,h4 { letter-spacing:-.02em; }
      .tower-header { display:flex; justify-content:space-between; align-items:center; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:14px 16px; margin-bottom:12px; }
      .tower-title { font-size:22px; font-weight:750; }
      .tower-subtitle { color:var(--muted); font-size:12px; margin-top:3px; }
      .live-pill { color:#08775d; background:#dff7ef; border:1px solid #bcebdc; border-radius:999px; padding:4px 9px; font-size:11px; font-weight:750; }
      .kpi-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:10px 0 18px; }
      .kpi { background:#fff; border:1px solid var(--border); border-radius:8px; padding:13px 15px; }
      .kpi-label { color:var(--muted); font-size:12px; font-weight:600; }
      .kpi-value { font-size:28px; line-height:34px; font-weight:760; }
      .incident-card { background:#fff; border:1px solid #edc5ca; border-left:5px solid #c93645; border-radius:8px; padding:13px 15px; margin:8px 0; }
      .incident-head { display:flex; justify-content:space-between; gap:12px; }
      .incident-title { font-weight:750; }
      .incident-meta { color:var(--muted); font-size:12px; margin-top:4px; }
      .country-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
      .country-card { background:#fff; border:1px solid var(--border); border-radius:8px; padding:11px 13px; }
      .country-name { font-weight:700; }
      .country-facts { color:var(--muted); font-size:12px; margin-top:4px; }
      .status-ok,.status-watch,.status-critical { display:inline-block; border-radius:3px; padding:2px 6px; font-size:11px; font-weight:700; }
      .status-ok { color:#08775d; background:#dff7ef; }
      .status-watch { color:#8b5900; background:#fff0cc; }
      .status-critical { color:#b42318; background:#fee4e2; }
      .approval-chart { background:#fff; border:1px solid var(--border); border-radius:8px; padding:10px; }
      .approval-chart svg { width:100%; display:block; }
      .approval-legend { display:flex; gap:18px; color:var(--muted); font-size:12px; padding:0 38px 5px; }
      .approval-legend i { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; }
      .payments-table { overflow:auto; background:#fff; border:1px solid var(--border); border-radius:8px; }
      .payments-table table { width:100%; border-collapse:collapse; font-size:12px; }
      .payments-table th,.payments-table td { text-align:left; padding:8px 10px; border-bottom:1px solid #edf0f4; }
      .payments-table th { color:var(--muted); font-weight:650; }
      .payment-approved { color:#08775d; font-weight:700; }
      .payment-declined { color:#b42318; font-weight:700; }
      .evidence-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; }
      .evidence-item { background:#f7f9fb; border:1px solid var(--border); border-radius:6px; padding:9px; }
      .evidence-label { color:var(--muted); font-size:11px; text-transform:uppercase; }
      .evidence-value { font-weight:750; margin-top:2px; }
      @media(max-width:760px) { .kpi-grid,.country-grid { grid-template-columns:1fr; } .tower-header { align-items:flex-start; flex-direction:column; } }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown("## Control Tower")
    merchant: Merchant = st.selectbox("Monitored merchant", MERCHANTS)
    st.caption("Real five-minute simulator windows")
    if st.button("Reset demo", use_container_width=True):
        try:
            reset_demo()
            st.success("Backend reset complete.")
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Backend reset failed: {exc}")


with st.popover("Judge Lab"):
    st.markdown("#### Inject supported degradation")
    st.caption("Choose merchant + country and at most one optional slice dimension.")
    with st.form("judge_injection_form"):
        lab_merchant = st.selectbox("Merchant", MERCHANTS, index=MERCHANTS.index(merchant))
        lab_country = st.selectbox("Country", COUNTRIES, index=1)
        provider_choice = st.selectbox(
            "Provider", ("Any", "Stripe", "Adyen", "dLocal")
        )
        method_choice = st.selectbox(
            "Payment method", ("Any", *sorted(COUNTRY_PAYMENT_METHODS[lab_country]))
        )
        bank_choice = st.selectbox(
            "Issuing bank", ("Any", *sorted(COUNTRY_ISSUING_BANKS[lab_country]))
        )
        target_rate = st.slider("Target approval rate", 0, 60, 20, 5)
        inject = st.form_submit_button("Inject incident", type="primary", use_container_width=True)
    if inject:
        provider = None if provider_choice == "Any" else provider_choice
        payment_method = None if method_choice == "Any" else method_choice
        issuing_bank = None if bank_choice == "Any" else bank_choice
        config = InjectionConfig(
            merchant=lab_merchant,
            country=lab_country,
            provider=provider,
            payment_method=payment_method,
            issuing_bank=issuing_bank,
            target_approval_rate=target_rate / 100,
            duration_windows=6,
        )
        selected_filters = sum(
            value is not None
            for value in (provider, payment_method, issuing_bank)
        )
        if selected_filters > 1:
            st.error(
                "This slice is too narrow for the supported demo policy. "
                "Choose at most one provider, payment method, or issuing bank."
            )
        else:
            try:
                result = api_json(
                    "POST",
                    "/injections",
                    json={"config": config.model_dump(mode="json")},
                )
                st.session_state["last_injection"] = result["injection_id"]
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Injection failed: {exc}")
    if st.session_state.get("last_injection"):
        st.success(f"Active: {st.session_state['last_injection']}")
        st.caption("The detector receives generated transactions only.")
    if st.button("Reset backend and clear incident", use_container_width=True):
        try:
            reset_demo()
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Backend reset failed: {exc}")


@st.fragment(run_every="2s")
def render_live_dashboard() -> None:
    try:
        api_json("POST", "/monitor/tick")
        batch = TransactionBatch.model_validate(api_json("GET", "/monitor/latest-batch"))
        incident_response = MerchantIncidentsResponse.model_validate(
            api_json("GET", f"/merchants/{merchant}/incidents")
        )
    except (requests.RequestException, ValueError) as exc:
        st.error(
            "Backend unavailable or returned invalid data. Live updates are paused; "
            f"no fallback metrics are being shown. ({exc})",
            icon="🚫",
        )
        return

    incidents = incident_response.incidents
    snapshot = build_merchant_snapshot(batch, merchant, incidents)
    trends = update_trends(merchant, batch, snapshot)
    theme = THEMES[merchant]
    st.markdown(
        f"""
        <div class="tower-header">
          <div><div class="tower-title">{merchant} Payment Control Tower</div>
          <div class="tower-subtitle">Mexico · Brazil · Colombia · latest real window ends {batch.window_end.strftime('%H:%M UTC')}</div></div>
          <span class="live-pill">● LIVE BACKEND</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if incidents:
        st.markdown("### Active incidents — backend priority order")
        for position, item in enumerate(incidents, start=1):
            incident = item.incident
            st.markdown(
                f"""
                <div class="incident-card">
                  <div class="incident-head"><span class="incident-title">#{position} · {incident.severity.upper()} · {incident.country}</span>
                  <span>US$ {incident.estimated_loss:,.0f} estimated loss</span></div>
                  <div class="incident-meta">Approval {incident.expected_conversion:.1%} → {incident.actual_conversion:.1%} · {incident.affected_volume} transactions · score {incident.anomaly_score:.1f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.success("No active incident emitted by the detector in this demo state.", icon="✅")

    incident_class = " status-critical" if incidents else ""
    st.markdown(
        f"""
        <div class="kpi-grid">
          <div class="kpi"><div class="kpi-label">Approval rate · current real window</div><div class="kpi-value">{snapshot.approval_rate:.1%}</div></div>
          <div class="kpi"><div class="kpi-label">Transactions · current real window</div><div class="kpi-value">{snapshot.transaction_count:,}</div></div>
          <div class="kpi"><div class="kpi-label">Active incidents</div><div class="kpi-value{incident_class}">{len(incidents)}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Country health — measured batch")
    country_cards = []
    for country in COUNTRIES:
        metric = snapshot.countries[country]
        status_class = {
            "No active incident": "status-ok",
            "Attention": "status-watch",
            "Critical": "status-critical",
        }[metric.status]
        country_cards.append(
            f"<div class='country-card'><div class='country-name'>{country}</div>"
            f"<div class='country-facts'>{metric.approval_rate:.1%} approval · "
            f"{metric.transaction_count} transactions</div>"
            f"<div style='margin-top:7px'><span class='{status_class}'>{metric.status}</span></div></div>"
        )
    st.markdown(f"<div class='country-grid'>{''.join(country_cards)}</div>", unsafe_allow_html=True)

    st.markdown("### Approval rate by country — actual windows")
    render_chart(trends, theme)

    st.markdown("### Recent payments — current real window")
    render_recent_payments(snapshot)

    st.markdown("### Diagnosis & recommendation")
    if not incidents:
        st.info("No diagnosis is available because the detector has emitted no incident.")
    for item in incidents:
        diagnosis = item.diagnosis
        presentation = diagnosis_presentation(diagnosis.diagnosis_status)
        with st.container(border=True):
            st.markdown(f"#### {item.incident.country}")
            if diagnosis.diagnosis_status == "confirmed":
                st.success(presentation.heading, icon="✅")
                displayed_evidence = [
                    evidence
                    for evidence in diagnosis.evidence
                    if evidence.dimension in diagnosis.root_cause_dimensions
                ]
            else:
                st.warning(presentation.heading, icon="⚠️")
                displayed_evidence = diagnosis.evidence
            st.write(diagnosis.explanation)
            evidence_html = "".join(
                f"<div class='evidence-item'><div class='evidence-label'>{escape(evidence.dimension.replace('_', ' '))}</div>"
                f"<div class='evidence-value'>{escape(evidence.value)}</div>"
                f"<small>{evidence.baseline_metric:.1%} → {evidence.live_metric:.1%}</small></div>"
                for evidence in displayed_evidence
            )
            if evidence_html:
                st.markdown(f"**{presentation.evidence_heading}**")
                st.markdown(f"<div class='evidence-grid'>{evidence_html}</div>", unsafe_allow_html=True)
            st.info(diagnosis.recommended_action, icon="💡")

    st.caption(
        "Every live value above comes from POST /monitor/tick, GET /monitor/latest-batch, "
        "or GET /merchants/{merchant}/incidents. No synthetic UI fallback is active."
    )


render_live_dashboard()
