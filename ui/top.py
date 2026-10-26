"""Always visible: greeting, quiet badges, and the one big sentence about the current what-if."""
import streamlit as st

import config
import engine
from ui import data, fmt

CLOSE_CALL = 50     # dollars: "That's cutting it close." below this lowest point
SHORT_NAMES = {"rent": "rent", "card_autopay": "card payment", "installment": "tuition payment",
               "recurring_bill": "bill", "subscription": "subscription"}


def header(ds, note=None):
    left, right = st.columns([3, 2], vertical_alignment="bottom")
    left.markdown('<p class="rw-brand">Runway</p><p class="rw-hello">How long your money lasts this semester.</p>', unsafe_allow_html=True)
    with right.container(horizontal=True, horizontal_alignment="right", gap="small", key="badges"):
        st.badge(data.backend_label(ds), color="gray")
        st.badge("Reasoning by NVIDIA Nemotron", color="green")
        st.badge(f"Today: {fmt.day(config.DEMO_TODAY)}", color="gray")
    if note:
        st.info(fmt.md(note))


def _thing(e):
    return e.label if e.kind == "purchase" else SHORT_NAMES.get(e.kind, fmt.event_name(e))


def headline(p):
    """(big sentence, one short reason, good?) for a projection. The lowest point and the end balance are left
    to the big-number area, so they are not repeated here."""
    r = engine.main_reason(p)
    if p.lasts_through_semester:
        why = f"It gets closest after {_thing(r.event)} on {fmt.day(r.event.date)}." if r.event else ""
        return "You're covered all semester.", why, True
    when = p.first_below_zero.value
    big = f"Your money runs out in {fmt.weeks_words(p.runway_weeks.value)}, on {fmt.day(when)}."
    if r.event and r.event.date == when:
        why = (f"A {fmt.dollars(r.event.amount)} {_thing(r.event)} is due that day. "
               f"You'll only have {fmt.balance(r.balance_before)}.")
    elif r.event:
        why = f"After {fmt.dollars(r.event.amount)} {_thing(r.event)} on {fmt.day(r.event.date)}, you slip below zero."
    else:
        why = "Everyday spending slowly takes you below zero."
    return big, why, False


def status(p):
    big, why, good = headline(p)
    n = len(p.scenario.approved)
    note = (f"Counting {n} aid award{'s' if n != 1 else ''} as if approved. It isn't certain money." if n else "")
    st.markdown(f'<div class="rw-status {"rw-good" if good else "rw-bad"}"><div class="rw-big">{fmt.html(big)}</div>'
                + (f'<div class="rw-why">{fmt.html(why)}</div>' if why else "")
                + (f'<div class="rw-why rw-if">{fmt.html(note)}</div>' if note else "") + "</div>", unsafe_allow_html=True)
