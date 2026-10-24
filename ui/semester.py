"""Tab 1, "My semester": the big number, the balance chart, and up to three ways to fix it."""
from datetime import timedelta

import streamlit as st

import config
import engine
from ui import chart, fmt, state


def _card(title, sentence, key, more=None, more_label="Change"):
    """A fix card: a toggle with the title, one sentence, and any detail behind "Change"."""
    with st.container(border=True):
        st.toggle(f"**{fmt.md(title)}**", key=key)
        st.markdown(fmt.md(sentence))
        if more:
            with st.expander(more_label):
                more()


def _figure(label, value, when, delta):
    tone = "rw-red" if value < 0 else "rw-green"
    chip = ""
    if delta is not None and delta.value != 0:
        chip = (f' <span class="rw-delta {"rw-up" if delta.value > 0 else "rw-down"}">'
                f'{fmt.html(fmt.change(delta.value))}</span>')
    return (f'<div class="rw-fig"><div class="rw-fig-label">{label}</div>'
            f'<div class="rw-fig-value {tone}">{fmt.html(fmt.balance(value))}{chip}</div>'
            + (f'<div class="rw-fig-when">{fmt.html(when)}</div>' if when else "") + "</div>")


def money_strip(current, deltas):
    """The big number (checking today), then two smaller figures for the current what-ifs."""
    d = deltas or {}
    big, low, end = st.columns([4, 3, 3], vertical_alignment="top")
    big.markdown(f'<div class="rw-today">{fmt.html(fmt.dollars(current.start_balance.value))}</div>'
                 '<div class="rw-today-cap">in your checking account today</div>', unsafe_allow_html=True)
    low.markdown(_figure("Lowest point", current.lowest.value, fmt.day(current.lowest_date.value), d.get("lowest")),
                 unsafe_allow_html=True)
    end.markdown(_figure("End of semester", current.end_balance.value, fmt.day(config.SEMESTER_END),
                         d.get("end_balance")), unsafe_allow_html=True)


def render(ds, subs, base, current, changed, deltas=None):
    s = st.session_state
    money_strip(current, deltas)
    st.altair_chart(chart.build(base, current, changed), width="stretch")
    st.caption("Your balance at the end of each day. Hover for details."
               + (" The dashed line is before your changes." if changed else ""))

    st.markdown("### Ways to fix it")
    fixes = {f.name: f for f in engine.available_fixes(engine.Scenario(refund_submit_date=s.wf_submit), ds,
                                                       engine.Ledger())}
    helpful = [x for x in subs if x.merchant in fixes and fixes[x.merchant].savings.value > 0]
    useless = [x for x in subs if x.merchant in fixes and fixes[x.merchant].savings.value <= 0]
    cols = st.columns(3)
    if fixes.get("refund released"):
        with cols[0]:
            rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=s.wf_submit))
            held = next(r for r in ds.refunds if r.status == "HELD")

            def change_date():
                st.date_input("I'll send it on", key="wf_submit", min_value=config.DEMO_TODAY + timedelta(days=1),
                              max_value=config.SEMESTER_END, format="MM/DD/YYYY")

            _card("Send the verification form", f"Releases your {fmt.dollars(held.amount)} refund around "
                  f"{fmt.day(rel)}.", "wf_refund", change_date, "Change date")
    for sub in helpful[:1]:
        with cols[1]:
            _card(f"Cancel {sub.merchant}", f"Saves {fmt.dollars(fixes[sub.merchant].savings.value)} this semester.",
                  state.cancel_key(sub.merchant))
    with cols[2]:
        sh = engine.ExtraShift(s.wf_shift_date, engine.Decimal(f"{s.wf_shift_hours:.1f}"))
        pay, added = engine.extra_shift_pay(sh, ds, state.choices())

        def pickers():
            a, b = st.columns([3, 2])
            a.date_input("Day", key="wf_shift_date", min_value=config.DEMO_TODAY + timedelta(days=1),
                         max_value=config.SEMESTER_END, format="MM/DD/YYYY")
            b.number_input("Hours", key="wf_shift_hours", min_value=0.5, max_value=12.0, step=0.5)

        _card("Pick up an extra shift",
              f"Adds {fmt.dollars(added.value)} to your {fmt.day(pay)} paycheck." if added.value > 0 else
              f"That shift is paid {fmt.day(pay)}, after the semester.", "wf_shift_on", pickers)

    for sub in useless + helpful[1:]:
        f = fixes[sub.merchant]
        if f.savings.value > 0:
            st.checkbox(fmt.md(f"Also cancel {sub.merchant}: saves {fmt.dollars(f.savings.value)}"),
                        key=state.cancel_key(sub.merchant))
            continue
        with st.expander(f"Cancelling {sub.merchant} won't help this semester. Why?"):
            charge, paid = next(((c, p) for c, p in engine.subscription_timing(sub, ds) if c > config.DEMO_TODAY),
                                (None, None))
            st.markdown(fmt.md(f"- {sub.merchant} is billed to your credit card.\n"
                               f"- Its next charge is {fmt.day(charge)}.\n"
                               f"- You pay that card bill on {fmt.day(paid)}, after the semester.\n"
                               f"- So cancelling saves {fmt.money(f.savings.value)} this semester."))
    st.button("Start over", type="tertiary", icon=":material/restart_alt:", on_click=state.reset, args=(subs,),
              key="start_over")
