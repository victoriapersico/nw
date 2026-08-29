"""Judge-only incident injection controls for the Control Tower demo."""

import streamlit as st
import os
import requests

from backend.schemas import (
    COUNTRY_ISSUING_BANKS,
    COUNTRY_PAYMENT_METHODS,
    InjectionConfig,
)

API_BASE_URL = os.getenv(
      "CONTROL_TOWER_API_URL",
      "http://127.0.0.1:8000",
)

st.markdown(
    """
    <style>
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display:none !important; }
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 88% 8%, #b9f7ff 0, transparent 28rem),
                radial-gradient(circle at 8% 88%, #d8c7ff 0, transparent 30rem),
                linear-gradient(135deg,#eef3ff 0%,#f8f5ff 48%,#d9f7ff 130%);
            background-attachment:fixed;
        }
        .block-container { position:relative; z-index:2; }
        html,body,[class*="css"] { font-family:"Segoe UI Variable Text","Aptos",sans-serif; }
        h1,h2,h3 { font-family:"Segoe UI Variable Display","Aptos Display",sans-serif !important; letter-spacing:-.04em !important; }
        .lab-brand { font-family:"Bahnschrift SemiCondensed","Arial Narrow",sans-serif; font-size:.78rem; font-weight:750; letter-spacing:.13em; text-transform:uppercase; color:#baf7ff; }
        .lab-hero { position:relative; overflow:hidden; color:white; background:linear-gradient(120deg,rgba(31,25,92,.96),rgba(99,49,211,.92) 58%,rgba(0,184,220,.86)); border:1px solid rgba(255,255,255,.32); border-radius:26px; padding:1.8rem 2rem; margin:.4rem 0 1.25rem; box-shadow:0 20px 48px rgba(77,56,170,.24); backdrop-filter:blur(18px); }
        .lab-hero::after { content:""; position:absolute; width:13rem; height:13rem; right:-3rem; top:-6rem; border-radius:50%; background:rgba(255,255,255,.12); box-shadow:0 0 60px rgba(130,244,255,.28); }
        .lab-title { font-size:clamp(2.5rem,5vw,4.2rem); font-weight:850; line-height:1; letter-spacing:-.055em; margin:.4rem 0; }
        .lab-copy { max-width:740px; opacity:.84; }
        .isolation-note { background:rgba(255,255,255,.55); border:1px solid rgba(255,255,255,.75); border-radius:18px; padding:1rem 1.15rem; margin-bottom:1.1rem; backdrop-filter:blur(14px); }
        [data-testid="stForm"] { background:rgba(255,255,255,.48); border:1px solid rgba(255,255,255,.72); border-radius:22px; padding:1.25rem; backdrop-filter:blur(16px); box-shadow:0 15px 34px rgba(40,50,80,.08); }
        [data-testid="stSidebar"] { background:linear-gradient(180deg,#fff,#e9e3ff 70%,#d7f8ff); }
        .bubble-field { position:fixed; inset:0; z-index:1; overflow:hidden; pointer-events:none; }
        .bubble { --size:70px; --left:10%; --duration:18s; --delay:0s; position:absolute; left:var(--left); bottom:-22vh; width:var(--size); height:var(--size); border-radius:50%; background:linear-gradient(145deg,rgba(255,255,255,.58),rgba(121,91,255,.14)); border:1px solid rgba(255,255,255,.7); box-shadow:inset -10px -10px 24px rgba(86,65,180,.1),0 8px 30px rgba(55,85,170,.1); backdrop-filter:blur(3px); animation:bubble-rise var(--duration) linear var(--delay) infinite; }
        .bubble:nth-child(3n) { background:linear-gradient(145deg,rgba(255,255,255,.6),rgba(25,212,232,.18)); }
        .bubble:nth-child(4n) { border-radius:42% 58% 55% 45%; }
        @keyframes bubble-rise {
            0% { transform:translate3d(0,0,0) scale(.72); opacity:0; }
            10% { opacity:.72; }
            55% { transform:translate3d(38px,-68vh,0) scale(1); }
            100% { transform:translate3d(-18px,-135vh,0) scale(1.12); opacity:0; }
        }
        @media (prefers-reduced-motion:reduce) { .bubble { animation:none; opacity:.28; bottom:auto; top:var(--left); } }
    </style>
    <div class="bubble-field" aria-hidden="true">
        <span class="bubble" style="--size:54px;--left:6%;--duration:20s;--delay:-4s"></span>
        <span class="bubble" style="--size:92px;--left:17%;--duration:25s;--delay:-17s"></span>
        <span class="bubble" style="--size:38px;--left:29%;--duration:17s;--delay:-9s"></span>
        <span class="bubble" style="--size:118px;--left:43%;--duration:29s;--delay:-22s"></span>
        <span class="bubble" style="--size:48px;--left:57%;--duration:19s;--delay:-13s"></span>
        <span class="bubble" style="--size:76px;--left:69%;--duration:23s;--delay:-6s"></span>
        <span class="bubble" style="--size:32px;--left:80%;--duration:16s;--delay:-11s"></span>
        <span class="bubble" style="--size:104px;--left:91%;--duration:27s;--delay:-19s"></span>
    </div>
    <div class="lab-hero">
        <div class="lab-brand">NextWave Hackathon 2026 · Team Moche</div>
        <div class="lab-title">Judge Lab</div>
        <div class="lab-copy">Inject an unseen payment degradation, then return to the Control Tower and watch the incident appear.</div>
    </div>
    <div class="isolation-note"><b>Isolation guarantee</b><br>
    The injector modifies simulated future state only. Its configuration is never passed to the detector.</div>
    """,
    unsafe_allow_html=True,
)

