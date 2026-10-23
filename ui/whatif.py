"""What-if panel. Every change reruns the engine (milliseconds); nothing here does money math."""
from datetime import timedelta

import streamlit as st

import config
import engine
from ui import fmt, state


def _fix_line(f, ds, submit):
    if f.kind == "refund":
        rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=submit))
        return f"Submit the verification form: your {fmt.money(f.savings.value)} refund arrives {fmt.day(rel)}"
    return f"Cancel {f.name}: saves {fmt.money(f.savings.value)} before {fmt.day(config.SEMESTER_END)}"


def verdict(ds):
    """can_afford for the purchase, against the student's choices without any fixes (or None)."""
    p = state.purchase()
    if not p:
        return None
    return engine.can_afford(p.cost, p.date, p.account, state.choices(), ds, p.label)


def _show_verdict(a, current, ds):
    p, s = a.purchase, st.session_state
    what = f"**{p.label}**, {fmt.money(p.cost)} on {fmt.day(p.date)} ({'debit card' if p.account == 'checking' else 'credit card'})"
    if a.verdict == "yes":
        st.success(f"**Yes**, you can afford {what}. Lowest balance {fmt.money(a.without_fixes.lowest.value)} on "
                   f"{fmt.day(a.without_fixes.lowest_date.value)}.")
        return
    if a.verdict == "no":
        st.error(f"**No.** With {what}, checking goes below $0 even with every fix: lowest "
                 f"{fmt.money(a.with_fixes.lowest.value)} on {fmt.day(a.with_fixes.lowest_date.value)}.")
        return
    lines = "\n".join(f"- {_fix_line(f, ds, s.wf_submit)}" for f in a.fixes)
    zero = [f for f in a.considered if f.savings.value <= 0]
    st.warning(f"**Yes, if** you make these changes. Without them, {what} takes checking to "
               f"{fmt.money(a.without_fixes.lowest.value)} on {fmt.day(a.without_fixes.lowest_date.value)}.\n\n{lines}"
               + (f"\n\nNot useful before {fmt.day(config.SEMESTER_END)}: "
                  + ", ".join(f"cancelling {f.name} (saves {fmt.money(f.savings.value)})" for f in zero) if zero else ""))
    applied = all(s.wf_refund if f.kind == "refund" else s[state.cancel_key(f.name)] for f in a.fixes)
    if applied:
        st.success(f"**Resolved.** With these changes your lowest balance is {fmt.money(current.lowest.value)} on "
                   f"{fmt.day(current.lowest_date.value)}.")
    else:
        st.button("Apply these fixes", type="primary", on_click=state.apply_fixes, args=(a.fixes,), key="wf_apply")


def render(ds, subs, current):
    st.subheader("What if...")
    s = st.session_state
    fixes = {f.name: f for f in engine.available_fixes(engine.Scenario(refund_submit_date=s.wf_submit), ds,
                                                       engine.Ledger())}
    refund = next((r for r in ds.refunds if r.status == "HELD"), None)
    if refund:
        st.toggle("Submit the verification form", key="wf_refund")
        st.date_input("Submitted on", key="wf_submit", min_value=config.DEMO_TODAY + timedelta(days=1),
                      max_value=config.SEMESTER_END, format="MM/DD/YYYY")
        rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=s.wf_submit))
        st.caption(f"Your {fmt.money(refund.amount)} refund would arrive {fmt.day_year(rel)} "
                   f"({refund.release_business_days} business days after the hold clears).")

    st.markdown("**Subscriptions**")
    for sub in subs:
        f = fixes.get(sub.merchant)
        saves = f.savings.value if f else 0
        st.checkbox(f"Cancel {sub.merchant} - saves {fmt.money(saves)} before {fmt.day(config.SEMESTER_END)}",
                    key=state.cancel_key(sub.merchant))
        if f and saves <= 0:
            charge, paid = next(((c, p) for c, p in engine.subscription_timing(sub, ds) if c > config.DEMO_TODAY),
                                (None, None))
            if charge:
                st.caption(f"Why $0: its next charge ({fmt.day(charge)}) goes on the credit card, and that card bill "
                           f"is paid from checking on {fmt.day_year(paid)}, after the semester ends.")

    st.markdown("**Extra shifts**")
    c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
    c1.date_input("Date", key="wf_shift_date", min_value=config.DEMO_TODAY + timedelta(days=1),
                  max_value=config.SEMESTER_END, format="MM/DD/YYYY")
    c2.number_input("Hours", key="wf_shift_hours", min_value=0.5, max_value=12.0, step=0.5)
    c3.button("Add shift", on_click=state.add_shift, key="wf_add_shift")
    for i, (d, h) in enumerate(s.wf_shifts):
        r1, r2 = st.columns([5, 2], vertical_alignment="center")
        r1.markdown(f"{fmt.day(d)}: {h} hours")
        r2.button("Remove", key=f"wf_rm_{i}", on_click=state.remove_shift, args=(i,))

    st.markdown("**A purchase**")
    st.toggle("Include this purchase", key="wf_buy_on")
    c1, c2 = st.columns(2)
    c1.number_input("Amount ($)", key="wf_buy_cost", min_value=0.0, step=10.0, format="%.2f")
    c2.date_input("Date", key="wf_buy_date", min_value=config.DEMO_TODAY + timedelta(days=1),
                  max_value=config.SEMESTER_END, format="MM/DD/YYYY")
    st.radio("Pay with", ["checking", "card"], key="wf_buy_account", horizontal=True,
             format_func=lambda a: "Debit card (checking)" if a == "checking" else "Credit card")
    st.text_input("What is it?", key="wf_buy_label")
    a = verdict(ds)
    if a:
        _show_verdict(a, current, ds)

    st.button("Reset to \"nothing changes\"", on_click=state.reset, args=(subs,), key="wf_reset")
    return a
