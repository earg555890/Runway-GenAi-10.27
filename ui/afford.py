"""Tab 2, "Can I afford it?": one purchase, one big answer, one button to do the fixes."""
from datetime import timedelta

import streamlit as st

import config
import engine
from ui import fmt, state
from ui.top import CLOSE_CALL


def _fix_sentence(f, ds):
    if f.kind == "refund":
        rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=st.session_state.wf_submit))
        return (f"Send your verification form to financial aid, so your {fmt.money(f.savings.value)} refund "
                f"arrives around {fmt.day(rel)}.")
    return f"Cancel {f.name}. That saves {fmt.money(f.savings.value)} before the semester ends."


def _answer(text, good):
    st.markdown(f'<div class="rw-answer {"rw-green" if good else "rw-red"}">{fmt.html(text)}</div>',
                unsafe_allow_html=True)


def render(ds, current):
    s = st.session_state
    a, b, c = st.columns([3, 2, 2])
    a.text_input("What is it?", key="buy_label")
    b.number_input("How much? ($)", key="buy_cost", min_value=0.0, step=10.0, format="%.2f")
    c.date_input("When?", key="buy_date", min_value=config.DEMO_TODAY + timedelta(days=1),
                 max_value=config.SEMESTER_END, format="MM/DD/YYYY")
    st.checkbox("Paying by credit card?", key="buy_card",
                help="Card purchases leave checking later, when you pay the card bill.")
    p = state.purchase()
    st.button("Check", type="primary", key="buy_check", on_click=state.check_purchase, disabled=p is None)
    if not s.buy_active or p is None:
        return

    v = engine.can_afford(p.cost, p.date, p.account, state.choices(), ds, p.label)
    if v.verdict == "yes":
        low = v.without_fixes
        _answer("Yes", True)
        st.markdown(fmt.md(f"Your lowest point would be {fmt.money(low.lowest.value)} on "
                           f"{fmt.day(low.lowest_date.value)}."
                           + (" That's cutting it close." if low.lowest.value < CLOSE_CALL else "")))
    elif v.verdict == "no":
        _answer("Not right now", False)
        st.markdown(fmt.md(f"Even with every fix, your balance would drop to {fmt.money(v.with_fixes.lowest.value)} "
                           f"on {fmt.day(v.with_fixes.lowest_date.value)}."))
    else:
        done = all(s.wf_refund if f.kind == "refund" else s[state.cancel_key(f.name)] for f in v.fixes)
        if done:
            _answer("You can afford it.", True)
            st.markdown(fmt.md(f"Your lowest point would be {fmt.money(current.lowest.value)} on "
                               f"{fmt.day(current.lowest_date.value)}."
                               + (" That's cutting it close." if current.lowest.value < CLOSE_CALL else "")))
        else:
            _answer(f"Yes, if you do {fmt.things(len(v.fixes))}", True)
            st.markdown(fmt.md("\n".join(f"{i}. {_fix_sentence(f, ds)}" for i, f in enumerate(v.fixes, start=1))))
            st.caption(fmt.md(f"Without them, your balance would drop to {fmt.money(v.without_fixes.lowest.value)} "
                              f"on {fmt.day(v.without_fixes.lowest_date.value)}."))
            st.button("Do these", type="primary", key="buy_do", on_click=state.apply_fixes, args=(v.fixes,))
    st.button(fmt.md(f"Take {p.label} out of my plan"), type="tertiary", key="buy_drop", on_click=state.drop_purchase)
