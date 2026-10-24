"""Runway front end.  streamlit run ui/app.py   (DATA_BACKEND=local or zetaris, from .env or the environment)

Reads everything through normalize and engine; the UI does no money math (rule 2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

import engine  # noqa: E402
from ui import afford, ask, behind, data, found, semester, state, style, top  # noqa: E402

st.set_page_config(page_title="Runway", page_icon=":material/flight_takeoff:", layout="wide",
                   initial_sidebar_state="collapsed")
style.apply()
ds, note = data.load_dataset()
subs = engine.subscriptions(ds)
state.init(subs)

scenario = state.scenario(subs)
changed = state.changed(scenario)
ledger = engine.Ledger()
base = engine.project(engine.Scenario(refund_submit_date=scenario.refund_submit_date), ds, ledger)
current = engine.project(scenario, ds, ledger) if changed else base
if changed:
    engine.compare(base, current, ledger)

top.header(ds, note)
top.status(current)
ask.render()

tab1, tab2, tab3 = st.tabs(["My semester", "Can I afford it?", "What we found"])
with tab1:
    semester.render(ds, subs, base, current, changed)
with tab2:
    afford.render(ds, current)
with tab3:
    found.render(ds, engine.Scenario(refund_submit_date=scenario.refund_submit_date))

st.write("")
behind.render(ledger, ds)
