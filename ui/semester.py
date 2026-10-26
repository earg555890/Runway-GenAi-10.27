"""Tab 1, "Semester": the big number, the balance chart, and up to three ways to fix it."""
from datetime import timedelta

import streamlit as st

import config
import engine
from ui import chart, fmt, state


def _card(title, sentence, key, more=None, more_label="Change", done=False):
    """A fix card: a toggle with the title, one sentence, and any detail behind "Change". Done (marked in the
    check-in): the switch stays on and locked."""
    with st.container(border=True):
        st.toggle(f"**{fmt.md(title)}**", key=key, disabled=done)
        st.markdown(fmt.md(sentence))
        if done:
            st.caption("Done. You marked this in your check-in.")
        elif more:
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
    if changed:
        with_cls = "rw-sw-with rw-sw-good" if current.lasts_through_semester else "rw-sw-with"   # matches the line
        st.markdown('<div class="rw-legend"><span class="rw-sw rw-sw-before"></span>Before your changes'
                    f'<span class="rw-sw {with_cls}"></span>With your changes</div>', unsafe_allow_html=True)
    st.altair_chart(chart.build(base, current, changed), width="stretch")
    st.caption("Your balance at the end of each day. Hover for details.")

    st.markdown("### Ways to fix it")
    fixes = {f.name: f for f in engine.available_fixes(engine.Scenario(refund_submit_date=s.wf_submit), ds,
                                                       engine.Ledger())}
    helpful = [x for x in subs if x.merchant in fixes and fixes[x.merchant].savings.value > 0]
    useless = [x for x in subs if x.merchant in fixes and fixes[x.merchant].savings.value <= 0]
    cols = st.columns(2)
    if fixes.get("refund released"):
        with cols[0]:
            rel = engine.refund_release_date(ds, engine.Scenario(refund_submit_date=s.wf_submit))
            held = next(r for r in ds.refunds if r.status == "HELD")

            def change_date():
                st.date_input("I'll send it on", key="wf_submit", min_value=config.DEMO_TODAY,
                              max_value=config.SEMESTER_END, format="MM/DD/YYYY")

            _card("Send the verification form", f"Releases your {fmt.dollars(held.amount)} refund around "
                  f"{fmt.day(rel)}.", "wf_refund", change_date, "Change date", done=state.is_done(("refund",)))
    for sub in helpful[:1]:
        with cols[1]:
            _card(f"Cancel {sub.merchant}", f"Saves {fmt.dollars(fixes[sub.merchant].savings.value)} this semester.",
                  state.cancel_key(sub.merchant), done=state.is_done(("cancel", sub.merchant)))
    _rest(ds, subs, fixes, helpful, useless)


def _rest(ds, subs, fixes, helpful, useless):
    shift_planner(ds, subs)
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
    meal_card(ds)
    st.button("Start over", type="tertiary", icon=":material/restart_alt:", on_click=state.reset, args=(subs,),
              key="start_over")


def hours_words(h):
    return f"{float(h):g} hour{'s' if float(h) != 1 else ''}"


def timing_words(p, run_out):
    if p.timing == "after_semester":
        return f"Paid {fmt.day(p.pay_date)}, after the semester."
    if p.timing == "late":
        return f"Paid {fmt.day(p.pay_date)}, after you run out."
    return f"Paid {fmt.day(p.pay_date)}, in time." if run_out else f"Paid {fmt.day(p.pay_date)}."


def plan_sentence(plan):
    """"These 3 shifts add $172 and your money lasts until Mon, Nov 16 (7 days longer)." All values from the
    engine's shift plan."""
    n = len(plan.shifts)
    lead = f"This shift adds {fmt.dollars(plan.total.value)}" if n == 1 else \
        f"These {n} shifts add {fmt.dollars(plan.total.value)}"
    after, longer = plan.after, plan.days_longer
    if after.lasts_through_semester:
        return f"{lead} and you're covered all semester."
    if longer is not None and longer.value > 0:
        return (f"{lead} and your money lasts until {fmt.day(after.first_below_zero.value)} "
                f"({longer.value} day{'s' if longer.value != 1 else ''} longer).")
    return f"{lead}, but your money still runs out on {fmt.day(after.first_below_zero.value)}."


