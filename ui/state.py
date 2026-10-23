"""What-if panel state. Session state holds the widget values; scenario() turns them into an engine.Scenario."""
from datetime import date, timedelta
from decimal import Decimal

import streamlit as st

import config
import engine

FLIGHT = dict(cost=400.0, date=date(2026, 11, 10), account="checking", label="Thanksgiving flight home")


def _defaults(subs):
    d = {
        "wf_refund": False,
        "wf_submit": config.DEMO_TODAY + timedelta(days=1),
        "wf_shifts": [],                              # [(date, hours str)]
        "wf_shift_date": config.DEMO_TODAY + timedelta(days=5),
        "wf_shift_hours": 4.0,
        "wf_buy_on": False,
        "wf_buy_cost": FLIGHT["cost"],
        "wf_buy_date": FLIGHT["date"],
        "wf_buy_account": FLIGHT["account"],
        "wf_buy_label": FLIGHT["label"],
    }
    d.update({cancel_key(s.merchant): False for s in subs})
    return d


def cancel_key(merchant):
    return f"wf_cancel_{merchant}"


def init(subs):
    for k, v in _defaults(subs).items():
        st.session_state.setdefault(k, list(v) if isinstance(v, list) else v)


def reset(subs):
    for k, v in _defaults(subs).items():
        st.session_state[k] = list(v) if isinstance(v, list) else v


def add_shift():
    d, hours = st.session_state.wf_shift_date, st.session_state.wf_shift_hours
    if d and hours > 0 and config.DEMO_TODAY < d <= config.SEMESTER_END:
        st.session_state.wf_shifts = st.session_state.wf_shifts + [(d, f"{hours:.1f}")]


def remove_shift(i):
    shifts = list(st.session_state.wf_shifts)
    shifts.pop(i)
    st.session_state.wf_shifts = shifts


def apply_fixes(fixes):
    for f in fixes:
        if f.kind == "refund":
            st.session_state.wf_refund = True
        else:
            st.session_state[cancel_key(f.name)] = True


def choices():
    """The student's own choices that are not fixes Runway can suggest (extra shifts)."""
    return engine.Scenario(refund_submit_date=st.session_state.wf_submit,
                           extra_shifts=tuple(engine.ExtraShift(d, Decimal(h)) for d, h in st.session_state.wf_shifts))


def purchase():
    s = st.session_state
    if not s.wf_buy_on or not s.wf_buy_cost or s.wf_buy_cost <= 0:
        return None
    return engine.Purchase(Decimal(f"{s.wf_buy_cost:.2f}"), s.wf_buy_date, s.wf_buy_account,
                           s.wf_buy_label.strip() or "purchase")


def scenario(subs):
    s = st.session_state
    base = choices()
    p = purchase()
    return engine.Scenario(
        refund_released=s.wf_refund,
        refund_submit_date=s.wf_submit,
        cancel_subscriptions=tuple(x.merchant for x in subs if s[cancel_key(x.merchant)]),
        extra_shifts=base.extra_shifts,
        purchases=(p,) if p else ())


def is_base(sc):
    """True when the scenario changes nothing (the submit date alone changes nothing)."""
    return not (sc.refund_released or sc.cancel_subscriptions or sc.extra_shifts or sc.purchases)
