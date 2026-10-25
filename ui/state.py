"""The student's what-if choices, kept in session state, turned into an engine.Scenario on every rerun. Also
what the student marked done in the check-in (kept for the session) and the log of Runway's actions."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import streamlit as st

import actions
import agent
import config
import engine
from ui import fmt

MAX_TURNS = 10

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
    st.session_state.setdefault("done", {})          # item kind -> {"label", "title", "fix"}
    st.session_state.setdefault("action_log", [])    # [{"when", "what", "kind"}]
    st.session_state.setdefault("prepared", [])      # what Runway has prepared and logged already


def _apply_done():
    """Fixes marked done stay on in the what-if switches too."""
    s = st.session_state
    for d in s.done.values():
        if d["fix"] == ["refund"]:
            s.wf_refund, s.wf_submit = True, config.DEMO_TODAY
        elif d["fix"][:1] == ["cancel"]:
            s[cancel_key(d["fix"][1])] = True


def reset(subs):
    """Start over: the what-ifs go back to "nothing changes" (what was marked done stays done)."""
    for k, v in _defaults(subs).items():
        st.session_state[k] = v
    _apply_done()


def log(what, kind="approved"):
    t = datetime.now()
    st.session_state.action_log.append({"when": f"{t:%I:%M:%S %p}".lstrip("0"), "what": what, "kind": kind})


def prepared(key, what):
    """Log once that Runway prepared something (a draft, a reminder, a link) for the student to approve."""
    if key not in st.session_state.prepared:
        st.session_state.prepared.append(key)
        log(what, "prepared")


def mark_done(item, ds):
    """The student marks an item done: fixes turn on in the forecast (the form counts as sent today), the
    check-in drops it, and Runway says what changed in the chat."""
    s = st.session_state
    label, title = actions.done_label(item), actions.text(item)[0]
    s.done[item.kind] = {"label": label, "title": title, "fix": list(item.fix)}
    _apply_done()
    log(f"Marked done: {label} ({title})", "done")
    after = done_scenario()
    remaining = len([i for i in engine.attention_items(after, ds) if i.kind not in s.done])
    s.history = ([agent.event_answer(actions.done_message(item, ds, after, remaining))]
                 + s.get("history", []))[:MAX_TURNS]


def undo(kind):
    s = st.session_state
    d = s.done.pop(kind, None)
    if not d:
        return
    if d["fix"] == ["refund"]:
        s.wf_refund, s.wf_submit = False, config.DEMO_TODAY + timedelta(days=1)
    elif d["fix"][:1] == ["cancel"]:
        s[cancel_key(d["fix"][1])] = False
    log(f"Undone: {d['label']} ({d['title']})", "undone")


def is_done(fix):
    return any(d["fix"] == list(fix) for d in st.session_state.get("done", {}).values())


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


def submit_date():
    """When the form is (or would be) sent: today once it's marked sent, else the date picked."""
    s = st.session_state
    return config.DEMO_TODAY if "refund" in s.get("done", {}) else s.wf_submit


def choices():
    """What the student decided that Runway can't suggest as a fix: the form date and an extra shift."""
    sh = shift()
    return engine.Scenario(refund_submit_date=submit_date(), extra_shifts=(sh,) if sh else ())


def done_cancels():
    return tuple(d["fix"][1] for d in st.session_state.get("done", {}).values() if d["fix"][:1] == ["cancel"])


def scenario(subs):
    s, base = st.session_state, choices()
    p = purchase() if s.buy_active else None
    cancels = tuple(x.merchant for x in subs if s[cancel_key(x.merchant)])
    return engine.Scenario(
        refund_released=s.wf_refund or "refund" in s.done, refund_submit_date=submit_date(),
        cancel_subscriptions=tuple(dict.fromkeys(cancels + done_cancels())),
        extra_shifts=base.extra_shifts, purchases=(p,) if p else ())


def done_scenario():
    """What the student has actually done (marked done in the check-in), without the what-ifs being explored."""
    return engine.Scenario(refund_released="refund" in st.session_state.get("done", {}),
                           refund_submit_date=submit_date(), cancel_subscriptions=done_cancels())


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
