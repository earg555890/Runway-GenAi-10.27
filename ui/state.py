"""The student's what-if choices, kept in session state, turned into an engine.Scenario on every rerun. Also
what the student marked done in the check-in (kept for the session) and the log of Runway's actions."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import streamlit as st

import actions
import agent
import config
import engine
import mealplan
import normalize
from ui import fmt

MAX_TURNS = 10

FLIGHT = dict(label="Flight home for Thanksgiving", cost=400.0, date=date(2026, 11, 10))


def cancel_key(merchant):
    return f"wf_cancel_{merchant}"


def _defaults(subs):
    d = {
        "wf_refund": False,
        "wf_submit": config.DEMO_TODAY + timedelta(days=1),
        "wf_shifts": [],            # the shift planner: [{"date": date, "hours": float}]
        "wf_shift_date": saturday(0),
        "wf_shift_hours": 4.0,
        "buy_label": FLIGHT["label"],
        "buy_cost": FLIGHT["cost"],
        "buy_date": FLIGHT["date"],
        "buy_card": False,
        "buy_active": False,        # True once the student presses "Check": the purchase joins the plan
        "wf_budget": False,         # "Use my budget in my forecast"
        "wf_meal_moves": 0,         # dining-dollar meals a week moved to swipes (meal plan card)
    }
    d.update({cancel_key(s.merchant): False for s in subs})
    d.update({budget_key(c): 0 for c in normalize.FLEXIBLE})
    d.update({approved_key(o): False for o in OPP_IDS})
    return d


OPP_IDS = ("OPP-01", "OPP-02", "OPP-03", "OPP-04", "OPP-05", "OPP-06")


def approved_key(opp_id):
    return f"wf_approved_{opp_id}"


def approved():
    """Opportunities the student switched on as "if approved" what-ifs (never certain money)."""
    return tuple(o for o in OPP_IDS if st.session_state.get(approved_key(o)))


def budget_key(category):
    return f"bud_amt_{category}"


def budget():
    """{flexible category: whole dollars} the student set (all zero: no budget yet)."""
    return {c: int(st.session_state.get(budget_key(c)) or 0) for c in normalize.FLEXIBLE}


def has_budget():
    return any(budget().values())


def set_budget(amounts):
    for c in normalize.FLEXIBLE:
        st.session_state[budget_key(c)] = int(amounts.get(c, 0))


def budget_scenario_part():
    """The budget for the forecast, when the switch is on and a budget is set."""
    if st.session_state.get("wf_budget") and has_budget():
        return tuple((c, Decimal(v)) for c, v in budget().items())
    return ()


def init_mode():
    st.session_state.setdefault("data_mode", "maya")


def mine():
    """My data mode: the student's own bank file (private: no saved answers, no AI calls she didn't ask for)."""
    return st.session_state.get("data_mode") == "mine"


def switch_mode():
    """Changing between Maya and My data starts fresh: what-ifs, budget, done items and the chat."""
    s = st.session_state
    keep = s.get("data_mode")
    for k in [k for k in s.keys() if k.startswith(("wf_", "buy_", "bud_amt_", "ci_", "imp_", "meal_"))
              or k in ("done", "action_log", "prepared", "history", "bud_month", "bud_account", "bud_pick")]:
        del s[k]
    s.data_mode = keep


def fit_dates():
    """Keep the date pickers inside her dates (My data mode)."""
    s = st.session_state
    lo, hi = config.DEMO_TODAY + timedelta(days=1), config.SEMESTER_END
    for k in ("wf_submit", "wf_shift_date", "buy_date"):
        if k in s and not lo <= s[k] <= hi:
            s[k] = min(max(s[k], lo), hi)


def init(subs):
    for k, v in _defaults(subs).items():
        st.session_state.setdefault(k, v)
    st.session_state.setdefault("done", {})          # item kind -> {"label", "title", "fix"}
    st.session_state.setdefault("action_log", [])    # [{"when", "what", "kind"}]
    st.session_state.setdefault("prepared", [])      # what Runway has prepared and logged already
    meal_data()


def _apply_done():
    """Fixes marked done stay on in the what-if switches too."""
    s = st.session_state
    for d in s.done.values():
        if d["fix"] == ["refund"]:
            s.wf_refund, s.wf_submit = True, config.DEMO_TODAY
        elif d["fix"][:1] == ["cancel"]:
            s[cancel_key(d["fix"][1])] = True


def reset(subs):
    """Start over: the what-ifs go back to "nothing changes" (what was marked done and the budget amounts stay)."""
    keep = budget()
    for k, v in _defaults(subs).items():
        st.session_state[k] = v
    st.session_state.shift_msg = None
    set_budget(keep)
    _apply_done()


def log(what, kind="approved"):
    t = datetime.now()
    st.session_state.action_log.append({"when": f"{t:%I:%M:%S %p}".lstrip("0"), "what": what, "kind": kind})


def opened(kind, how, title, what):
    """She opened something Runway prepared (the email draft, a reminder, a cancel page): logged and remembered."""
    log(what)
    from ui import memory
    memory.intent(kind, how, title)


def _remember_shifts():
    from ui import memory
    memory.shifts(shifts())


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
    from ui import memory
    memory.done(item.kind, label, title)
    after = done_scenario(ds)
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
    from ui import memory
    memory.undone(kind, d["label"], d["title"])


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


def saturday(weeks_ahead=0):
    """This coming Saturday (after today), or one `weeks_ahead` later."""
    today = config.DEMO_TODAY
    return today + timedelta(days=(5 - today.weekday()) % 7 or 7, weeks=weeks_ahead)


def shifts():
    """The planned extra shifts (shift planner), merged by day, as engine.ExtraShift."""
    out = [engine.ExtraShift(x["date"], Decimal(f"{x['hours']:.1f}")) for x in st.session_state.get("wf_shifts") or []
           if config.DEMO_TODAY < x["date"] <= config.SEMESTER_END and x["hours"] > 0]
    return engine.merge_shifts(out)


def add_shift(day, hours):
    """Plan a shift (a button callback). A friendly message instead when the day or the hours don't work."""
    s = st.session_state
    s.shift_msg = None
    hours = float(hours or 0)
    planned = sum(x["hours"] for x in s.wf_shifts if x["date"] == day)
    if day <= config.DEMO_TODAY:
        s.shift_msg = "Pick a day after today."
    elif day > config.SEMESTER_END:
        s.shift_msg = f"Pick a day by {fmt.day(config.SEMESTER_END)}, when the semester ends."
    elif hours <= 0:
        s.shift_msg = "Pick how many hours."
    elif planned + hours > float(engine.MAX_SHIFT_HOURS):
        s.shift_msg = (f"That's more than {engine.MAX_SHIFT_HOURS:.0f} hours on {fmt.day(day)}. "
                       "Pick fewer hours.")
    else:
        s.wf_shifts = [*s.wf_shifts, {"date": day, "hours": hours}]
        _remember_shifts()


