import streamlit as st

import config
from ui import data, fmt


def render(ds, note=None):
    st.title("Runway")
    st.markdown("##### See how long your money lasts this semester, and why.")
    with st.container(horizontal=True, gap="small"):
        st.badge(data.backend_label(ds), icon=":material/database:", color="green" if ds.backend != "local" else "blue")
        st.badge("Reasoning by NVIDIA Nemotron (coming soon)", icon=":material/psychology:", color="gray")
        st.badge(f"Demo date: {fmt.day(config.DEMO_TODAY)}, {config.DEMO_TODAY.year}", icon=":material/event:",
                 color="orange")
    if note:
        st.warning(note)
