"""Merchant-scoped client dashboard for the Control Tower MVP."""

import os
import requests

from copy import deepcopy
from typing import Any

import streamlit as st

from backend.schemas import COUNTRY_ISSUING_BANKS, COUNTRY_PAYMENT_METHODS, InjectionConfig

API_BASE_URL = os.getenv(
    "CONTROL_TOWER_API_URL",
    "http://127.0.0.1:8000",
)

def fetch_merchant_incidents(
    merchant: str,
) -> list[dict[str, Any]] | None:
    """Return None only when the local API is unavailable."""

    try:
        response = requests.get(
            f"{API_BASE_URL}/merchants/{merchant}/incidents",
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["incidents"]
    except requests.RequestException:
        return None


def render_approval_chart(
    trends: dict[str, list[float]],
    country_metrics: dict[str, dict[str, Any]],
    theme: dict[str, str],
) -> None:
    """Render a dependency-free SVG chart for Windows demo environments."""

    colors = [theme["primary"], theme["accent"], theme["dark"]]
    width, height = 920, 280
    left, right, top, bottom = 52, 24, 20, 42
    chart_width = width - left - right
    chart_height = height - top - bottom
    minimum, maximum = 55.0, 100.0

    def point(index: int, value: float, count: int) -> tuple[float, float]:
        x = left + (chart_width * index / max(count - 1, 1))
        y = top + (maximum - value) * chart_height / (maximum - minimum)
        return x, y

    grid = "".join(
        f'<line x1="{left}" x2="{width - right}" y1="{point(0, tick, 2)[1]:.1f}" '
        f'y2="{point(0, tick, 2)[1]:.1f}" stroke="rgba(90,105,135,.16)" />'
        f'<text x="8" y="{point(0, tick, 2)[1] + 4:.1f}" fill="#68758c" font-size="11">{tick}%</text>'
        for tick in (60, 70, 80, 90, 100)
    )
    lines: list[str] = []
    legend: list[str] = []
    for color, (country, approvals) in zip(colors, trends.items()):
        points = " ".join(
            f"{x:.1f},{y:.1f}"
            for index, value in enumerate(approvals)
            for x, y in [point(index, value, len(approvals))]
        )
        expected = country_metrics[country]["expected"]
        expected_y = point(0, expected, 2)[1]
        lines.append(
            f'<line x1="{left}" x2="{width - right}" y1="{expected_y:.1f}" '
            f'y2="{expected_y:.1f}" stroke="{color}" stroke-opacity=".32" '
            'stroke-dasharray="5 5" />'
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />'
        )
        for index, approval in enumerate(approvals):
            x, y = point(index, approval, len(approvals))
            critical = approval - expected <= -8
            marker = "#dc2638" if critical else color
            radius = "5" if critical else "3"
            lines.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{marker}" '
                'stroke="white" stroke-width="1.5" />'
            )
        legend.append(
            f'<span><i style="background:{color}"></i>{country} '
            f'({approvals[-1]:.1f}% / expected {expected:.1f}%)</span>'
        )

    chart = f"""
    <div class="approval-chart">
        <svg viewBox="0 0 {width} {height}" role="img" aria-label="Live approval rate by country">
            {grid}{''.join(lines)}
            <text x="{width / 2 - 36:.1f}" y="{height - 10}" fill="#68758c" font-size="11">Latest windows</text>
        </svg>
        <div class="approval-legend">{''.join(legend)}</div>
    </div>
    """
    st.markdown(chart, unsafe_allow_html=True)


def render_approval_chart_legacy(*_args: Any, **_kwargs: Any) -> None:
    """Compatibility shim that avoids Streamlit's blocked pyarrow transport."""

    render_approval_chart(data["trend"], countries, theme)