def add_typed_shift():
    add_shift(st.session_state.wf_shift_date, st.session_state.wf_shift_hours)


def add_shifts(items):
    """Shifts from a chat answer ([{"date": "YYYY-MM-DD", "hours": "4.00"}]) into the planner, skipping ones that
    are already there."""
    have = {(x["date"], x["hours"]) for x in st.session_state.wf_shifts}
    for x in items:
        d, h = date.fromisoformat(x["date"]), float(x["hours"])
        if (d, h) not in have:
            add_shift(d, h)


def remove_shift(day):
    st.session_state.wf_shifts = [x for x in st.session_state.wf_shifts if x["date"] != day]
    st.session_state.shift_msg = None
    _remember_shifts()


def reset_shifts():
    """Clears only the planned shifts ("Start over" clears everything)."""
    st.session_state.wf_shifts = []
    st.session_state.shift_msg = None
    _remember_shifts()


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
    """What the student decided that Runway can't suggest as a fix: the form date and the planned shifts."""
    return engine.Scenario(refund_submit_date=submit_date(), extra_shifts=shifts())


def done_cancels():
    return tuple(d["fix"][1] for d in st.session_state.get("done", {}).values() if d["fix"][:1] == ["cancel"])


def data_mode():
    return "mine" if mine() else "maya"


