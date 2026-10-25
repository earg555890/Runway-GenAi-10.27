"""The student's what-if choices, kept in session state, turned into an engine.Scenario on every rerun."""
from datetime import date, timedelta
from decimal import Decimal

import streamlit as st

import config
import engine
from ui import fmt

FLIGHT = dict(label="Flight home for Thanksgiving", cost=400.0, date=date(2026, 11, 10))


def cancel_key(merchant):
    return f"wf_cancel_{merchant}"


def _defaults(subs):
    d = {
        "wf_refund": False,
        "wf_submit": config.DEMO_TODAY + timedelta(days=1),
        "wf_shift_on": False,
        "wf_shift_date": date(2026, 11, 4),
        "wf_shift_hours": 4.0,
        "buy_label": FLIGHT["label"],
        "buy_cost": FLIGHT["cost"],
        "buy_date": FLIGHT["date"],
        "buy_card": False,
        "buy_active": False,        # True once the student presses "Check": the purchase joins the plan
    }
    d.update({cancel_key(s.merchant): False for s in subs})
    return d


def init(subs):
    for k, v in _defaults(subs).items():
        st.session_state.setdefault(k, v)


def reset(subs):
    for k, v in _defaults(subs).items():
        st.session_state[k] = v


def apply_fixes(fixes):
    for f in fixes:
        if f.kind == "refund":
            st.session_state.wf_refund = True
        else:
            st.session_state[cancel_key(f.name)] = True


def check_purchase():
    st.session_state.buy_active = True


def drop_purchase():
    st.session_state.buy_active = False


def shift():
    s = st.session_state
    if s.wf_shift_on and s.wf_shift_hours > 0 and config.DEMO_TODAY < s.wf_shift_date <= config.SEMESTER_END:
        return engine.ExtraShift(s.wf_shift_date, Decimal(f"{s.wf_shift_hours:.1f}"))
    return None


def purchase():
    """The purchase in the 'Can I afford it?' fields (or None if the amount is not positive)."""
    s = st.session_state
    if not s.buy_cost or s.buy_cost <= 0 or not config.DEMO_TODAY < s.buy_date <= config.SEMESTER_END:
        return None
    return engine.Purchase(Decimal(f"{s.buy_cost:.2f}"), s.buy_date, "card" if s.buy_card else "checking",
                           s.buy_label.strip() or "this purchase")


def choices():
    """What the student decided that Runway can't suggest as a fix: the form date and an extra shift."""
    sh = shift()
    return engine.Scenario(refund_submit_date=st.session_state.wf_submit, extra_shifts=(sh,) if sh else ())


def scenario(subs):
    s, base = st.session_state, choices()
    p = purchase() if s.buy_active else None
    return engine.Scenario(
        refund_released=s.wf_refund, refund_submit_date=s.wf_submit,
        cancel_subscriptions=tuple(x.merchant for x in subs if s[cancel_key(x.merchant)]),
        extra_shifts=base.extra_shifts, purchases=(p,) if p else ())


def done_scenario():
    """What the student has actually done (marked done in the check-in), without the what-ifs being explored."""
    return engine.Scenario(refund_submit_date=st.session_state.wf_submit)


def changed(sc):
    return bool(sc.refund_released or sc.cancel_subscriptions or sc.extra_shifts or sc.purchases)


def summary(sc):
    """The what-if in plain words, e.g. 'refund form sent Tue Oct 27, Spotify cancelled'."""
    parts = []
    if sc.refund_released:
        parts.append(f"verification form sent {fmt.day(sc.submit_date)}")
    parts += [f"{m} cancelled" for m in sc.cancel_subscriptions]
    parts += [f"extra shift {fmt.day(x.date)} ({x.hours} hours)" for x in sc.extra_shifts]
    parts += [f"{p.label} ({fmt.money(p.cost)}, {fmt.day(p.date)})" for p in sc.purchases]
    return ", ".join(parts)