with st.form("judge_injection_form"):
    st.markdown("### Configure incident")
    form_left, form_middle, form_right = st.columns(3)
    with form_left:
        merchant = st.selectbox("Merchant", ["Rappi", "Carrefour", "Despegar"], index=2)
        country = st.selectbox("Country", ["Mexico", "Brazil", "Colombia"])
        provider = st.selectbox("Provider", ["Any", "Stripe", "Adyen", "dLocal"], index=2)
    with form_middle:
        payment_method = st.selectbox(
            "Payment method",
            ["Any", *sorted(COUNTRY_PAYMENT_METHODS[country])],
        )
        issuing_bank = st.selectbox(
            "Issuing bank",
            ["Any", *sorted(COUNTRY_ISSUING_BANKS[country])],
        )
        decline_code = st.selectbox(
            "Decline code",
            ["Not specified", "05", "51", "54", "57", "61", "91", "96"],
        )
    with form_right:
        target_rate_percent = st.slider("Target approval rate", 0, 100, 30, 5)
        duration_windows = st.number_input(
            "Duration (5-minute windows)", min_value=1, max_value=24, value=6
        )
        st.caption("Six windows equal 30 simulated minutes.")

    submitted = st.form_submit_button(
        "Inject incident",
        type="primary",
        use_container_width=True,
    )

if submitted:
    config = InjectionConfig(
        merchant=merchant,
        country=country,
        provider=None if provider == "Any" else provider,
        payment_method=None if payment_method == "Any" else payment_method,
        issuing_bank=None if issuing_bank == "Any" else issuing_bank,
        decline_code=None if decline_code == "Not specified" else decline_code,
        target_approval_rate=target_rate_percent / 100,
        duration_windows=int(duration_windows),
    )

    try:
        response = requests.post(
            f"{API_BASE_URL}/injections",
            json={"config": config.model_dump(mode="json")},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        st.session_state["active_injection"] = config.model_dump(mode="json")
        st.session_state["injection_id"] = result["injection_id"]
        st.rerun()
    except requests.RequestException as exc:
        st.error(f"Could not create the test injection: {exc}")

active_injection = st.session_state.get("active_injection")
if active_injection:
    st.markdown("### Active test incident")
    status_column, reset_column = st.columns([4, 1])
    status_column.error(
        f"{active_injection['merchant']} · {active_injection['country']} · "
        f"target approval {active_injection['target_approval_rate']:.0%}",
        icon="🚨",
    )
    if reset_column.button("Reset", use_container_width=True):
        del st.session_state["active_injection"]
        st.rerun()
else:
    st.info("No test injection is currently active.")

st.caption("Judge-only demo controls · Team Moche")
