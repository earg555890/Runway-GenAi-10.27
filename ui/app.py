"""Runway front end.  streamlit run ui/app.py   (DATA_BACKEND=local or zetaris, from .env or the environment)

Reads everything through normalize and engine; the UI does no money math (rule 2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

import engine  # noqa: E402
from ui import ask, chart, data, explain, findings, header, hero, live_zetaris, sidebar, state, whatif  # noqa: E402

st.set_page_config(page_title="Runway", page_icon=":material/flight_takeoff:", layout="wide")

ds, note = data.load_dataset()
header.render(ds, note)
sidebar.render(ds)

subs = engine.subscriptions(ds)
state.init(subs)
scenario = state.scenario(subs)
ledger = engine.Ledger()
base = engine.project(engine.Scenario(refund_submit_date=scenario.refund_submit_date), ds, ledger)
same = state.is_base(scenario)
current = base if same else engine.project(scenario, ds, ledger)
deltas = None if same else engine.compare(base, current, ledger)

hero.render(base, current, deltas)
left, right = st.columns([3, 2], gap="large")
with right:
    whatif.render(ds, subs, current)
with left:
    chart.render(base, current, same)

findings.render(ds, engine.Scenario(refund_submit_date=scenario.refund_submit_date))
explain.render(ledger, ds)
live_zetaris.render()
ask.render()