def meal_data():
    """Her meal plan settings and log for this mode (mealplan.py), loaded once per session."""
    s = st.session_state
    if "meal_data" not in s:
        s.meal_data = mealplan.load(data_mode())
    return s.meal_data


def meal_today(ds):
    """The meal log's "today": the demo's today for Maya; the real date in My data mode (inside her plan's dates)."""
    if not mine():
        return config.DEMO_TODAY
    t, plan = date.today(), mealplan.settings(meal_data(), ds)
    return min(max(t, plan.start), plan.end) if plan else t


def meal_part(ds):
    """Scenario fields for her meal plan and log (none in Maya's default state)."""
    return mealplan.scenario_part(meal_data(), ds, meal_today(ds)) if ds is not None else {}


def meal_log_label(meals, points):
    """The chat's button: "Log 2 meals", "Log $8.50 in points"."""
    what = [f"{meals} meal{'' if meals == 1 else 's'}" if meals else "",
            f"{fmt.dollars(points)} in points" if points else ""]
    return "Log " + " and ".join(x for x in what if x)


def log_meal_from_chat(offer, answer_key, ds=None):
    """Her tap on a chat answer's "Log 2 meals": the entry goes into her meal log (today) and is saved."""
    s, (meals, points) = st.session_state, offer
    day = meal_today(ds)
    problem = mealplan.add(meal_data(), day, meals=meals, points=points, ds=ds, today=day)
    if problem:
        s.meal_msg = problem
        return
    mealplan.save(data_mode(), s.meal_data)
    s.meal_msg = None
    s.meal_logged = set(s.get("meal_logged") or ()) | {answer_key}
    log(f"{meal_log_label(meals, points)}: logged from the chat", "meal")


def scenario(subs, ds=None):
    s, base = st.session_state, choices()
    p = purchase() if s.buy_active else None
    cancels = tuple(x.merchant for x in subs if s[cancel_key(x.merchant)])
    return engine.Scenario(
        refund_released=s.wf_refund or "refund" in s.done, refund_submit_date=submit_date(),
        cancel_subscriptions=tuple(dict.fromkeys(cancels + done_cancels())),
        extra_shifts=base.extra_shifts, purchases=(p,) if p else (), budget=budget_scenario_part(),
        approved=approved(), meal_moves=int(s.get("wf_meal_moves") or 0), **meal_part(ds))


def done_scenario(ds=None):
    """What the student has actually done (marked done in the check-in, her meal log), without the what-ifs being
    explored."""
    return engine.Scenario(refund_released="refund" in st.session_state.get("done", {}),
                           refund_submit_date=submit_date(), cancel_subscriptions=done_cancels(),
                           budget=budget_scenario_part(), **meal_part(ds))


def changed(sc):
    return bool(sc.refund_released or sc.cancel_subscriptions or sc.extra_shifts or sc.purchases or sc.budget
                or sc.approved or sc.meal_moves or sc.meal_settings or sc.meal_log or sc.meal_today)


def summary(sc):
    """The what-if in plain words, e.g. 'refund form sent Tue Oct 27, Spotify cancelled'."""
    parts = []
    if sc.refund_released:
        parts.append(f"verification form sent {fmt.day(sc.submit_date)}")
    parts += [f"{m} cancelled" for m in sc.cancel_subscriptions]
    parts += [f"extra shift {fmt.day(x.date)} ({x.hours} hours)" for x in sc.extra_shifts]
    parts += [f"{p.label} ({fmt.money(p.cost)}, {fmt.day(p.date)})" for p in sc.purchases]
    if sc.budget:
        parts.append("your budget")
    if sc.approved:
        parts.append(f"{len(sc.approved)} aid award{'s' if len(sc.approved) != 1 else ''} if approved")
    if sc.meal_moves:
        parts.append(f"{sc.meal_moves} meal{'s' if sc.meal_moves != 1 else ''} a week on swipes")
    if sc.meal_settings or sc.meal_log:
        parts.append("your meal plan")
    return ", ".join(parts)