# Contract-shaped mocks until the live backend is integrated. Each merchant owns
# a separate payload so switching companies can never mix their information.
MERCHANT_DATA: dict[str, dict[str, Any]] = {
    "Rappi": {
        "updated": "18 seconds ago",
        "countries": {
            "Mexico": {"approval": 91.8, "expected": 92.4, "transactions": 18420, "loss": 3240, "status": "Stable"},
            "Brazil": {"approval": 71.2, "expected": 93.1, "transactions": 26180, "loss": 48700, "status": "Critical"},
            "Colombia": {"approval": 90.6, "expected": 91.5, "transactions": 13940, "loss": 4100, "status": "Stable"},
        },
        "providers": [
            {"name": "Stripe", "approval": 92.7, "status": "Operational"},
            {"name": "Adyen", "approval": 91.9, "status": "Operational"},
            {"name": "dLocal", "approval": 62.4, "status": "Degraded"},
        ],
        "trend": {
            "Mexico": [92.0, 92.5, 92.1, 91.9, 92.2, 91.8],
            "Brazil": [93.0, 92.8, 91.4, 84.1, 76.9, 71.2],
            "Colombia": [91.2, 91.0, 91.6, 91.1, 90.9, 90.6],
        },
        "incident": {
            "severity": "Critical", "country": "Brazil",
            "title": "PIX payment approval drop",
            "root_cause": {"Country": "Brazil", "Provider": "dLocal", "Method": "PIX"},
            "diagnosis": "The degradation is concentrated in PIX transactions processed by dLocal.",
            "diagnosis_points": [
                "PIX approval is significantly below baseline.",
                "dLocal is the only degraded provider.",
                "Stripe and Adyen remain within normal ranges.",
            ],
            "recommendation": "Escalate to dLocal and temporarily route affected PIX traffic to a healthy provider.",
            "confidence": 0.94,
        },
    },
    "Carrefour": {
        "updated": "24 seconds ago",
        "countries": {
            "Mexico": {"approval": 89.7, "expected": 90.2, "transactions": 12110, "loss": 1900, "status": "Stable"},
            "Brazil": {"approval": 91.4, "expected": 91.7, "transactions": 15430, "loss": 1600, "status": "Stable"},
            "Colombia": {"approval": 88.9, "expected": 89.5, "transactions": 9780, "loss": 2100, "status": "Stable"},
        },
        "providers": [
            {"name": "Stripe", "approval": 90.8, "status": "Operational"},
            {"name": "Adyen", "approval": 89.9, "status": "Operational"},
            {"name": "dLocal", "approval": 89.5, "status": "Operational"},
        ],
        "trend": {
            "Mexico": [89.9, 90.1, 89.8, 90.0, 89.6, 89.7],
            "Brazil": [91.5, 91.8, 91.6, 91.4, 91.7, 91.4],
            "Colombia": [89.2, 89.4, 89.1, 89.0, 89.3, 88.9],
        },
        "incident": None,
    },
    "Despegar": {
        "updated": "11 seconds ago",
        "countries": {
            "Mexico": {"approval": 87.1, "expected": 89.8, "transactions": 8420, "loss": 9800, "status": "Attention"},
            "Brazil": {"approval": 90.4, "expected": 90.9, "transactions": 11260, "loss": 2700, "status": "Stable"},
            "Colombia": {"approval": 89.8, "expected": 90.1, "transactions": 7340, "loss": 1400, "status": "Stable"},
        },
        "providers": [
            {"name": "Stripe", "approval": 90.6, "status": "Operational"},
            {"name": "Adyen", "approval": 85.1, "status": "Under observation"},
            {"name": "dLocal", "approval": 89.8, "status": "Operational"},
        ],
        "trend": {
            "Mexico": [89.6, 89.4, 89.0, 88.1, 87.5, 87.1],
            "Brazil": [90.8, 90.5, 90.9, 90.6, 90.5, 90.4],
            "Colombia": [90.0, 90.2, 90.1, 89.9, 90.0, 89.8],
        },
        "incident": {
            "severity": "Medium", "country": "Mexico",
            "title": "Increased declines on Adyen",
            "root_cause": {"Country": "Mexico", "Provider": "Adyen", "Method": "CARD"},
            "diagnosis": "The degradation is concentrated in CARD payments processed by Adyen.",
            "diagnosis_points": [
                "The drop mainly affects CARD payments.",
                "Adyen accounts for most of the deterioration.",
                "Other providers remain stable.",
            ],
            "recommendation": "Monitor two additional windows and inspect Adyen decline codes.",
            "confidence": 0.78,
        },
    },
}

MERCHANT_THEMES = {
    "Rappi": {"primary": "#ff5a5f", "dark": "#8f2730", "soft": "#ffe8e5", "background": "#ffbeb8", "accent": "#ff9d82"},
    "Carrefour": {"primary": "#1554a3", "dark": "#082d64", "soft": "#e5efff", "background": "#bdd5fa", "accent": "#e52329"},
    "Despegar": {"primary": "#6f32c9", "dark": "#3e197c", "soft": "#eee4ff", "background": "#d5bbfa", "accent": "#f6c945"},
}

