"""Tab 2, "Afford it?": one purchase, one big verdict, numbered steps, one line about the lowest point."""
from datetime import timedelta

import streamlit as st

import config
import engine
from ui import fmt, state
from ui.top import CLOSE_CALL


def _step(f, ds):
    if f.kind == "refund":
        rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=st.session_state.wf_submit))
        return f"Send your verification form. Your {fmt.dollars(f.savings.value)} refund comes around {fmt.day(rel)}."
    return f"Cancel {f.name}. That saves {fmt.dollars(f.savings.value)} this semester."


def _verdict(text, good):
    st.markdown(f'<div class="rw-answer {"rw-green" if good else "rw-red"}">{fmt.html(text)}</div>',
                unsafe_allow_html=True)


def _lowest(p, prefix="Your lowest point would be"):
    close = " That's cutting it close." if 0 <= p.lowest.value < CLOSE_CALL else ""
    st.markdown(fmt.md(f"{prefix} {fmt.balance(p.lowest.value)} on {fmt.day(p.lowest_date.value)}.{close}"))


def render(ds, current):
    s = st.session_state
    a, b, c = st.columns([3, 2, 2])
    a.text_input("What is it?", key="buy_label")
    b.number_input("How much? ($)", key="buy_cost", min_value=0.0, step=10.0, format="%.2f")
    c.date_input("When?", key="buy_date", min_value=config.DEMO_TODAY + timedelta(days=1),
                 max_value=config.SEMESTER_END, format="MM/DD/YYYY")
    st.checkbox("Paying by card?", key="buy_card", help="Card purchases leave checking later, when you pay the bill.")
    p = state.purchase()
    st.button("Check", type="primary", key="buy_check", on_click=state.check_purchase, disabled=p is None)
    if not s.buy_active or p is None:
        return

    v = engine.can_afford(p.cost, p.date, p.account, state.choices(), ds, p.label)
    if v.verdict == "yes":
        _verdict("Yes", True)
        _lowest(v.without_fixes)
    elif v.verdict == "no":
        _verdict("Not right now", False)
        _lowest(v.with_fixes, "Even with every fix, you'd be")
    elif all(s.wf_refund if f.kind == "refund" else s[state.cancel_key(f.name)] for f in v.fixes):
        _verdict("You can afford it.", True)
        _lowest(current)
    else:
        _verdict(f"Yes, if you do {fmt.things(len(v.fixes))} first", True)
        st.markdown(fmt.md("\n".join(f"{i}. {_step(f, ds)}" for i, f in enumerate(v.fixes, start=1))))
        st.button("Do these", type="primary", key="buy_do", on_click=state.apply_fixes, args=(v.fixes,))
        _lowest(v.with_fixes, "With both, your lowest point would be" if len(v.fixes) == 2 else
                "Then your lowest point would be")
    st.button("Remove this purchase from my plan", type="tertiary", key="buy_drop", on_click=state.drop_purchase)
