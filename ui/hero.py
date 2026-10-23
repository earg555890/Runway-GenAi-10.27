"""Three headline metrics for the current scenario, with the change vs "nothing changes"."""
import streamlit as st

import config
from ui import fmt


def runway_text(p):
    if p.lasts_through_semester:
        return "Lasts the whole semester"
    return f"{p.runway_weeks.value} weeks, until {fmt.day(p.first_below_zero.value)}"


def render(base, current, deltas):
    d = deltas or {}
    c1, c2, c3 = st.columns(3)
    weeks = d.get("runway_weeks")
    c1.metric("Runway", runway_text(current), border=True,
              delta=None if not weeks or weeks.value == 0 else f"{'+' if weeks.value > 0 else ''}{weeks.value} weeks",
              help="How long checking stays at or above $0, counted from today.")
    c2.metric(f"Lowest balance ({fmt.day(current.lowest_date.value)})", fmt.money(current.lowest.value), border=True,
              delta=fmt.signed_money(d["lowest"].value) if d else None)
    c3.metric(f"Balance at semester end ({fmt.day(config.SEMESTER_END)})", fmt.money(current.end_balance.value),
              border=True, delta=fmt.signed_money(d["end_balance"].value) if d else None)
    if d:
        st.caption(f"Changes are compared with \"nothing changes\". Your what-if: {current.scenario.describe()}.")