MERCHANT_LOGOS = {
    "Rappi": "https://upload.wikimedia.org/wikipedia/commons/0/06/Rappi_logo.svg",
    "Carrefour": "https://fr.wikipedia.org/wiki/Special:Redirect/file/Logo_Carrefour.svg",
    "Despegar": "https://upload.wikimedia.org/wikipedia/commons/d/db/Despegar.com_logo.svg",
}


st.markdown("""
<style>
    /* Hide Streamlit's development chrome: Deploy, menu and top decoration. */
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display: none !important; }
    .stApp { color:#3c4257; background:linear-gradient(135deg,#dce6f2 0%,#edf2f8 48%,#d9e5f1 100%); }
    .block-container { width:calc(100% - 2rem); max-width:1440px; margin-inline:auto; padding:.8rem 0 2rem; }
    html, body, [class*="css"] { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; font-size:14px; }
    h1, h2, h3, h4, .hero-title, .team-name { font-family:"Segoe UI Variable Display","Aptos Display","Trebuchet MS",sans-serif !important; }
    h3 { color:#172033 !important; font-size:1.18rem !important; font-weight:760 !important; letter-spacing:-.025em !important; margin-top:1.35rem !important; margin-bottom:.65rem !important; }
    h3::before { content:""; display:inline-block; width:.22rem; height:.9rem; margin-right:.5rem; border-radius:99px; background:var(--merchant-primary); vertical-align:-.04rem; }
    h4 { font-weight:760 !important; letter-spacing:-.025em !important; }
    [data-testid="stSidebarNav"] { display:none !important; }
    [data-testid="stSidebar"] { border-right:1px solid rgba(255,255,255,.35); min-width:280px; max-width:280px; }
    [data-testid="stSidebar"] > div:first-child { padding-top:0; }
    [data-testid="stSidebarContent"] { width:100%; min-height:100vh; background:transparent !important; }
    [data-testid="stSidebarUserContent"] { width:100%; min-height:100vh; padding:1.35rem 1rem 2rem !important; }
    [data-testid="stSidebar"] [data-testid="stImage"] { display:flex; justify-content:center; background:transparent; border:0; padding:.45rem 0 .8rem; margin:0; box-shadow:none; }
    [data-testid="stSidebar"] [data-testid="stImage"] img { display:block; margin:0 auto; }
    [data-testid="stPopoverBody"] { min-width:340px; border:1px solid #dfe5ec; border-radius:14px; box-shadow:0 18px 50px rgba(26,31,54,.18); }
    [data-testid="stPopover"] { position:fixed; right:0; top:42%; z-index:999999; width:auto !important; }
    [data-testid="stPopover"] > button { min-height:112px; width:38px; padding:.65rem .35rem !important; color:white !important; background:var(--merchant-primary) !important; border:0 !important; border-radius:8px 0 0 8px !important; box-shadow:0 8px 24px rgba(60,66,87,.18); writing-mode:vertical-rl; transform:rotate(180deg); font-size:.72rem; letter-spacing:.04em; }
    [data-testid="stMetric"] { background:rgba(255,255,255,.3); border:1px solid rgba(255,255,255,.5); border-radius:12px; padding:1rem 1.1rem; box-shadow:0 8px 24px rgba(30,50,80,.04); }
    [data-testid="stMetricValue"] { color: #172033; }
    [data-testid="stVegaLiteChart"] { background:transparent !important; border:0; border-radius:0; padding:0; box-shadow:none; backdrop-filter:none; }
    [data-testid="stVegaLiteChart"] .vega-embed,
    [data-testid="stVegaLiteChart"] canvas,
    [data-testid="stVegaLiteChart"] svg { background:transparent !important; }
    [data-testid="stVerticalBlockBorderWrapper"] { background:rgba(255,255,255,.3); border-color:rgba(255,255,255,.5) !important; border-radius:12px !important; box-shadow:0 8px 24px rgba(60,66,87,.04); backdrop-filter:blur(14px); }
    .product-name { color:#29324a; font-size:1.22rem; line-height:1.15; font-weight:750; letter-spacing:-.025em; margin:.35rem 0 .25rem; }
    .product-copy { color:#748096; font-size:.76rem; margin-bottom:.8rem; }
    .stripe-nav { width:calc(100% + 2rem); min-height:46vh; margin:.55rem -1rem 1rem; padding:.55rem .7rem; border-top:1px solid rgba(94,111,136,.12); border-bottom:1px solid rgba(94,111,136,.12); }
    .stripe-nav a { display:flex; width:100%; align-items:center; gap:.75rem; color:#4f5d73 !important; text-decoration:none !important; font-size:.88rem; padding:.68rem .75rem; border-radius:7px; }
    .stripe-nav a:hover { background:rgba(255,255,255,.24); color:#273247 !important; }
    .stripe-nav a.active { color:var(--merchant-dark) !important; background:rgba(255,255,255,.34); box-shadow:inset 3px 0 0 var(--merchant-primary); font-weight:700; }
    [data-testid="stSidebar"] div[data-baseweb="select"] > div { background:transparent; border:0; box-shadow:none; font-weight:700; color:#29324a; padding-left:0; }
    .nav-icon { width:1.15rem; text-align:center; color:#77839a; }
    .eyebrow { color: #65728a; font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }
    .status-ok,.status-watch,.status-critical { display:inline-block; padding:.2rem .55rem; border-radius:999px; font-size:.78rem; font-weight:700; }
    .status-ok { color:#08775d; background:#dff7ef; }
    .status-watch { color:#9b5d00; background:#fff0cc; }
    .status-critical { color:#b42318; background:#fee4e2; }
    .incident-card { background:white; border:1px solid #e4eaf2; border-left:5px solid #e5484d; border-radius:14px; padding:1.15rem 1.3rem; margin-bottom:.8rem; }
    .primary-alert { display:grid; grid-template-columns:1fr auto; gap:1rem; align-items:center; color:#8f1d2c; background:#fff5f6; border:1px solid #efb9c0; border-left:4px solid #dc3545; border-radius:3px; padding:.9rem 1rem; margin:.2rem 0 .75rem; box-shadow:0 2px 5px rgba(60,66,87,.08); }
    .alert-kicker { font-family:"Bahnschrift SemiCondensed","Arial Narrow",sans-serif; font-size:.74rem; font-weight:750; letter-spacing:.12em; }
    .alert-country { opacity:.78; font-size:.72rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; margin-top:.28rem; }
    .alert-title { font-size:1.02rem; font-weight:700; margin:.2rem 0 .28rem; }
    .alert-facts { opacity:.9; font-size:.92rem; }
    .alert-action { color:white !important; background:#dc3545; text-decoration:none !important; border-radius:3px; padding:.48rem .7rem; font-size:.75rem; font-weight:650; white-space:nowrap; }
    .healthy-alert { color:#08775d; background:rgba(232,251,244,.72); border:1px solid rgba(24,157,112,.22); border-radius:18px; padding:1rem 1.2rem; margin:.2rem 0 1rem; backdrop-filter:blur(12px); }
    .provider-stack { background:rgba(255,255,255,.3); border:1px solid rgba(255,255,255,.5); border-radius:12px; padding:.2rem .75rem; box-shadow:0 8px 24px rgba(60,66,87,.04); backdrop-filter:blur(14px); }
    .provider-row { display:flex; align-items:center; gap:.7rem; background:transparent; border-bottom:1px solid rgba(95,110,140,.15); padding:.85rem .15rem; }
    .provider-row:last-child { border-bottom:0; }
    .provider-dot { width:.58rem; height:.58rem; flex:0 0 .58rem; border-radius:50%; background:#25b879; box-shadow:0 0 0 4px rgba(37,184,121,.12); }
    .provider-dot.warn { background:#f06a47; box-shadow:0 0 0 4px rgba(240,106,71,.12); }
    .provider-meta { color:#65728a; font-size:.86rem; margin-top:.08rem; }
    .diagnosis-list { margin:.15rem 0 .35rem; padding:0; list-style:none; }
    .diagnosis-list li { position:relative; padding:.45rem 0 .45rem 1.4rem; border-bottom:1px solid rgba(100,115,145,.12); line-height:1.4; }
    .diagnosis-list li:last-child { border-bottom:0; }
    .diagnosis-list li::before { content:""; position:absolute; left:.1rem; top:.82rem; width:.48rem; height:.48rem; border-radius:2px; background:var(--merchant-primary); transform:rotate(45deg); }
    .root-cause-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.6rem; margin:.4rem 0 .75rem; }
    .cause-item { background:rgba(255,255,255,.3); border:1px solid rgba(255,255,255,.5); border-radius:12px; padding:.7rem .75rem; }
    .cause-label { color:#69758b; font-size:.68rem; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }
    .cause-value { color:#172033; font-size:1rem; font-weight:800; margin-top:.15rem; }
    .merchant-hero { color:#3c4257; background:rgba(255,255,255,.3) !important; border:1px solid rgba(255,255,255,.55); border-radius:14px; padding:.9rem 1.1rem; margin-bottom:.75rem; box-shadow:0 8px 26px rgba(60,66,87,.06); backdrop-filter:blur(16px); }
    .hero-title { font-size:1rem; line-height:1.2; font-weight:650; letter-spacing:0; margin:.35rem 0 .2rem; }
    .hero-subtitle { color:#697386; font-size:.74rem; }
    .merchant-hero.rappi-hero { color:#1a1f36; background:rgba(255,255,255,.3) !important; border-color:rgba(255,255,255,.55); }
    .rappi-hero .hero-subtitle { color:#697386; }
    .rappi-hero .live-pill { color:#c2412d; background:#fff0eb; border-color:#ffd7ca; }
    .live-pill { display:inline-block; color:var(--merchant-dark); background:var(--merchant-soft); border:1px solid rgba(100,110,135,.12); border-radius:999px; padding:.2rem .55rem; font-size:.68rem; font-weight:750; }
    .kpi-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0; margin:.4rem 0 1rem; background:rgba(255,255,255,.3); border:1px solid rgba(255,255,255,.5); border-radius:12px; box-shadow:0 8px 24px rgba(60,66,87,.04); backdrop-filter:blur(14px); }
    .kpi-card { position:relative; overflow:hidden; min-width:0; background:transparent; border:0; border-right:1px solid rgba(111,128,151,.16); border-radius:0; padding:.8rem 1rem; box-shadow:none; }
    .kpi-card::before { content:""; position:absolute; inset:0 auto 0 0; width:2px; background:var(--merchant-primary); }
    .kpi-label { color:#65728a; font-size:.82rem; font-weight:650; margin-bottom:.48rem; }
    .kpi-value { color:#152039; font-size:clamp(1.45rem,2.25vw,2.05rem); line-height:1.1; font-weight:780; letter-spacing:-.035em; white-space:nowrap; }
    .kpi-card.incident { background:linear-gradient(145deg,#d92d3a,#b91f2c) !important; border-color:#a91d28 !important; box-shadow:0 12px 30px rgba(185,31,44,.28); }
    .kpi-card.incident::before { display:none; }
    .kpi-card.incident .kpi-label,.kpi-card.incident .kpi-value { color:white !important; }
    .kpi-link { color:inherit !important; text-decoration:none !important; display:block; }
    .kpi-link .kpi-card { transition:transform .18s ease,box-shadow .18s ease; }
    .kpi-link:hover .kpi-card { transform:translateY(-3px); box-shadow:0 16px 34px rgba(185,31,44,.35); }
    .injector-shell { background:linear-gradient(145deg,rgba(255,255,255,.96),var(--merchant-soft)); border:1px solid rgba(210,220,234,.9); border-radius:20px; padding:1rem 1.2rem; margin:.5rem 0 1rem; }
    @media (max-width:900px) { .kpi-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    @media (max-width:540px) { .kpi-grid { grid-template-columns:1fr; } }
</style>
""", unsafe_allow_html=True)


