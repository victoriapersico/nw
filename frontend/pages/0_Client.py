"""Merchant-scoped client dashboard for the Control Tower MVP."""

import os
import requests

from copy import deepcopy
from typing import Any

import streamlit as st

from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    COUNTRY_PAYMENT_METHODS,
    InjectionConfig,
)

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
            timeout=1.5,
        )
        response.raise_for_status()
        return response.json()["incidents"]
    except requests.RequestException:
        return None


def advance_and_fetch_monitoring(merchant: str) -> dict[str, Any] | None:
    """Advance one real simulator window, then read its merchant-scoped metrics."""

    try:
        tick = requests.post(f"{API_BASE_URL}/monitor/tick", timeout=5)
        tick.raise_for_status()
        response = requests.get(
            f"{API_BASE_URL}/merchants/{merchant}/monitoring",
            timeout=2,
        )
        response.raise_for_status()
        return response.json()
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

    chart = f"""
    <div class="approval-chart">
        <svg viewBox="0 0 {width} {height}" role="img" aria-label="Live approval rate by country">
            {grid}{''.join(lines)}
            <text x="{width / 2 - 36:.1f}" y="{height - 10}" fill="#68758c" font-size="11">Latest windows</text>
        </svg>
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
            "Mexico": {
                "approval": 91.8,
                "expected": 92.4,
                "transactions": 18420,
                "loss": 3240,
                "status": "Stable",
            },
            "Brazil": {
                "approval": 71.2,
                "expected": 93.1,
                "transactions": 26180,
                "loss": 48700,
                "status": "Critical",
            },
            "Colombia": {
                "approval": 90.6,
                "expected": 91.5,
                "transactions": 13940,
                "loss": 4100,
                "status": "Stable",
            },
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
            "severity": "Critical",
            "country": "Brazil",
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
            "Mexico": {
                "approval": 89.7,
                "expected": 90.2,
                "transactions": 12110,
                "loss": 1900,
                "status": "Stable",
            },
            "Brazil": {
                "approval": 91.4,
                "expected": 91.7,
                "transactions": 15430,
                "loss": 1600,
                "status": "Stable",
            },
            "Colombia": {
                "approval": 88.9,
                "expected": 89.5,
                "transactions": 9780,
                "loss": 2100,
                "status": "Stable",
            },
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
            "Mexico": {
                "approval": 87.1,
                "expected": 89.8,
                "transactions": 8420,
                "loss": 9800,
                "status": "Attention",
            },
            "Brazil": {
                "approval": 90.4,
                "expected": 90.9,
                "transactions": 11260,
                "loss": 2700,
                "status": "Stable",
            },
            "Colombia": {
                "approval": 89.8,
                "expected": 90.1,
                "transactions": 7340,
                "loss": 1400,
                "status": "Stable",
            },
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
            "severity": "Medium",
            "country": "Mexico",
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
    "Rappi": {
        "primary": "#ff5a5f",
        "dark": "#8f2730",
        "soft": "#ffe8e5",
        "background": "#ffbeb8",
        "accent": "#ff9d82",
    },
    "Carrefour": {
        "primary": "#1554a3",
        "dark": "#082d64",
        "soft": "#e5efff",
        "background": "#bdd5fa",
        "accent": "#e52329",
    },
    "Despegar": {
        "primary": "#6f32c9",
        "dark": "#3e197c",
        "soft": "#eee4ff",
        "background": "#d5bbfa",
        "accent": "#f6c945",
    },
}

MERCHANT_LOGOS = {
    "Rappi": "https://upload.wikimedia.org/wikipedia/commons/0/06/Rappi_logo.svg",
    "Carrefour": "https://fr.wikipedia.org/wiki/Special:Redirect/file/Logo_Carrefour.svg",
    "Despegar": "https://upload.wikimedia.org/wikipedia/commons/d/db/Despegar.com_logo.svg",
}

st.markdown(
    """
