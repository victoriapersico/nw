"""Streamlit entrypoint for the Payment Control Tower."""

from pathlib import Path
import runpy
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st


st.set_page_config(page_title="Payment Control Tower", page_icon="📡", layout="wide")

runpy.run_path(str(Path(__file__).parent / "pages" / "0_Client.py"))
