"""Always visible: greeting, quiet badges, and the one big sentence about the current what-if."""
import streamlit as st

import config
import engine
from ui import data, fmt, state

CLOSE_CALL = 50     # dollars: "That's cutting it close." below this lowest point


def header(ds, note=None):
    left, right = st.columns([3, 2], vertical_alignment="bottom")
    left.markdown('<p class="rw-brand">Runway</p><p class="rw-hello">Hi Maya. See how long your money lasts this '
                  'semester, and why.</p>', unsafe_allow_html=True)
    with right.container(horizontal=True, horizontal_alignment="right", gap="small"):
        st.badge(data.backend_label(ds), color="gray")
        st.badge("NVIDIA Nemotron (soon)", color="gray")
        st.badge(f"Today: {fmt.day(config.DEMO_TODAY)}, {config.DEMO_TODAY.year}", color="gray")
    if note:
        st.info(fmt.md(note))


def headline(p):
    """(big sentence, reason sentence, good?) for a projection."""
    r = engine.main_reason(p)
    if p.lasts_through_semester:
        big = (f"You're covered through the end of the semester. Lowest point: {fmt.money(p.lowest.value)} "
               f"on {fmt.day(p.lowest_date.value)}.")
        why = (f"Your lowest point comes right after your {fmt.event_name(r.event)} of {fmt.money(-r.event.amount)} "
               f"on {fmt.day(r.event.date)}." if r.event else "")
        if p.lowest.value < CLOSE_CALL:
            why += " That's cutting it close."
        return big, why.strip(), True
    when = p.first_below_zero.value
    big = f"Your money runs out {fmt.day(when)}, {fmt.weeks_words(p.runway_weeks.value)} from today."
    if r.event and r.event.date == when:
        why = (f"Your {fmt.event_name(r.event)} of {fmt.money(-r.event.amount)} that day is more than you'll have "
               f"({fmt.money(r.balance_before)}).")
    elif r.event:
        why = (f"After your {fmt.event_name(r.event)} of {fmt.money(-r.event.amount)} on {fmt.day(r.event.date)}, "
               "everyday spending takes you below $0.")
    else:
        why = "Everyday spending slowly takes you below $0."
    return big, why, False


def status(p):
    big, why, good = headline(p)
    plan = state.summary(p.scenario)
    st.markdown(f'<div class="rw-status {"rw-good" if good else "rw-bad"}"><div class="rw-big">{fmt.html(big)}</div>'
                + (f'<div class="rw-why">{fmt.html(why)}</div>' if why else "")
                + (f'<div class="rw-plan">With your what-ifs: {fmt.html(plan)}.</div>' if plan else "")
                + "</div>", unsafe_allow_html=True)
