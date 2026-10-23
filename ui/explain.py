"""How Runway calculated this: every Computed record, traceable to source rows and query evidence."""
import re
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from ui import fmt

C_ID = re.compile(r"^C\d+$")


def _goto(ids):
    picked = st.session_state.get("explain_input")
    if picked and C_ID.match(picked) and picked in ids:
        st.session_state.explain_record = picked
        st.session_state.explain_input = None


def _row(ds, row_id):
    rec = ds.row(row_id)
    fields = {k: (v.isoformat() if isinstance(v, date) else str(v) if isinstance(v, Decimal) else v)
              for k, v in asdict(rec).items()}
    st.markdown(f"**{row_id}**: source `{rec.source}`, table `{rec.table}`")
    st.dataframe(pd.DataFrame([{"field": k, "value": "" if v is None else str(v)} for k, v in fields.items()]),
                 hide_index=True, width="stretch")
    for ev in ds.evidence:
        if row_id in ev.row_ids:
            took = f"{ev.duration_s:.3f} s"
            if ev.original_duration_s is not None:
                took += f" (original Zetaris query: {ev.original_duration_s:.1f} s)"
            st.markdown(f"Returned by query **{ev.query}** · backend `{ev.backend}` · {took}")
            st.code(ev.sql, language="sql", wrap_lines=True)


def render(ledger, ds):
    with st.expander("How Runway calculated this", icon=":material/calculate:"):
        st.caption("Every number above is a computed record, worked out in plain Python from Maya's source rows "
                   "(no AI does the math). Pick a record to see how it was made and which rows it came from.")
        items = ledger.items
        ids = [c.id for c in items]
        st.dataframe(pd.DataFrame([{"id": c.id, "what": c.label, "value": fmt.value(c), "how": c.how} for c in items]),
                     hide_index=True, width="stretch", height=280,
                     column_config={"how": st.column_config.TextColumn(width="large")})
        if st.session_state.get("explain_record") not in ids:
            st.session_state.explain_record = ids[0]
        st.selectbox("Look closer at a record", ids, key="explain_record",
                     format_func=lambda i: f"{i}: {ledger.get(i).label}")
        c = ledger.get(st.session_state.explain_record)
        st.markdown(f"**{c.label}** = **{fmt.value(c)}**")
        st.markdown(c.how)
        if c.inputs:
            st.pills("Built from (click a row ID to see the row, or a C# to jump to that record)", c.inputs,
                     key="explain_input", on_change=_goto, args=(ids,))
            picked = st.session_state.get("explain_input")
            if picked and picked in c.inputs and not C_ID.match(picked):
                _row(ds, picked)
