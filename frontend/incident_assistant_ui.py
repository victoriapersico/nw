"""Streamlit panel for evidence-only questions about the selected incident."""

from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.remediation_client import (
    RemediationClientError,
    ask_incident_assistant,
)


_MODE_LABELS = {
    "openai": "OpenAI · structured evidence-only response",
    "mock": "Deterministic Mock Mode response",
    "fallback": "Deterministic fallback after the LLM was unavailable",
}


def _render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        evidence = message.get("evidence") or []
        if evidence:
            with st.expander(
                f"Evidence used · {len(evidence)} facts",
                icon=":material/fact_check:",
            ):
                for fact in evidence:
                    st.markdown(f"**{fact['label']}**")
                    st.caption(fact["value"])
        if message["role"] == "assistant" and message.get("mode"):
            st.caption(_MODE_LABELS.get(message["mode"], "Evidence-only response"))


def render_incident_assistant(
    api_base_url: str,
    merchant: str,
    incident_id: str,
) -> None:
    """Render chat history isolated to one selected incident."""

    history_key = f"incident-assistant-history:{merchant}:{incident_id}"
    history = st.session_state.setdefault(history_key, [])

    with st.container(border=True):
        st.markdown("#### Ask about this incident")
        st.caption(
            "Answers use only this incident's evidence and counterfactual simulation. "
            "The assistant cannot approve changes, contact providers, or alter routing."
        )

        message_area = st.container(height=300, border=False)
        with message_area:
            if not history:
                st.info(
                    "Try: “What is the root cause?”, “What is the estimated impact?”, "
                    "or “Why is this simulation safer?”",
                    icon=":material/chat_info:",
                )
            for message in history:
                _render_message(message)

        prompt = st.chat_input(
            "Ask a standalone question about this incident",
            key=f"incident-assistant-input:{merchant}:{incident_id}",
            max_chars=1_000,
            submit_mode="disable",
        )
        if not prompt:
            return

        user_message = {"role": "user", "content": prompt}
        history.append(user_message)
        with message_area:
            _render_message(user_message)

        try:
            with st.spinner("Checking the incident evidence", show_time=True):
                response = ask_incident_assistant(
                    api_base_url,
                    incident_id,
                    merchant,
                    prompt,
                )
        except RemediationClientError as exc:
            error_message = {
                "role": "assistant",
                "content": f"The incident assistant is unavailable: {exc}",
                "evidence": [],
            }
            history.append(error_message)
            with message_area:
                _render_message(error_message)
            return

        assistant_message = {
            "role": "assistant",
            "content": response["answer"],
            "evidence": response.get("evidence", []),
            "mode": response.get("mode"),
        }
        history.append(assistant_message)
        with message_area:
            _render_message(assistant_message)
