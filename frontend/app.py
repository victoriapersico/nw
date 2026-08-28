"""Streamlit frontend for the generic hackathon starter."""

import os
from typing import Any

from dotenv import load_dotenv
import requests
import streamlit as st


load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("BACKEND_REQUEST_TIMEOUT_SECONDS", "90"))

st.set_page_config(
    page_title="NextWave AI Starter",
    page_icon="⚡",
    layout="centered",
)

st.markdown(
    """
    <style>
        .block-container {max-width: 850px; padding-top: 3rem;}
        [data-testid="stMetric"] {
            background: rgba(124, 58, 237, 0.07);
            border: 1px solid rgba(124, 58, 237, 0.18);
            border-radius: 0.75rem;
            padding: 0.8rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def request_analysis(input_text: str, record_id: str) -> dict[str, Any]:
    """Call the FastAPI backend with an explicit timeout and clear errors."""

    try:
        response = requests.post(
            f"{BACKEND_URL}/analyze",
            json={"input_text": input_text, "record_id": record_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise RuntimeError(
            "The analysis timed out. Check the backend or increase its API timeout."
        ) from exc
    except requests.ConnectionError as exc:
        raise RuntimeError(
            f"Could not reach the backend at {BACKEND_URL}. Is FastAPI running?"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Backend request failed: {exc}") from exc

    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text or "No error details were returned."
        raise RuntimeError(f"Backend returned {response.status_code}: {detail}")

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Backend returned an invalid JSON response.") from exc


st.title("⚡ NextWave AI Practice Starter")
st.write(
    "A minimal end-to-end demo: send context to FastAPI, run AI decision logic "
    "with Python tools, and receive a structured result."
)

with st.form("analysis_form"):
    input_text = st.text_area(
        "What should the assistant analyze?",
        value="Review this record and recommend the best next action.",
        height=140,
        help="Tomorrow, replace this with the challenge-specific input.",
    )
    record_id = st.text_input(
        "Sample record ID",
        value="REC-001",
        help="Available examples: REC-001, REC-002, REC-003",
    )
    submitted = st.form_submit_button("Analyze", type="primary", use_container_width=True)

if submitted:
    if not input_text.strip() or not record_id.strip():
        st.warning("Enter both analysis text and a record ID.")
    else:
        with st.spinner("Analyzing the record and running tools..."):
            try:
                result = request_analysis(input_text.strip(), record_id.strip())
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                with st.container(border=True):
                    st.subheader("Analysis result")
                    st.caption(f"Completed in {result['mode'].upper()} mode")

                    decision_column, confidence_column = st.columns(2)
                    decision_column.metric(
                        "Decision", result["decision"].replace("_", " ").title()
                    )
                    confidence_column.metric(
                        "Confidence", f"{result['confidence']:.0%}"
                    )

                    st.markdown("#### Recommended action")
                    st.success(result["recommended_action"])

                    st.markdown("#### Why")
                    st.write(result["reasoning_summary"])

                    st.markdown("#### Tools used")
                    st.markdown(" · ".join(f"`{name}`" for name in result["tools_used"]))

st.caption(f"Backend: {BACKEND_URL}")
