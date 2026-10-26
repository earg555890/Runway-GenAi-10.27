"""Runway front end.  streamlit run ui/app.py   (DATA_BACKEND=local or zetaris, from .env or the environment)

Two modes (switch in the header): the demo student Maya (synthetic, eight sources) and My data (the student's own
bank file, kept on this computer; rule 7). Reads everything through normalize and engine; the UI does no money math
(rule 2).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

import config  # noqa: E402
import engine  # noqa: E402
import mydata  # noqa: E402
from ui import (afford, ask, behind, budget, checkin, data, findmoney, found, myimport, semester, state,  # noqa: E402
                style, top)


def page(ds, note):
    mine = state.mine()
    subs = engine.subscriptions(ds)
    state.init(subs)
    if mine:
        state.fit_dates()
    scenario = state.scenario(subs)
    changed = state.changed(scenario)
    ledger = engine.Ledger()
    base = engine.project(engine.Scenario(refund_submit_date=scenario.refund_submit_date), ds, ledger)
    current = engine.project(scenario, ds, ledger) if changed else base
    deltas = engine.compare(base, current, ledger) if changed else None

    top.header(ds, note)
    if mine:
        myimport.manage()
    with st.container(key="notices"):                 # 2. the important notices: status card + check-in
        top.status(current)
        checkin.render(ds, state.done_scenario())

    tab1, tab_budget, tab2, tab_money, tab3 = st.tabs(["Semester", "Budget", "Afford it?", "Find money", "Findings"])
    with tab1:
        semester.render(ds, subs, base, current, changed, deltas)
    with tab_budget:
        budget.render(ds, scenario)
    with tab2:
        afford.render(ds, current)
    with tab_money:
        findmoney.render(ds, scenario)
    with tab3:
        found.render(ds, engine.Scenario(refund_submit_date=scenario.refund_submit_date))

    st.write("")
    behind.render(ledger, ds)
    ask.panel(ds, scenario)                           # the floating chat button and, when open, the chat panel


st.set_page_config(page_title="Runway", page_icon=":material/flight_takeoff:", layout="wide",
                   initial_sidebar_state="collapsed")
style.apply()
state.init_mode()
top.mode_switch()
if state.mine():
    if not mydata.exists():
        top.header_empty()
        myimport.render()
        st.stop()
    my_ds = myimport.load()
    today, start, end = mydata.dates(my_ds)
    with config.as_of(today, start, end, start):     # her dates: today is the last day in her file
        page(my_ds, None)
else:
    page(*data.load_dataset())
