"""The "this is Zetaris" moment: one federated query across checking AND card, live and uncached."""
import threading
import time

import pandas as pd
import streamlit as st

import data_access as da
from ui import data

QUERY = "federated_recurring_charges"


def _run(out):
    try:
        out["result"] = da.run(QUERY, backend="zetaris", use_cache=False)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"


def render():
    st.subheader("Run live on Zetaris")
    st.markdown("One federated SQL query over two separate sources, the checking account and the credit card, "
                "to find charges that repeat every month. No cache: this goes to Zetaris right now.")
    reachable = data.zetaris_reachable()
    host, port = data.zetaris_address()
    clicked = st.button("Run live on Zetaris", icon=":material/bolt:", disabled=not reachable, key="live_run")
    if not reachable:
        st.caption(f"Zetaris isn't reachable at {host}:{port} right now. Start the Zetaris Docker bundle to try this.")
    if clicked:
        out, timer = {}, st.empty()
        worker = threading.Thread(target=_run, args=(out,), daemon=True)
        start = time.perf_counter()
        worker.start()
        while worker.is_alive():
            timer.markdown(f":stopwatch: Running on Zetaris... **{time.perf_counter() - start:.1f} s**")
            time.sleep(0.1)
        timer.empty()
        st.session_state.live = dict(out, seconds=time.perf_counter() - start)
    live = st.session_state.get("live")
    if live:
        if "error" in live:
            st.error(f"The live query failed after {live['seconds']:.1f} s: {live['error']}")
            return
        r = live["result"]
        st.success(f"Zetaris answered in **{live['seconds']:.1f} s**: {len(r.rows)} rows from "
                   f"{' and '.join(r.evidence.sources)}.")
        st.code(r.evidence.sql, language="sql", wrap_lines=True)
        cols = ["source"] + [c for c in r.columns if c != "source"]
        st.dataframe(pd.DataFrame(r.rows)[cols], hide_index=True, width="stretch")