with st.sidebar:
    company_logo, company_name = st.columns([1, 4], vertical_alignment="center")
    current_merchant = st.session_state.get("monitored_company", "Rappi")
    with company_logo:
        st.image(MERCHANT_LOGOS[current_merchant], use_container_width=True)
    with company_name:
        merchant = st.selectbox(
            "Monitored company",
            list(MERCHANT_DATA),
            index=list(MERCHANT_DATA).index(current_merchant),
            key="monitored_company",
            label_visibility="collapsed",
        )
    st.markdown(
        '<nav class="stripe-nav">'
        '<a class="active" href="#overview"><span class="nav-icon">⌂</span>Overview</a>'
        '<a href="#incidents"><span class="nav-icon">▤</span>Incidents</a>'
        '<a href="#monitoring"><span class="nav-icon">⌁</span>Monitoring</a>'
        '<a href="#countries"><span class="nav-icon">◎</span>Countries</a>'
        '<a href="#diagnosis"><span class="nav-icon">◇</span>Providers</a>'
        '<a href="#report"><span class="nav-icon">▣</span>Reports</a>'
        '</nav>',
        unsafe_allow_html=True,
    )

with st.popover("⚙ Judge Lab"):
        st.markdown("#### Inject test incident")
        st.caption("Configure a simulated degradation without leaving the dashboard.")
        with st.form("judge_injection_form"):
            merchant_names = list(MERCHANT_DATA)
            lab_merchant = st.selectbox("Merchant", merchant_names, index=merchant_names.index(merchant))
            lab_country = st.selectbox("Country", ["Mexico", "Brazil", "Colombia"])
            lab_provider = st.selectbox("Provider", ["Any", "Stripe", "Adyen", "dLocal"], index=2)
            lab_method = st.selectbox("Payment method", ["Any", *sorted(COUNTRY_PAYMENT_METHODS[lab_country])])
            lab_bank = st.selectbox("Issuing bank", ["Any", *sorted(COUNTRY_ISSUING_BANKS[lab_country])])
            target_rate = st.slider("Target approval rate", 0, 100, 30, 5)
            inject = st.form_submit_button("Inject incident", type="primary", use_container_width=True)

        if inject:
            config = InjectionConfig(
                merchant=lab_merchant,
                country=lab_country,
                provider=None if lab_provider == "Any" else lab_provider,
                payment_method=None if lab_method == "Any" else lab_method,
                issuing_bank=None if lab_bank == "Any" else lab_bank,
                target_approval_rate=target_rate / 100,
                duration_windows=6,
            )

            try:
                response = requests.post(
                    f"{API_BASE_URL}/injections",
                    json={"config": config.model_dump(mode="json")},
                    timeout=30,
                )
                response.raise_for_status()
                result = response.json()

                st.session_state["last_injection"] = {
                    **config.model_dump(mode="json"),
                    "injection_id": result["injection_id"],
                }
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Could not create the test injection: {exc}")

        last_injection = st.session_state.get("last_injection")
        if last_injection:
            st.success(
                f"Submitted to simulator: {last_injection['injection_id']}"
            )
            st.caption(
                "The detector only receives the generated transactions, "
                "never this configuration."
            )
            if st.button("Clear local notice", use_container_width=True):
                del st.session_state["last_injection"]
                st.rerun()


        if st.session_state.get("active_injection"):
            active = st.session_state["active_injection"]
            st.error(f"Active: {active['merchant']} / {active['country']} / {active['target_approval_rate']:.0%}")
            if st.button("Reset incident", use_container_width=True):
                del st.session_state["active_injection"]
                st.rerun()


