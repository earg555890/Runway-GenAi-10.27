"""Tab 1, "My semester": the balance chart and up to three ways to fix it."""
from datetime import timedelta

import streamlit as st

import config
import engine
from ui import chart, fmt, state


def _card(title, body, key, extra=None):
    with st.container(border=True):
        st.toggle(f"**{fmt.md(title)}**", key=key)
        st.markdown(fmt.md(body))
        if extra:
            extra()


def render(ds, subs, base, current, changed):
    s = st.session_state
    st.altair_chart(chart.build(base, current, changed), width="stretch")
    st.caption("Your checking balance at the end of each day. Hover over the line or the dots for details."
               + (" The dashed line is before your what-ifs." if changed else ""))

    st.markdown("### Ways to fix it")
    fixes = {f.name: f for f in engine.available_fixes(engine.Scenario(refund_submit_date=s.wf_submit), ds,
                                                       engine.Ledger())}
    helpful = [x for x in subs if x.merchant in fixes and fixes[x.merchant].savings.value > 0]
    useless = [x for x in subs if x.merchant in fixes and fixes[x.merchant].savings.value <= 0]
    cols = st.columns(3)
    refund = fixes.get("refund released")
    if refund:
        with cols[0]:
            rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=s.wf_submit))
            held = next(r for r in ds.refunds if r.status == "HELD")

            def change_date():
                with st.expander("Change date"):
                    st.date_input("I'll send it on", key="wf_submit", min_value=config.DEMO_TODAY + timedelta(days=1),
                                  max_value=config.SEMESTER_END, format="MM/DD/YYYY")

            _card("Send the verification form to financial aid",
                  f"Releases your {fmt.money(held.amount)} refund around {fmt.day(rel)}. "
                  f"Adds {fmt.money(refund.savings.value)} before the semester ends.", "wf_refund", change_date)
    for sub in helpful[:1]:
        with cols[1]:
            _card(f"Cancel {sub.merchant}",
                  f"Saves {fmt.money(fixes[sub.merchant].savings.value)} before the semester ends.",
                  state.cancel_key(sub.merchant))
    with cols[2]:
        def pickers():
            a, b = st.columns([3, 2])
            a.date_input("Day", key="wf_shift_date", min_value=config.DEMO_TODAY + timedelta(days=1),
                         max_value=config.SEMESTER_END, format="MM/DD/YYYY")
            b.number_input("Hours", key="wf_shift_hours", min_value=0.5, max_value=12.0, step=0.5)
            sh = engine.ExtraShift(s.wf_shift_date, engine.Decimal(f"{s.wf_shift_hours:.1f}"))
            pay, added = engine.extra_shift_pay(sh, ds, state.choices())
            st.caption(fmt.md(f"Adds {fmt.money(added.value)} to your {fmt.day(pay)} paycheck."
                              if added.value > 0 else f"That shift is paid {fmt.day(pay)}, after the semester ends."))

        _card("Pick up an extra shift", "One more shift at the cafe.", "wf_shift_on", pickers)

    for sub in useless + helpful[1:]:
        f = fixes[sub.merchant]
        if f.savings.value > 0:
            st.checkbox(fmt.md(f"Also cancel {sub.merchant}: saves {fmt.money(f.savings.value)}"),
                        key=state.cancel_key(sub.merchant))
            continue
        with st.expander(f"Cancelling {sub.merchant} won't help this semester. Why?"):
            charge, paid = next(((c, p) for c, p in engine.subscription_timing(sub, ds) if c > config.DEMO_TODAY),
                                (None, None))
            st.markdown(fmt.md(f"{sub.merchant} is billed to your credit card. Its next charge ({fmt.day(charge)}) "
                               f"is on the card bill you pay on {fmt.day(paid)}, after the semester ends, so cancelling "
                               f"it saves {fmt.money(f.savings.value)} before then."))
    st.button("Start over", type="tertiary", icon=":material/restart_alt:", on_click=state.reset, args=(subs,),
              key="start_over")