def shift_planner(ds, subs):
    """Try shifts she's thinking of taking: each one's pay and payday, the total, and how much longer the money
    lasts. The planned shifts are in the forecast (status card, chart, check-in) like the other what-ifs."""
    s = st.session_state
    with st.container(border=True, key="shift_planner"):
        st.markdown("**:material/schedule: Shift planner**")
        if not ds.job:
            st.caption("Connect your work schedule to plan extra shifts.")
            return
        plan = engine.shift_plan(state.shifts(), state.scenario(subs), ds)
        run_out = plan.before.first_below_zero.value
        if plan.shifts:
            st.markdown(f"**{fmt.md(plan_sentence(plan))}**")
            for p in plan.shifts:
                left, right = st.columns([6, 1], vertical_alignment="center")
                left.markdown(fmt.md(f"{fmt.day(p.shift.date)} · {hours_words(p.shift.hours)} · adds "
                                     f"{fmt.dollars(p.added.value)}. {timing_words(p, run_out)}"))
                right.button("", key=f"shift_rm_{p.shift.date}", icon=":material/close:", type="tertiary",
                             help="Remove this shift", on_click=state.remove_shift, args=(p.shift.date,))
            for monday, h in sorted(plan.week_hours.items()):
                st.caption(f":material/warning: That's {float(h):g} extra hours in the week of {fmt.day(monday)}. "
                           "Make sure you still have time for class.")
        else:
            st.markdown("Try shifts you're thinking of taking. See how much longer your money lasts.")
        if run_out:
            in_time = engine.latest_shift_paid_before(run_out, ds)
            if in_time:
                st.caption(fmt.md(f"A shift worked by {fmt.day(in_time[0].value)} is paid "
                                  f"{fmt.day(in_time[1].value)}, in time."))
        this_sat, next_sat = state.saturday(0), state.saturday(1)
        a, b = st.columns(2)
        a.button("+4h this Saturday", key="shift_add_this", icon=":material/add:", on_click=state.add_shift,
                 args=(this_sat, 4), help=fmt.day(this_sat), width="stretch")
        b.button("+4h next Saturday", key="shift_add_next", icon=":material/add:", on_click=state.add_shift,
                 args=(next_sat, 4), help=fmt.day(next_sat), width="stretch")
        with st.expander("Add a different day"):
            d, h = st.columns([3, 2])
            d.date_input("Day", key="wf_shift_date", format="MM/DD/YYYY")
            h.number_input("Hours", key="wf_shift_hours", min_value=0.5, max_value=12.0, step=0.5)
            st.button("Add shift", key="shift_add", on_click=state.add_typed_shift)
        if s.get("shift_msg"):
            st.caption(f":material/info: {s.shift_msg}")
        if plan.shifts:
            st.button("Reset shifts", key="shift_reset", type="tertiary", icon=":material/restart_alt:",
                      on_click=state.reset_shifts)


def meal_card(ds):
    """The meal plan, compact: what's left, when the dining dollars run out, the swipe tip, and a pace slider."""
    s = st.session_state
    m = engine.meal_plan_status(engine.Scenario(meal_moves=int(s.get("wf_meal_moves") or 0)), ds)
    if not m:
        return
    c = m.c
    with st.container(border=True, key="meal_card"):
        st.markdown("**:material/restaurant: Meal plan**")
        left = (f"{c['swipes_left'].value} swipes and {fmt.dollars(c['dd_left'].value)} in dining dollars left.")
        when = (f"At this pace, your dining dollars run out around {fmt.day(m.runs_out)}." if m.runs_out else
                "At this pace, your dining dollars last the semester.")
        spare = (f"You'll have about {c['swipes_end'].value:.0f} swipes left on {fmt.day(config.SEMESTER_END)}."
                 if c["swipes_end"].value >= 0 else "Your swipes run out before the semester ends.")
        cost = (f"Checking pays {fmt.dollars(c['cost'].value)} for meals." if c["cost"].value else "")
        st.markdown(fmt.md(" ".join(x for x in (left, when, spare, cost) if x)))
        if m.runs_out and m.tip_works and not s.get("wf_meal_moves"):
            st.caption(fmt.md("Tip: use 2 swipes a week instead of dining dollars, and both last."))
        st.slider("Dining-dollar meals a week moved to swipes", min_value=0, max_value=5, key="wf_meal_moves",
                  help="Each move uses a swipe instead of dining dollars.")