data = deepcopy(MERCHANT_DATA[merchant])
theme = MERCHANT_THEMES[merchant]
hero_class = "merchant-hero rappi-hero" if merchant == "Rappi" else "merchant-hero"

live_incidents = fetch_merchant_incidents(merchant)

# When the API is available, it is the source of truth: no synthetic UI

if live_incidents is not None:
    data["updated"] = "just now"
    data["incident"] = None

    if live_incidents:
        primary = live_incidents[0]
        raw_incident = primary["incident"]
        diagnosis = primary["diagnosis"]
        evidence = diagnosis["evidence"]

        country_state = data["countries"][raw_incident["country"]]
        country_state["approval"] = raw_incident["actual_conversion"] * 100
        country_state["expected"] = raw_incident["expected_conversion"] * 100
        country_state["transactions"] = raw_incident["affected_volume"]
        country_state["loss"] = raw_incident["estimated_loss"]
        country_state["status"] = {
            "low": "Stable",
            "medium": "Attention",
            "high": "Critical",
            "critical": "Critical",
        }[raw_incident["severity"]]

        trend = data["trend"][raw_incident["country"]]
        trend[-2] = round(raw_incident["expected_conversion"] * 100, 1)
        trend[-1] = round(raw_incident["actual_conversion"] * 100, 1)

        dimension_labels = {
            "merchant": "Merchant",
            "country": "Country",
            "provider": "Provider",
            "payment_method": "Method",
            "issuing_bank": "Issuing bank",
            "decline_code": "Decline code",
            "intersection": "Intersection",
        }
        root_cause = {"Country": raw_incident["country"]}
        for item in evidence:
            root_cause[dimension_labels[item["dimension"]]] = item["value"]

        affected_slice = ", ".join(
            f"{dimension_labels[item['dimension']]}: {item['value']}"
            for item in evidence
        ) or "general payment traffic"

        data["incident"] = {
            "severity": raw_incident["severity"].title(),
            "country": raw_incident["country"],
            "title": f"Approval degradation — {affected_slice}",
            "root_cause": root_cause,
            "diagnosis": diagnosis["explanation"],
            "diagnosis_points": [
                (
                    f"{dimension_labels[item['dimension']]}: "
                    f"{item['value']} "
                    f"({item['baseline_metric']:.1%} → "
                    f"{item['live_metric']:.1%})"
                )
                for item in evidence
            ],
            "recommendation": diagnosis["recommended_action"],
            "confidence": diagnosis["confidence"],
        }

