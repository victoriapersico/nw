"""Streamlit entrypoint for the Payment Control Tower."""

from pathlib import Path
import runpy

import streamlit as st


st.set_page_config(page_title="Payment Control Tower", page_icon="📡", layout="wide")

runpy.run_path(str(Path(__file__).parent / "pages" / "0_Client.py"))
