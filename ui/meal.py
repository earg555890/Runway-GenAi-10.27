"""The meal plan card (Semester tab): meals and points left, one-tap logging, her recent entries, and her plan's
settings. The settings and log are kept on this computer (mealplan.py); the engine does every number (rule 2)."""
from datetime import date

import streamlit as st

import config
import engine
import mealplan
from ui import fmt, state

PER = {"day": "Per day", "week": "Per week", "semester": "Per semester"}
PERIOD = {"day": "today", "week": "this week", "semester": "this semester"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _meals(x):
    """Meals in words: whole meals ("about 40" when the engine's value has a fraction)."""
    return f"{x:.0f}"


def _points(x):
    return fmt.dollars(x)


def _amount(a, x):
    return _points(x) if a.kind == "points" else _meals(x)


def counter_lines(a, end):
    """(the big number, its period, the run-out or reset line, the "use them or lose them" line or "") for one
    allowance, all from the engine's records."""
    left = a.left.value
    big = _amount(a, max(left, 0))
    period = PERIOD[a.per]
    word = "points" if a.kind == "points" else "meals"
    if left < 0:
        over = _amount(a, -left)
        line = f"You've used {over} more than your plan {period}."
    elif a.per == "semester":
        line = (f"At this pace, they run out around {fmt.day(a.runs_out.value)}." if a.runs_out.value else
                "At this pace, they last the semester.")
    else:
        line = f"Resets {fmt.day(a.resets.value)}." if a.resets else f"Your plan ends {fmt.day(end)}."
        n, of = a.short_periods.value, a.periods_left.value
        if n and n == of:
            line += f" At your pace, you run short every {a.per}."
        elif n:
            line += f" At your pace, you run short {n} of {of} {a.per}s."
    lose = ""
    if a.unused_period is not None and a.unused_period.value >= (1 if a.kind == "meals" else 1):
        lose = (f"Use them or lose them: about {_amount(a, a.unused_period.value)} {word} left when "
                f"{period} ends.")
    elif a.per == "semester" and a.unused_end.value >= 1:
        lose = f"Use them or lose them: about {_amount(a, a.unused_end.value)} {word} left on {fmt.day(end)}."
    return big, period, line, lose


def _counter(title, a, end):
    big, period, line, lose = counter_lines(a, end)
    return (f'<div class="rw-meal-box"><div class="rw-meal-label">{fmt.html(title)}</div>'
            f'<div class="rw-meal-num">{fmt.html(big)}</div><div class="rw-meal-period">{fmt.html(period)}</div>'
            f'<div class="rw-meal-line">{fmt.html(line)}</div>'
            + (f'<div class="rw-meal-lose">{fmt.html(lose)}</div>' if lose else "") + "</div>")


def entry_words(e):
    parts = [fmt.day(date.fromisoformat(e["date"]))]
    if e["meals"]:
        parts.append(_plural(e["meals"], "meal"))
    if float(e["points"]):
        parts.append(f"{fmt.dollars(engine.D(e['points']))} points")
    if e.get("note"):
        parts.append(e["note"])
    return " · ".join(parts)


# --- callbacks (each saves to this computer right away) ------------------------------------------------------------
def _store(msg=None):
    s = st.session_state
    mealplan.save(state.data_mode(), s.meal_data)
    s.meal_msg = msg


def _plus(ds):
    s = st.session_state
    _store(mealplan.add_meal(s.meal_data, state.meal_today(ds), ds=ds, today=state.meal_today(ds)))


def _minus(ds):
    s = st.session_state
    ok = mealplan.undo_meal(s.meal_data, state.meal_today(ds))
    _store(None if ok else "No meals logged today.")


def _log_points(ds):
    s = st.session_state
    pts = s.get("meal_points_in")
    problem = mealplan.add(s.meal_data, state.meal_today(ds), points=pts or 0, ds=ds, today=state.meal_today(ds))
    if not problem:
        s.meal_points_in = None
    _store(problem)


def _log_other(ds):
    s = st.session_state
    problem = mealplan.add(s.meal_data, s.meal_other_date, meals=s.meal_other_meals or 0,
                           points=s.meal_other_points or 0, note=s.meal_other_note or "", ds=ds,
                           today=state.meal_today(ds))
    if not problem:
        s.meal_other_meals, s.meal_other_points, s.meal_other_note = 0, None, ""
    _store(problem)


def _remove(entry_id):
    mealplan.remove(st.session_state.meal_data, entry_id)
    _store()


def _save_settings(ds):
    s = st.session_state
    f = {"meals": s.meal_set_meals, "meals_per": s.meal_set_meals_per, "points": s.meal_set_points,
         "points_per": s.meal_set_points_per, "start": s.meal_set_start, "end": s.meal_set_end,
         "week_starts": WEEKDAYS.index(s.meal_set_reset)}
    problem = engine.meal_settings_problem(int(f["meals"] or 0), f["meals_per"], engine.D(f["points"] or 0),
                                           f["points_per"], f["start"], f["end"], f["week_starts"])
    if problem:
        _store(problem)
        return
    plan = engine.MealSettings(int(f["meals"] or 0), f["meals_per"], engine.D(f["points"] or 0), f["points_per"],
                               f["start"], f["end"], f["week_starts"], bool(s.meal_set_rolls))
    mealplan.set_settings(s.meal_data, plan)
    _store("Saved.")
    _remember(plan)


def _reset(ds):
    s = st.session_state
    s.meal_data = mealplan.empty()
    _store("Back to your school's plan." if ds.meal_plan else "Cleared.")
    _forms(ds, force=True)
    plan = engine.default_meal_settings(ds)
    if plan:
        _remember(plan)


def _remember(plan):
    from ui import memory
    memory.meal_plan(mealplan.memory_text(plan, fmt.dollars))


def _forms(ds, force=False):
    """The settings form starts from her plan (or a typical week plan in My data mode). A new plan of her own starts
    today (only what she uses from then on counts; she can set an earlier start to count her history); a plan she
    saved keeps its start."""
    s = st.session_state
    plan = mealplan.settings(s.meal_data, ds)
    vals = {"meal_set_meals": plan.meals if plan else 14, "meal_set_meals_per": plan.meals_per if plan else "week",
            "meal_set_points": float(plan.points) if plan else 0.0,
            "meal_set_points_per": plan.points_per if plan else "semester",
            "meal_set_start": plan.start if s.meal_data.get("settings") and plan else state.meal_today(ds),
            "meal_set_end": plan.end if plan else config.SEMESTER_END,
            "meal_set_reset": WEEKDAYS[plan.week_starts if plan else 0],
            "meal_set_rolls": plan.rolls_over if plan else False}
    for k, v in vals.items():
        if force:
            s[k] = v
        else:
            s.setdefault(k, v)


# --- the card ----------------------------------------------------------------------------------------------------
def card(ds, scenario):
    s = st.session_state
    _forms(ds)
    plan = mealplan.settings(s.meal_data, ds)
    with st.container(border=True, key="meal_card"):
        st.markdown("**:material/restaurant: Meal plan**")
        if not plan:
            st.markdown("Add your meal plan to count your meals and points.")
            _settings(ds, expanded=True)
            _message()
            return
        m = engine.meal_plan_status(scenario, ds, engine.Ledger(), detail=True)
        end = min(plan.end, config.SEMESTER_END)
        with st.container(key="meal_counters"):
            st.markdown('<div class="rw-meal-row">' + _counter("Meals left", m.meals, end)
                        + _counter("Points left", m.points, end) + "</div>", unsafe_allow_html=True)
        _logging(ds)
        if m.c["cost"].value:
            st.markdown(fmt.md(f"At this pace, you'd pay **about {fmt.dollars(m.c['cost'].value)} for meals** from "
                               "checking (estimated)."))
        elif m.cost_unknown:
            st.caption("Log a meal you paid for with points, and PocketMoney can estimate what extra meals cost.")
        elif m.pooled and m.runs_out and m.tip_works and not s.get("wf_meal_moves"):
            st.caption(fmt.md("Tip: use 2 swipes a week instead of dining dollars, and both last."))
        if m.pooled:                                 # the what-if: meals a week paid with swipes, not points
            st.slider("Points meals a week moved to swipes", min_value=0, max_value=5, key="wf_meal_moves",
                      help="Each move uses a swipe instead of points.")
        _recent()
        _message()
        _other_day(ds)
        _settings(ds)


def _logging(ds):
    s = st.session_state
    today = state.meal_today(ds)
    n = mealplan.meals_on(s.meal_data, today)
    with st.container(horizontal=True, vertical_alignment="center", key="meal_log_row", gap="small"):
        st.button("", key="meal_minus", icon=":material/remove:", on_click=_minus, args=(ds,),
                  help="Undo one meal today", disabled=not n)
        st.markdown(f'<div class="rw-meal-today"><b>{n}</b> {"meal" if n == 1 else "meals"} today</div>',
                    unsafe_allow_html=True)
        st.button("", key="meal_plus", icon=":material/add:", on_click=_plus, args=(ds,), type="primary",
                  help="Log one meal today")
    with st.form("meal_points_form", border=False, enter_to_submit=True):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small", key="meal_points_row"):
            st.number_input("Points used ($)", key="meal_points_in", min_value=0.0, max_value=200.0, step=1.0,
                            value=None, placeholder="0.00", format="%.2f")
            st.form_submit_button("Log", on_click=_log_points, args=(ds,))


def _other_day(ds):
    s = st.session_state
    with st.expander("Log another day"):
        today = state.meal_today(ds)
        plan = mealplan.settings(s.meal_data, ds)
        lo = plan.start if plan else config.SEMESTER_START
        s.setdefault("meal_other_date", today)
        with st.form("meal_other_form", border=False):
            st.date_input("Day", key="meal_other_date", min_value=min(lo, today), max_value=today,
                          format="MM/DD/YYYY")
            a, b = st.columns(2)
            a.number_input("Meals", key="meal_other_meals", min_value=0, max_value=engine.MAX_MEALS_ENTRY, step=1)
            b.number_input("Points ($)", key="meal_other_points", min_value=0.0,
                           max_value=float(engine.MAX_POINTS_ENTRY), step=1.0, value=None, placeholder="0.00",
                           format="%.2f")
            st.text_input("Note (optional)", key="meal_other_note", max_chars=80)
            st.form_submit_button("Log", on_click=_log_other, args=(ds,))


def _recent():
    log = st.session_state.meal_data["log"]
    if not log:
        return
    st.markdown('<div class="rw-meal-recent">Recent</div>', unsafe_allow_html=True)
    for e in list(reversed(log))[:5]:
        left, right = st.columns([8, 1], vertical_alignment="center")
        left.markdown(fmt.md(entry_words(e)))
        right.button("", key=f"meal_rm_{e['id']}", icon=":material/close:", type="tertiary", help="Remove this",
                     on_click=_remove, args=(e["id"],))


def _message():
    msg = st.session_state.get("meal_msg")
    if msg:
        st.caption(f":material/info: {msg}")


def _settings(ds, expanded=False):
    s = st.session_state
    with st.expander("Edit my meal plan", expanded=expanded):
        with st.form("meal_settings_form", border=False):
            a, b = st.columns(2)
            a.number_input("Meals", key="meal_set_meals", min_value=0, max_value=engine.MAX_PLAN_MEALS, step=1)
            b.selectbox("How often", list(PER), key="meal_set_meals_per", format_func=PER.get)
            a, b = st.columns(2)
            a.number_input("Points ($)", key="meal_set_points", min_value=0.0, max_value=float(engine.MAX_PLAN_POINTS),
                           step=10.0, format="%.2f")
            b.selectbox("How often", list(PER), key="meal_set_points_per", format_func=PER.get)
            st.checkbox("Unused meals and points roll over", key="meal_set_rolls",
                        help="Only for per-day and per-week amounts.")
            st.selectbox("My week starts on", WEEKDAYS, key="meal_set_reset")
            a, b = st.columns(2)
            a.date_input("Plan starts", key="meal_set_start", format="MM/DD/YYYY")
            b.date_input("Plan ends", key="meal_set_end", format="MM/DD/YYYY")
            st.form_submit_button("Save", type="primary", on_click=_save_settings, args=(ds,))
        if s.meal_data.get("settings") or s.meal_data["log"]:
            st.button("Reset to my school's plan" if ds.meal_plan else "Clear my meal plan", key="meal_reset",
                      type="tertiary", icon=":material/restart_alt:", on_click=_reset, args=(ds,))