countries = data["countries"]
total_transactions = sum(item["transactions"] for item in countries.values())
total_loss = sum(item["loss"] for item in countries.values())
weighted_approval = (
    sum(item["approval"] * item["transactions"] for item in countries.values())
    / total_transactions
)
weighted_expected = (
    sum(item["expected"] * item["transactions"] for item in countries.values())
    / total_transactions
)

incident = data["incident"]
active_incidents = (
    len(live_incidents)
    if live_incidents is not None
    else (1 if incident else 0)
)
st.markdown(
    f"""
    <style>
        :root {{ --merchant-primary: {theme['primary']}; --merchant-dark: {theme['dark']}; --merchant-soft: {theme['soft']}; --merchant-background: {theme['background']}; --merchant-accent: {theme['accent']}; }}
        .event-name,.team-name {{ color: var(--merchant-dark); }}
        .merchant-hero {{ background:rgba(255,255,255,.3) !important; }}
        [data-testid="stAppViewContainer"] {{
            background:
                radial-gradient(circle at 88% 5%, var(--merchant-primary) -35%, transparent 38rem),
                linear-gradient(135deg,var(--merchant-background) 0%,var(--merchant-soft) 52%,var(--merchant-background) 125%);
            background-attachment:fixed;
        }}
        [data-testid="stSidebar"] {{ background:var(--merchant-background); }}
        [data-testid="stMetric"]:hover {{ border-color: var(--merchant-primary); transform: translateY(-2px); transition: .18s ease; }}
        div[data-baseweb="select"] > div:focus-within {{ border-color: var(--merchant-primary); box-shadow: 0 0 0 1px var(--merchant-primary); }}
    </style>
    <div id="overview"></div>
    <div class="{hero_class}">
        <span class="live-pill">● LIVE MONITORING</span>
        <div class="hero-title">{merchant} Payment Control Tower</div>
        <div class="hero-subtitle">Unified payment monitoring across Mexico, Brazil and Colombia — Updated {data['updated']}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div id="incidents"></div>', unsafe_allow_html=True)
if incident:
    incident_country = countries[incident["country"]]
    st.markdown(
        f"""
        <div class="primary-alert">
            <div>
                <div class="alert-kicker">🚨 ACTIVE INCIDENT</div>
                <div class="alert-country">{incident['country']}</div>
                <div class="alert-title">{incident['title']}</div>
                <div class="alert-facts">
                    Approval {incident_country['expected']:.1f}% → {incident_country['approval']:.1f}%
                    &nbsp; · &nbsp; Estimated loss US$ {incident_country['loss']:,.0f}
                    &nbsp; · &nbsp; Confidence {incident['confidence']:.0%}
                </div>
            </div>
            <a class="alert-action" href="#incident-detail">View diagnosis ↓</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="healthy-alert"><b>✓ No active incidents</b> · All monitored countries are operating within expected ranges.</div>',
        unsafe_allow_html=True,
    )