<style>
    :root {
        --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px; --space-5:20px; --space-6:24px; --space-8:32px;
        --surface:#ffffff; --surface-muted:#fafbfc; --page:#f6f7f9; --border:#e3e7ee;
        --text:#172033; --muted:#687386; --danger:#c93645; --danger-soft:#fff3f4;
        --radius-card:4px; --radius-control:3px; --shadow:0 1px 3px rgba(23,32,51,.035);
    }
    /* Hide Streamlit's development chrome: Deploy, menu and top decoration. */
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display: none !important; }
    .stApp { color:var(--text); background:var(--page); }
    [data-testid="stMain"] { background:#eef2f6; }
    [data-testid="stMainBlockContainer"],
    .block-container {
        width:min(100%,1280px); max-width:1280px; margin-left:auto !important; margin-right:auto !important;
        padding:var(--space-2) var(--space-5) var(--space-4);
        background:transparent !important; border:0 !important; border-radius:0 !important; box-shadow:none !important;
        transition:width .2s ease,margin .2s ease;
    }
    html, body, [class*="css"] { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; font-size:14px; }
    h1, h2, h3, h4, .hero-title, .team-name { font-family:"Segoe UI Variable Display","Aptos Display","Trebuchet MS",sans-serif !important; }
    [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap:var(--space-1); }
    h3 { color:var(--text) !important; font-size:15px !important; line-height:20px !important; font-weight:650 !important; letter-spacing:-.01em !important; margin:var(--space-2) 0 var(--space-1) !important; }
    h3::before { content:""; display:inline-block; width:3px; height:16px; margin-right:var(--space-2); border-radius:2px; background:var(--danger); vertical-align:-2px; }
    h4 { font-weight:760 !important; letter-spacing:-.025em !important; }
    [data-testid="stSidebarNav"] { display:none !important; }
    [data-testid="stSidebar"] { border-right:1px solid var(--border); height:100dvh; overflow:hidden !important; box-shadow:none; }
    [data-testid="stSidebar"][aria-expanded="true"] { min-width:152px; max-width:152px; }
    [data-testid="stAppViewContainer"]:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMain"] {
        width:100% !important;
        margin-left:0 !important;
    }
    [data-testid="stAppViewContainer"]:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMainBlockContainer"] {
        margin-left:auto !important;
        margin-right:auto !important;
    }
    [data-testid="stSidebar"] > div:first-child { padding-top:0; }
    [data-testid="stSidebarContent"] { width:100%; height:100dvh; overflow:hidden !important; background:transparent !important; }
    [data-testid="stSidebarUserContent"] { width:100%; height:100%; overflow:hidden !important; padding:var(--space-2) var(--space-2) !important; }
    [data-testid="stSidebar"] [data-testid="stImage"] { display:flex; justify-content:center; background:transparent; border:0; padding:0; margin:0; box-shadow:none; }
    [data-testid="stSidebar"] [data-testid="stImage"] img { display:block; margin:0 auto; }
    [data-testid="stPopoverBody"] { min-width:340px; border:1px solid var(--border); border-radius:var(--radius-card); box-shadow:0 16px 40px rgba(26,31,54,.16); }
    [data-testid="stPopover"] { position:fixed; right:0; top:42%; z-index:999999; width:auto !important; }
    [data-testid="stPopover"] > button { min-height:112px; width:38px; padding:.65rem .35rem !important; color:white !important; background:var(--merchant-primary) !important; border:0 !important; border-radius:8px 0 0 8px !important; box-shadow:0 8px 24px rgba(60,66,87,.18); writing-mode:vertical-rl; transform:rotate(180deg); font-size:.72rem; letter-spacing:.04em; }
    [data-testid="stMetric"] { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:10px var(--space-3); box-shadow:none; }
    [data-testid="stMetricValue"] { color:#172033; font-size:24px; line-height:28px; }
    [data-testid="stVegaLiteChart"] { background:transparent !important; border:0; border-radius:0; padding:var(--space-1) var(--space-6) 0 0; margin-bottom:0 !important; box-shadow:none; }
    [data-testid="stVegaLiteChart"] .vega-embed,
    [data-testid="stVegaLiteChart"] canvas,
    [data-testid="stVegaLiteChart"] svg { background:transparent !important; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        background:transparent !important;
        background-color:transparent !important;
        box-shadow:none !important;
        border:none !important;
        border-radius:0 !important;
    }
    [data-testid="stColumn"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stForm"] [data-testid="stVerticalBlockBorderWrapper"] {
        background:var(--surface) !important;
        background-color:var(--surface) !important;
        border:1px solid var(--border) !important;
        border-radius:var(--radius-card) !important;
        box-shadow:none !important;
    }
    [data-testid="stColumn"] [data-testid="stVerticalBlock"] { gap:var(--space-1); }
    .product-name { color:#29324a; font-size:1.22rem; line-height:1.15; font-weight:750; letter-spacing:-.025em; margin:.35rem 0 .25rem; }
    .product-copy { color:#748096; font-size:.76rem; margin-bottom:.8rem; }
    [data-testid="stSidebar"] div[data-baseweb="select"] > div { background:transparent; border:0; box-shadow:none; font-weight:700; color:#29324a; padding-left:0; }
    .eyebrow { color:var(--muted); font-size:11px; line-height:16px; font-weight:650; text-transform:uppercase; letter-spacing:.08em; margin-top:0; }
    .status-ok,.status-watch,.status-critical { display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; font-weight:700; }
    .status-ok { color:#08775d; background:#dff7ef; }
    .status-watch { color:#9b5d00; background:#fff0cc; }
    .status-critical { color:#b42318; background:#fee4e2; }
    .incident-card { background:white; border:1px solid #e4eaf2; border-left:5px solid #e5484d; border-radius:14px; padding:1.15rem 1.3rem; margin-bottom:.8rem; }
    .primary-alert { position:static; display:grid; grid-template-columns:minmax(260px,.8fr) minmax(0,1.2fr); min-height:88px; gap:var(--space-4); align-items:center; color:#852431; background:var(--danger-soft); border:1px solid #f0cbd0; border-left:3px solid var(--danger); border-radius:var(--radius-card); padding:10px var(--space-3); margin:0 0 18px; box-shadow:none; }
    .alert-kicker { font-family:"Bahnschrift SemiCondensed","Arial Narrow",sans-serif; font-size:.74rem; font-weight:750; letter-spacing:.12em; }
    .alert-country { opacity:.8; font-size:11px; line-height:15px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; margin-top:2px; }
    .alert-title { font-size:15px; line-height:19px; font-weight:700; margin:1px 0 0; }
    .alert-side { display:flex; align-items:center; justify-content:flex-end; gap:var(--space-3); min-width:0; }
    .alert-facts { opacity:.9; font-size:12px; line-height:18px; text-align:right; white-space:nowrap; }
    .alert-action { color:white !important; background:var(--danger); text-decoration:none !important; border-radius:var(--radius-control); padding:8px var(--space-3); font-size:12px; font-weight:650; white-space:nowrap; }
    .healthy-alert { position:static; color:#08775d; background:rgba(232,251,244,.72); border:1px solid rgba(24,157,112,.22); border-radius:18px; padding:1rem 1.2rem; margin:0 0 18px; backdrop-filter:blur(12px); }
    .provider-stack { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:var(--space-1) var(--space-3); box-shadow:none; }
    .provider-row { display:flex; align-items:center; gap:.7rem; background:transparent; border-bottom:1px solid rgba(95,110,140,.15); padding:.85rem .15rem; }
    .provider-row:last-child { border-bottom:0; }
    .provider-dot { width:.58rem; height:.58rem; flex:0 0 .58rem; border-radius:50%; background:#25b879; box-shadow:0 0 0 4px rgba(37,184,121,.12); }
    .provider-dot.warn { background:#f06a47; box-shadow:0 0 0 4px rgba(240,106,71,.12); }
    .provider-meta { color:#65728a; font-size:.86rem; margin-top:.08rem; }
    .root-cause-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-1); margin:var(--space-1) 0; }
    .cause-item { background:var(--surface-muted); border:1px solid var(--border); border-radius:var(--radius-control); padding:var(--space-2); }
    .cause-label { color:#69758b; font-size:.68rem; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }
    .cause-value { color:#172033; font-size:1rem; font-weight:800; margin-top:.15rem; }
    .merchant-hero { position:static; color:var(--text); background:var(--surface) !important; border:1px solid var(--border); border-radius:var(--radius-card); padding:8px var(--space-3); margin-bottom:18px; box-shadow:none; }
    .hero-row { display:flex; align-items:center; gap:var(--space-2); min-width:0; }
    .hero-title { font-size:20px; line-height:24px; font-weight:700; letter-spacing:-.02em; margin:0; }
    .hero-subtitle { color:var(--muted); font-size:12px; line-height:16px; margin-top:var(--space-1); }
    .merchant-hero.rappi-hero { color:var(--text); background:var(--surface) !important; border:1px solid var(--border); }
    .rappi-hero .hero-subtitle { color:#697386; }
    .rappi-hero .live-pill { color:#c2412d; background:#fff0eb; border-color:#ffd7ca; }
    .live-pill { display:inline-block; color:#a92d39; background:#fcebed; border:1px solid #f3cdd2; border-radius:999px; padding:var(--space-1) var(--space-2); font-size:11px; line-height:16px; font-weight:700; }
    .live-pill::first-letter { animation:live-pulse 1.4s ease-in-out infinite; }
    .live-note { color:var(--muted); font-size:12px; font-weight:500; margin-left:var(--space-2); text-transform:none; letter-spacing:0; }
    @keyframes live-pulse { 0%,100% { opacity:1; } 50% { opacity:.35; } }
    .executive-summary { position:static; display:block; clear:both; margin:0; padding:0; }
    .executive-summary .section-header { position:static; display:flex; align-items:baseline; gap:var(--space-2); margin:0 0 8px; }
    .executive-summary .section-header .eyebrow { margin:0; }
    .executive-summary .section-header .live-note { margin-left:0; }
    .kpi-row { position:static; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-2); margin:0; padding:0; background:transparent; border:0; box-shadow:none; }
    .kpi-card { position:relative; overflow:hidden; min-height:64px; min-width:0; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); padding:8px var(--space-3); box-shadow:none; }
    .kpi-card::before { display:none; }
    .kpi-label { color:var(--muted); font-size:12px; line-height:16px; font-weight:600; margin-bottom:var(--space-1); }
    .kpi-value { color:var(--text); font-size:26px; line-height:28px; font-weight:750; letter-spacing:-.03em; white-space:nowrap; }
    .kpi-card.incident { background:var(--surface) !important; border-color:#efc8cd !important; box-shadow:none; }
    .kpi-card.incident::after { content:""; position:absolute; top:var(--space-4); right:var(--space-4); width:8px; height:8px; border-radius:50%; background:var(--danger); }
    .kpi-card.incident .kpi-label { color:var(--muted) !important; }
    .kpi-card.incident .kpi-value { color:var(--danger) !important; }
    .kpi-link { color:inherit !important; text-decoration:none !important; display:block; }
    .kpi-link .kpi-card { transition:transform .18s ease,box-shadow .18s ease; }
    .kpi-link:hover .kpi-card { border-color:#dcaeb4 !important; box-shadow:var(--shadow); }
    .st-key-chart_section { position:static; display:block; clear:both; margin:0; padding:0; }
    .st-key-chart_section > [data-testid="stVerticalBlock"] { gap:6px; }
    .st-key-chart_section h3 { margin:0 !important; }
    .chart-top-spacer { height:20px; }
    .approval-chart { margin-bottom:-4px; }
    .approval-chart svg { display:block; }
    .country-row { display:flex; align-items:center; flex-wrap:wrap; gap:0; min-height:38px; margin:0 0 var(--space-2); padding:7px 10px; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-card); }
    .country-anchor { height:0; margin-top:0; }
    .country-entry { display:flex; align-items:center; gap:6px; white-space:nowrap; font-size:13px; }
    .country-entry + .country-entry::before { content:"|"; margin:0 12px; color:#a5adba; }
    .country-name { font-weight:700; }
    .country-rate { color:var(--text); font-variant-numeric:tabular-nums; }
    .country-separator { color:#a5adba; }
    .injector-shell { background:linear-gradient(145deg,rgba(255,255,255,.96),var(--merchant-soft)); border:1px solid rgba(210,220,234,.9); border-radius:20px; padding:1rem 1.2rem; margin:.5rem 0 1rem; }
    @media (max-width:900px) { .block-container { padding-inline:var(--space-6); } .kpi-row { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    @media (max-width:900px) { .primary-alert { grid-template-columns:1fr; } .alert-side { justify-content:space-between; } .alert-facts { text-align:left; white-space:normal; } }
    @media (max-width:640px) { .block-container { padding-inline:var(--space-4); } .kpi-row { grid-template-columns:1fr; } .alert-side { align-items:flex-start; flex-direction:column; } }
</style>
""",
    unsafe_allow_html=True,
)

if "live_playback" not in st.session_state:
    st.session_state["live_playback"] = True

if "monitored_company" not in st.session_state:
    st.session_state["monitored_company"] = "Rappi"
current_merchant = st.session_state["monitored_company"]

st.markdown(
    """
    <style>
      .st-key-demo_toolbar {
        background:linear-gradient(105deg,#17233a,#203d68 58%,#19617a) !important;
        border:1px solid rgba(255,255,255,.17) !important;
        border-radius:14px !important;
        padding:10px 14px 12px !important;
        margin:2px 0 14px !important;
        box-shadow:0 10px 26px rgba(18,36,65,.15) !important;
      }
      .st-key-demo_toolbar [data-testid="stSelectbox"] label {
        color:#b9cce7 !important; font-size:10px !important; font-weight:750 !important;
        letter-spacing:.08em !important; text-transform:uppercase !important;
      }
      .st-key-demo_toolbar div[data-baseweb="select"] > div {
        min-height:34px !important; background:rgba(255,255,255,.11) !important;
        border:1px solid rgba(255,255,255,.23) !important; border-radius:8px !important;
        color:#fff !important;
      }
      .st-key-demo_toolbar div[data-baseweb="select"] * { color:#fff !important; }
      .st-key-demo_toolbar .stButton button {
        min-height:36px !important; border-radius:8px !important; border:0 !important;
        background:#fff !important; color:#183357 !important; font-weight:750 !important;
      }
      .toolbar-kicker { color:#a9c8e8; font-size:10px; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }
      .toolbar-title { color:#fff; font-size:16px; font-weight:760; letter-spacing:-.02em; margin-top:1px; }
      .toolbar-copy { color:#d7e6f7; font-size:12px; line-height:17px; margin-top:2px; }
      .toolbar-live { display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:5px 9px; font-size:11px; font-weight:750; }
      .toolbar-live.on { color:#b8f7d5; background:rgba(29,171,108,.18); border:1px solid rgba(133,239,184,.28); }
      .toolbar-live.off { color:#ffe0aa; background:rgba(231,157,44,.16); border:1px solid rgba(255,210,130,.25); }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.container(key="demo_toolbar"):
    toolbar_logo, toolbar_brand, toolbar_merchant, toolbar_status, toolbar_action = st.columns(
        [0.45, 1.95, 1.5, 2.5, 1.4], vertical_alignment="center"
    )
    with toolbar_logo:
        st.image(MERCHANT_LOGOS[current_merchant], width=40)
    with toolbar_brand:
        st.markdown(
            "<div class='toolbar-kicker'>NextWave · payment operations</div>"
            "<div class='toolbar-title'>Control Tower</div>",
            unsafe_allow_html=True,
        )
    with toolbar_merchant:
        merchant = st.selectbox(
            "Merchant",
            list(MERCHANT_DATA),
            key="monitored_company",
        )
    with toolbar_status:
        is_live = st.session_state["live_playback"]
        live_class = "on" if is_live else "off"
        live_label = "● LIVE SIMULATOR" if is_live else "Ⅱ SIMULATOR PAUSED"
        st.markdown(
            f"<span class='toolbar-live {live_class}'>{live_label}</span>"
            "<div class='toolbar-copy'>One real simulated payment window every 5 seconds.</div>",
            unsafe_allow_html=True,
        )
    with toolbar_action:
        action_label = "Pause simulator" if st.session_state["live_playback"] else "Start simulator"
        if st.button(
            action_label,
            key="demo_live_action",
            use_container_width=True,
        ):
            st.session_state["live_playback"] = not st.session_state["live_playback"]
            st.rerun()


live_playback = bool(st.session_state["live_playback"])

with st.popover("Judge Lab"):
    st.markdown("#### Inject test incident")
    st.caption("Configure a simulated degradation without leaving the dashboard.")
    with st.form("judge_injection_form"):
        merchant_names = list(MERCHANT_DATA)
        lab_merchant = st.selectbox(
            "Merchant", merchant_names, index=merchant_names.index(merchant)
        )
        lab_country = st.selectbox("Country", ["Mexico", "Brazil", "Colombia"])
        lab_provider = st.selectbox(
            "Provider", ["Any", "Stripe", "Adyen", "dLocal"], index=2
        )
        lab_method = st.selectbox(
            "Payment method", ["Any", *sorted(COUNTRY_PAYMENT_METHODS[lab_country])]
        )
        lab_bank = st.selectbox(
            "Issuing bank", ["Any", *sorted(COUNTRY_ISSUING_BANKS[lab_country])]
        )
        target_rate = st.slider("Target approval rate", 0, 100, 30, 5)
        inject = st.form_submit_button(
            "Inject incident", type="primary", use_container_width=True
        )

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
        st.success(f"Submitted to simulator: {last_injection['injection_id']}")
        st.caption(
            "The detector only receives the generated transactions, "
            "never this configuration."
        )
        if st.button("Clear local notice", use_container_width=True):
            del st.session_state["last_injection"]
            st.rerun()

    if st.session_state.get("active_injection"):
        active = st.session_state["active_injection"]
        st.error(
            f"Active: {active['merchant']} / {active['country']} / {active['target_approval_rate']:.0%}"
        )
        if st.button("Reset incident", use_container_width=True):
            del st.session_state["active_injection"]
            st.rerun()


data = deepcopy(MERCHANT_DATA[merchant])
theme = MERCHANT_THEMES[merchant]
hero_class = "merchant-hero rappi-hero" if merchant == "Rappi" else "merchant-hero"

live_incidents = fetch_merchant_incidents(merchant) if live_playback else None

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
        diagnosis_confirmed = diagnosis["diagnosis_status"] == "confirmed"
        displayed_evidence = (
            [
                item
                for item in evidence
                if item["dimension"] in diagnosis["root_cause_dimensions"]
            ]
            if diagnosis_confirmed
            else evidence
        )
        grouped_evidence: dict[str, list[str]] = {}
        for item in displayed_evidence:
            label = dimension_labels[item["dimension"]]
            values = grouped_evidence.setdefault(label, [])
            if item["value"] not in values:
                values.append(item["value"])
        root_cause = {"Country": raw_incident["country"]}
        root_cause.update(
            {label: "; ".join(values) for label, values in grouped_evidence.items()}
        )

        affected_slice = (
            ", ".join(
                f"{dimension_labels[item['dimension']]}: {item['value']}"
                for item in displayed_evidence
            )
            or "general payment traffic"
        )
        incident_title = (
            f"Approval degradation — {affected_slice}"
            if diagnosis_confirmed
            else f"Approval degradation under investigation — {raw_incident['country']}"
        )

        data["incident"] = {
            "severity": raw_incident["severity"].title(),
            "country": raw_incident["country"],
            "title": incident_title,
            "root_cause": root_cause,
            "diagnosis": diagnosis["explanation"],
            "executive_summary": diagnosis.get("executive_summary"),
            "evidence_citations": diagnosis.get("evidence_citations", []),
            "evidence_citation_labels": {
                f"evidence-{index}": (
                    f"{dimension_labels[item['dimension']]}: {item['value']} "
                    f"({item['baseline_metric']:.1%} → {item['live_metric']:.1%})"
                )
                for index, item in enumerate(evidence, start=1)
            },
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
            "diagnosis_status": diagnosis["diagnosis_status"],
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
    len(live_incidents) if live_incidents is not None else (1 if incident else 0)
)
st.markdown(
    f"""
    <style>
        :root {{ --merchant-primary: {theme['primary']}; --merchant-dark: {theme['dark']}; --merchant-soft: {theme['soft']}; --merchant-background: {theme['background']}; --merchant-accent: {theme['accent']}; }}
        .event-name,.team-name {{ color: var(--merchant-dark); }}
        .merchant-hero {{ background:var(--surface) !important; }}
        [data-testid="stAppViewContainer"] {{ background:#eef2f6; }}
        [data-testid="stSidebar"] {{ background:var(--surface); }}
        [data-testid="stMetric"]:hover {{ border-color:var(--border); }}
        div[data-baseweb="select"] > div:focus-within {{ border-color: var(--merchant-primary); box-shadow: 0 0 0 1px var(--merchant-primary); }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.fragment(run_every="2s")
def render_live_header() -> None:
    tick = st.session_state.get("header_live_tick", 0) + 1
    st.session_state["header_live_tick"] = tick
    seconds_ago = (tick * 2) % 6
    st.markdown(
        f"""
        <div id="overview"></div>
        <div class="{hero_class}">
            <div class="hero-row">
                <span class="live-pill">● LIVE MONITORING</span>
                <div class="hero-title">{merchant} Payment Control Tower</div>
            </div>
            <div class="hero-subtitle">Unified payment monitoring across Mexico, Brazil and Colombia — Updated {seconds_ago} seconds ago</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


render_live_header()

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
            </div>
            <div class="alert-side">
                <div class="alert-facts">
                    Approval {incident_country['expected']:.1f}% → {incident_country['approval']:.1f}%
                    &nbsp; · &nbsp; Estimated loss US$ {incident_country['loss']:,.0f}
                    &nbsp; · &nbsp; Confidence {incident['confidence']:.0%}
                </div>
                <a class="alert-action" href="#incident-detail">View diagnosis ↓</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="healthy-alert"><b>✓ No active incidents</b> · All monitored countries are operating within expected ranges.</div>',
        unsafe_allow_html=True,
    )


@st.fragment(run_every="5s")
def render_live_summary() -> None:
    snapshot = st.session_state.get("monitoring_snapshot")
    if live_playback:
        snapshot = advance_and_fetch_monitoring(merchant)
        if snapshot is not None:
            st.session_state["monitoring_snapshot"] = snapshot

    if snapshot is None:
        st.warning("Waiting for the live Control Tower API. Start FastAPI to begin monitoring.")
        return

    active = fetch_merchant_incidents(merchant)
    incident_count = len(active) if active is not None else 0
    live_approval = snapshot["actual_approval_rate"] * 100
    live_transactions = snapshot["attempted_transactions"]
    incident_class = " incident" if incident_count else ""

    st.markdown(
        f"""
        <div id="report"></div>
        <section class="executive-summary">
            <div class="section-header">
                <div class="eyebrow">Live operations overview</div>
                <span class="live-note">Real simulator · updates every 5 seconds</span>
            </div>
            <div class="kpi-row">
                <div class="kpi-card">
                    <div class="kpi-label">Approval rate · live</div>
                    <div class="kpi-value">{live_approval:.1f}%</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Transactions · live</div>
                    <div class="kpi-value">{live_transactions:,}</div>
                </div>
                <a class="kpi-link" href="#incident-detail">
                    <div class="kpi-card{incident_class}">
                        <div class="kpi-label">Active incidents</div>
                        <div class="kpi-value">{incident_count}</div>
                    </div>
                </a>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


render_live_summary()


@st.fragment(run_every="5s")
def render_live_chart() -> None:
    snapshot = st.session_state.get("monitoring_snapshot")
    if snapshot is None:
        st.info("Live chart will appear after the first simulator window.")
        return

    live_trends: dict[str, list[float]] = {}
    live_countries: dict[str, dict[str, Any]] = {}
    for country in snapshot["countries"]:
        country_name = country["country"]
        history = [rate * 100 for rate in country["approval_history"]]
        live_trends[country_name] = history or [country["actual_approval_rate"] * 100]
        live_countries[country_name] = {
            "expected": country["expected_approval_rate"] * 100,
        }
    render_approval_chart(live_trends, live_countries, theme)


if False:  # Kept as a Vega reference; pyarrow is blocked by the Windows policy.
    chart_rows = []
    for country, approvals in live_trends.items():
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

    st.vega_lite_chart(
        chart_rows,
        {
            "background": "transparent",
            "layer": [
                {
                    "mark": {"type": "line", "strokeWidth": 2.5, "strokeCap": "round"},
                    "encoding": {
                        "x": {
                            "field": "window",
                            "type": "ordinal",
                            "title": "Latest windows",
                        },
                        "y": {
                            "field": "approval",
                            "type": "quantitative",
                            "scale": {"domain": [55, 100]},
                            "title": "Approval %",
                        },
                        "color": {
                            "field": "country",
                            "type": "nominal",
                            "title": "Country",
                            "scale": {
                                "range": [
                                    theme["primary"],
                                    theme["accent"],
                                    theme["dark"],
                                ]
                            },
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
                            {
                                "field": "approval",
                                "type": "quantitative",
                                "title": "Approval",
                                "format": ".1f",
                            },
                            {
                                "field": "expected",
                                "type": "quantitative",
                                "title": "Expected",
                                "format": ".1f",
                            },
                            {
                                "field": "difference",
                                "type": "quantitative",
                                "title": "Difference (pp)",
                                "format": "+.1f",
                            },
                            {"field": "status", "type": "nominal", "title": "Status"},
                        ],
                    },
                },
                {
                    "transform": [{"filter": "datum.status === 'Critical drop'"}],
                    "mark": {
                        "type": "point",
                        "filled": True,
                        "size": 90,
                        "color": "#dc2638",
                        "stroke": "white",
                        "strokeWidth": 2,
                    },
                    "encoding": {
                        "x": {"field": "window", "type": "ordinal"},
                        "y": {"field": "approval", "type": "quantitative"},
                        "tooltip": [
                            {
                                "field": "country",
                                "type": "nominal",
                                "title": "⚠ Affected country",
                            },
                            {
                                "field": "approval",
                                "type": "quantitative",
                                "title": "Approval",
                                "format": ".1f",
                            },
                            {
                                "field": "expected",
                                "type": "quantitative",
                                "title": "Expected",
                                "format": ".1f",
                            },
                            {
                                "field": "difference",
                                "type": "quantitative",
                                "title": "Drop (pp)",
                                "format": "+.1f",
                            },
                        ],
                    },
                },
                {
                    "transform": [{"filter": "datum.status === 'Critical drop'"}],
                    "mark": {
                        "type": "text",
                        "text": "!",
                        "dy": -15,
                        "fontSize": 14,
                        "fontWeight": "bold",
                        "color": "#b91c2c",
                    },
                    "encoding": {
                        "x": {"field": "window", "type": "ordinal"},
                        "y": {"field": "approval", "type": "quantitative"},
                    },
                },
            ],
            "config": {
                "view": {"stroke": None},
                "axis": {
                    "gridColor": "rgba(90,105,135,.15)",
                    "domain": False,
                    "tickColor": "transparent",
                    "labelColor": "#68758c",
                    "titleColor": "#68758c",
                    "titlePadding": 4,
                },
                "legend": {"labelColor": "#68758c", "titleColor": "#68758c"},
            },
            "height": 290,
        },
        use_container_width=True,
    )


with st.container(key="chart_section"):
    st.markdown('<div class="chart-top-spacer"></div>', unsafe_allow_html=True)
    st.markdown('<div id="monitoring"></div>', unsafe_allow_html=True)
    st.markdown("### Approval rate — live")
    render_live_chart()
    st.markdown(
        '<div id="countries" class="country-anchor"></div>', unsafe_allow_html=True
    )
    st.markdown("### Country status")
    country_entries = []
    for country_name, country in countries.items():
        status_class = {
            "Stable": "status-ok",
            "Attention": "status-watch",
            "Critical": "status-critical",
        }[country["status"]]
        country_entries.append(
            f"<div class='country-entry'><span class='country-name'>{country_name}</span>"
            f"<span class='country-separator'>·</span><span class='country-rate'>{country['approval']:.1f}%</span>"
            f"<span class='country-separator'>·</span>"
            f"<span class='{status_class}'>{country['status']}</span></div>"
        )
    st.markdown(
        f"<div class='country-row'>{''.join(country_entries)}</div>",
        unsafe_allow_html=True,
    )

st.markdown(
    '<div id="incident-detail"></div><div id="diagnosis"></div>', unsafe_allow_html=True
)
st.markdown("### Root cause & recommendation")
if incident is None:
    st.success("There are no incidents to diagnose.", icon="✅")
else:
    if incident.get("executive_summary"):
        st.info(incident["executive_summary"], icon="📌")
    diagnosis_confirmed = incident.get("diagnosis_status") == "confirmed"
    diagnosis_column, action_column = st.columns(2)
    with diagnosis_column:
        with st.container(border=True):
            st.markdown(
                "#### Confirmed root cause"
                if diagnosis_confirmed
                else "#### Evidence under review"
            )
            root_cause_items = "".join(
                f"<div class='cause-item'><div class='cause-label'>{label}</div>"
                f"<div class='cause-value'>{value}</div></div>"
                for label, value in incident["root_cause"].items()
            )
            st.markdown(
                f"<div class='root-cause-grid'>{root_cause_items}</div>",
                unsafe_allow_html=True,
            )
            st.markdown("##### Operations assessment")
            st.write(incident["diagnosis"])
            st.caption(f"Confidence: {incident['confidence']:.0%}")
            if incident.get("evidence_citations"):
                citation_labels = incident.get("evidence_citation_labels", {})
                st.caption(
                    "Evidence citations: "
                    + "; ".join(
                        citation_labels.get(citation, citation)
                        for citation in incident["evidence_citations"]
                    )
                )
    with action_column:
        with st.container(border=True):
            st.markdown("#### Recommended action")
            st.info(incident["recommendation"], icon="💡")

st.caption("Control Tower MVP — Simulated data for validating the demo flow")