st.markdown('<div id="report"></div><div class="eyebrow">Executive summary</div>', unsafe_allow_html=True)

incident_class = " incident" if active_incidents else ""
st.markdown(
    f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Approval rate</div>
            <div class="kpi-value">{weighted_approval:.1f}%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Transactions</div>
            <div class="kpi-value">{total_transactions:,}</div>
        </div>
        <a class="kpi-link" href="#incident-detail">
            <div class="kpi-card{incident_class}">
                <div class="kpi-label">Active incidents</div>
                <div class="kpi-value">{active_incidents}</div>
            </div>
        </a>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div id="monitoring"></div>', unsafe_allow_html=True)
st.markdown("### Approval rate — live")
chart_rows = []
for country, approvals in data["trend"].items():
    expected = countries[country]["expected"]
    for index, approval in enumerate(approvals):
        drop = approval - expected
        chart_rows.append(
            {
                "window": index + 1,
                "country": country,
                "approval": approval,
                "expected": expected,
                "difference": drop,
                "status": "Critical drop" if drop <= -8 else "Normal",
            }
        )

render_approval_chart_legacy(chart_rows, {
        "background": "transparent",
        "layer": [
            {
                "mark": {"type": "line", "strokeWidth": 3.5, "strokeCap": "round"},
                "encoding": {
                    "x": {"field": "window", "type": "ordinal", "title": "Latest windows"},
                    "y": {"field": "approval", "type": "quantitative", "scale": {"domain": [55, 100]}, "title": "Approval %"},
                    "color": {
                        "field": "country", "type": "nominal", "title": "Country",
                        "scale": {"range": [theme["primary"], theme["accent"], theme["dark"]]},
                        "legend": {"symbolType": "stroke", "symbolStrokeWidth": 4},
                    },
                },
            },
            {
                "mark": {"type": "point", "size": 220, "opacity": 0},
                "encoding": {
                    "x": {"field": "window", "type": "ordinal"},
                    "y": {"field": "approval", "type": "quantitative"},
                    "tooltip": [
                        {"field": "country", "type": "nominal", "title": "Country"},
                        {"field": "window", "type": "ordinal", "title": "Window"},
                        {"field": "approval", "type": "quantitative", "title": "Approval", "format": ".1f"},
                        {"field": "expected", "type": "quantitative", "title": "Expected", "format": ".1f"},
                        {"field": "difference", "type": "quantitative", "title": "Difference (pp)", "format": "+.1f"},
                        {"field": "status", "type": "nominal", "title": "Status"},
                    ],
                },
            },
            {
                "transform": [{"filter": "datum.status === 'Critical drop'"}],
                "mark": {"type": "point", "filled": True, "size": 145, "color": "#dc2638", "stroke": "white", "strokeWidth": 2.5},
                "encoding": {
                    "x": {"field": "window", "type": "ordinal"},
                    "y": {"field": "approval", "type": "quantitative"},
                    "tooltip": [
                        {"field": "country", "type": "nominal", "title": "⚠ Affected country"},
                        {"field": "approval", "type": "quantitative", "title": "Approval", "format": ".1f"},
                        {"field": "expected", "type": "quantitative", "title": "Expected", "format": ".1f"},
                        {"field": "difference", "type": "quantitative", "title": "Drop (pp)", "format": "+.1f"},
                    ],
                },
            },
            {
                "transform": [{"filter": "datum.status === 'Critical drop'"}],
                "mark": {"type": "text", "text": "!", "dy": -15, "fontSize": 14, "fontWeight": "bold", "color": "#b91c2c"},
                "encoding": {
                    "x": {"field": "window", "type": "ordinal"},
                    "y": {"field": "approval", "type": "quantitative"},
                },
            },
        ],
        "config": {
            "view": {"stroke": None},
            "axis": {"gridColor": "rgba(90,105,135,.15)", "domain": False, "tickColor": "transparent", "labelColor": "#68758c", "titleColor": "#68758c"},
            "legend": {"labelColor": "#68758c", "titleColor": "#68758c"},
        },
        "height": 280,
}, use_container_width=True)

st.markdown('<div id="countries"></div>', unsafe_allow_html=True)
st.markdown("### Country status")
country_columns = st.columns(3)
for column, (country_name, country) in zip(country_columns, countries.items()):
    status_class = {"Stable": "status-ok", "Attention": "status-watch", "Critical": "status-critical"}[country["status"]]
    with column:
        with st.container(border=True):
            st.markdown(
                f"**{country_name}** &nbsp; <span class='{status_class}'>{country['status']}</span>",
                unsafe_allow_html=True,
            )
            st.metric("Approval rate", f"{country['approval']:.1f}%")

st.markdown('<div id="incident-detail"></div><div id="diagnosis"></div>', unsafe_allow_html=True)
st.markdown("### Root cause & recommendation")
if incident is None:
    st.success("There are no incidents to diagnose.", icon="✅")
else:
    diagnosis_column, action_column = st.columns(2)
    with diagnosis_column:
        with st.container(border=True):
            st.markdown("#### Probable root cause")
            root_cause_items = "".join(
                f"<div class='cause-item'><div class='cause-label'>{label}</div>"
                f"<div class='cause-value'>{value}</div></div>"
                for label, value in incident["root_cause"].items()
            )
            st.markdown(
                f"<div class='root-cause-grid'>{root_cause_items}</div>",
                unsafe_allow_html=True,
            )
            diagnosis_items = "".join(
                f"<li>{point}</li>" for point in incident.get("diagnosis_points", [incident["diagnosis"]])
            )
            st.markdown(
                f"<ul class='diagnosis-list'>{diagnosis_items}</ul>",
                unsafe_allow_html=True,
            )
            st.caption(f"Confidence: {incident['confidence']:.0%}")
    with action_column:
        with st.container(border=True):
            st.markdown("#### Recommended action")
            st.info(incident["recommendation"], icon="💡")

st.caption("Control Tower MVP — Simulated data for validating the demo flow")
