"""My college (Find money tab): her college and city, on or off campus, and how far she can travel for work. Saved on
this computer (college.py) and remembered in "What Runway remembers" (Maya mode; never in My data mode, rule 7)."""
import re

import streamlit as st

import college
from ui import fmt, memory, state


def _form_defaults(c, force=False):
    s = st.session_state
    vals = {"college_name": (c or {}).get("name", ""), "college_city": (c or {}).get("city", ""),
            "college_housing": (c or {}).get("housing", ""), "college_travel": (c or {}).get("travel", "")}
    for k, v in vals.items():
        if force:
            s[k] = v
        else:
            s.setdefault(k, v)


def _changed():
    """Her college changed: forget the online results found for the old one."""
    for k in [k for k in st.session_state.keys() if str(k).startswith(("college_jobs", "college_costs"))]:
        del st.session_state[k]


def _save():
    s = st.session_state
    data = state.college_data()
    problem = college.set_college(data, s.college_name, s.college_city, s.college_housing, s.college_travel)
    if problem:
        s.college_msg = problem
        return
    state.save_college()
    _changed()
    s.college_msg = "Saved."
    memory.college(college.memory_text(data["college"]))
    state.log(f"Set my college: {data['college']['name']}", "college")


def _remove():
    s = st.session_state
    college.remove_college(state.college_data())
    state.save_college()
    _changed()
    _form_defaults(None, force=True)
    s.college_msg = "Removed."
    memory.college(None)
    state.log("Removed my college", "college")


def current():
    return college.current(state.college_data(), state.data_mode())


def where_words(c):
    """"State University" / "Example University, Champaign, IL"."""
    return c["name"] + (f", {c['city']}" if c.get("city") else "")


def setting():
    """The My college card: one line saying what's set, an editor one click away."""
    s, c = st.session_state, current()
    _form_defaults(c)
    with st.container(border=True, key="college_card"):
        st.markdown("**:material/school: My college**")
        if c:
            extra = [college.HOUSING[c["housing"]] if c.get("housing") else "",
                     college.TRAVEL[c["travel"]].lower() if c.get("travel") else ""]
            extra = " · ".join(x for x in extra if x)
            st.markdown(f'<div class="rw-card-text"><b>{fmt.html(where_words(c))}</b>'
                        + (f" · {fmt.html(extra)}" if extra else "") + "</div>", unsafe_allow_html=True)
            if c.get("demo"):
                st.caption("A demo school from Maya's made-up data. Type a real college to search near it.")
        else:
            st.markdown("Add your college to find jobs near campus and your school's published costs.")
        with st.expander("Edit my college", expanded=not c):
            with st.form("college_form", border=False):
                st.text_input("College name", key="college_name", max_chars=college.MAX_NAME,
                              placeholder="For example: University of Illinois Urbana-Champaign")
                st.text_input("City and state", key="college_city", max_chars=college.MAX_CITY,
                              placeholder="For example: Champaign, IL")
                a, b = st.columns(2)
                a.selectbox("Where you live", list(college.HOUSING), key="college_housing",
                            format_func=college.HOUSING.get)
                b.selectbox("How far you can travel for work", list(college.TRAVEL), key="college_travel",
                            format_func=college.TRAVEL.get)
                st.form_submit_button("Save", type="primary", on_click=_save)
            if c:
                st.button("Remove my college", key="college_remove", type="tertiary", icon=":material/delete:",
                          on_click=_remove)
        if s.get("college_msg"):
            st.caption(f":material/info: {s.college_msg}")


# --- Jobs near campus (Find money tab) ----------------------------------------------------------------------------
from datetime import datetime, timedelta  # noqa: E402

import config  # noqa: E402
import engine  # noqa: E402
from ui import background  # noqa: E402

SCHEDULES = {"weekly": "Every week", "biweekly": "Every two weeks"}


def offline():
    """Online search is off in sample mode and in the offline demo (replay)."""
    return config.SAMPLE_MODE or config.ANSWER_MODE.lower() == "replay"


def _jobs_key(c):
    return "college_jobs|" + "|".join((c["name"], c.get("city", ""), c.get("travel", "")))


def found_words(found):
    try:
        t = datetime.fromisoformat(found["found_at"])
    except (KeyError, ValueError, TypeError):
        return ""
    return f"Found {fmt.day(t.date())} at {t:%I:%M %p}".replace(" 0", " ")


def _default_start():
    """A new job's default start: next Monday (she can change it)."""
    t = config.DEMO_TODAY
    return t + timedelta(days=7 - t.weekday())


def _withholding(ds):
    """Taxes withheld: the same share as her current job's pay stubs, else 0 (she can change it)."""
    return float(ds.job.withholding_pct) if ds is not None and ds.job else 0.0


def _job_form_defaults(ds, force=False, pay=None, name=None):
    s = st.session_state
    vals = {"job_rate": float(pay) if pay else None, "job_hours": 10.0, "job_start": _default_start(),
            "job_schedule": "biweekly", "job_tax": _withholding(ds), "job_name": name or "New job"}
    for k, v in vals.items():
        if force:
            s[k] = v
        else:
            s.setdefault(k, v)


def _try(ds, pay=None, name=None):
    """"What if I got this job?": fill the form with what the page states (she checks it), then open it."""
    _job_form_defaults(ds, force=True, pay=pay, name=name)
    st.session_state.job_open, st.session_state.job_what_if = True, None


def _job_from_form():
    s = st.session_state
    if not s.get("job_rate"):
        return None, "Type the pay per hour. Check it on the job page."
    problem = engine.new_job_problem(s.job_rate, s.job_hours or 0, s.job_start, s.job_schedule, s.job_tax)
    if problem:
        return None, problem
    name = " ".join(str(s.get("job_name") or "New job").split())[:40] or "New job"
    return engine.NewJob(engine.D(s.job_rate), engine.Decimal(str(s.job_hours)), s.job_start, s.job_schedule,
                         engine.Decimal(str(s.job_tax or 0)), name), None


def _open_form():
    st.session_state.job_open = True


def _close_form():
    st.session_state.job_open, st.session_state.job_what_if = False, None


def _see():
    job, problem = _job_from_form()
    st.session_state.job_what_if, st.session_state.job_msg = (job, None) if job else (None, problem)


def _add(job):
    college.add_job(state.college_data(), job)
    state.save_college()
    st.session_state.job_what_if = None
    st.session_state.job_msg = "Added to your plan. Your forecast now counts this job."
    state.log(f"Added a job to my plan: {job.name}, {fmt.money(job.hourly_rate)}/hour, {job.hours_per_week} hours a "
              f"week from {fmt.day(job.start)}", "job")


def _remove_job(i):
    college.remove_job(state.college_data(), i)
    state.save_college()
    st.session_state.job_msg = "Removed from your plan."


def job_words(job):
    return (f"{job.name}: {fmt.money(job.hourly_rate)}/hour, {job.hours_per_week:g} hours a week from "
            f"{fmt.day(job.start)}, paid {SCHEDULES[job.schedule].lower()}")


def what_if_lines(w):
    """The what-if in plain sentences, all from the engine (rule 2)."""
    before, after = w.before.first_below_zero.value, w.after.first_below_zero.value
    if not w.first_pay:
        return [f"No paycheck from this job would arrive by {fmt.day(config.SEMESTER_END)}.",
                "So it doesn't change this semester."]
    out = [f"Your first paycheck would come {fmt.day(w.first_pay.value)}."]
    if before:
        out.append(f"That's {'before' if w.before_run_out else 'after'} you run out on {fmt.day(before)}.")
    out.append(f"Your lowest point would be {fmt.balance(w.after.lowest.value)}, instead of "
               f"{fmt.balance(w.before.lowest.value)}.")
    if before and after and after != before:
        out.append(f"You'd run out {fmt.day(after)} instead of {fmt.day(before)}.")
    elif before and after:
        out.append(f"You'd still run out {fmt.day(after)}.")
    elif before:
        out.append("Your money would last the semester.")
    out.append(f"It adds {fmt.dollars(w.total.value)} by {fmt.day(config.SEMESTER_END)}, after taxes withheld.")
    return out


SEARCHING = {"searching": True}


def _search(fn, c, mode=None):
    """The search, never raising: a failure becomes a plain message instead of an error. Job results are also
    kept on this computer for the chat (mode: "maya" or "mine")."""
    try:
        found = fn(c)
    except Exception:
        return {"error": True}
    if mode and found.get("results"):
        try:
            college.save_found(mode, found)
        except OSError:
            pass
    return found


def short_title(title):
    """A job page's title without the site name ("Campus Jobs | The Career Center - ..." -> "Campus Jobs")."""
    return re.split(r"\s[|\-–:]\s", title or "")[0].strip()[:40] or "New job"


def red(text):
    """Escaped HTML with every "... below zero" amount in red (the readability standard)."""
    return re.sub(r"((?:&#36;|\$)[\d,.]+ below zero)", r'<span class="rw-red">\1</span>', fmt.html(text))


def _results(found, ds):
    if found is SEARCHING or (found or {}).get("searching"):
        st.caption(":material/hourglass_top: Searching online. This can take up to a minute.")
        return
    if (found or {}).get("error"):
        st.caption("Search isn't available right now (offline or busy). Try again later, or try your own numbers "
                   "below.")
        return
    if not found or not found.get("results"):
        st.caption("No jobs found online right now. Try again later, or try your own numbers below.")
        return
    for i, r in enumerate(found["results"][:6]):
        meta = [r["employer"]] + ([r["place"]] if r["place"] != college.SEE else [])
        meta += [f"Pay: {r['pay'] if r['pay'] != college.SEE else 'see website'}",
                 f"Hours: {r['hours'] if r['hours'] != college.SEE else 'see website'}"]
        left, right = st.columns([5, 2], vertical_alignment="center")
        left.markdown(f"[{fmt.md(r['title'])}]({r['url']})  \n:gray[{fmt.md(' · '.join(meta))}]")
        right.button("What if I got this job?", key=f"job_try_{i}", type="tertiary", icon=":material/calculate:",
                     on_click=_try, args=(ds, college.pay_number(r["pay"]), short_title(r["title"])))
    st.caption(f"{found_words(found)} with {found.get('provider', 'web search')}. Runway didn't check who can apply "
               "or whether a job is still open. Pay and hours show only when the page says them.")


def _what_if_form(ds, scenario):
    s = st.session_state
    _job_form_defaults(ds)
    if not s.get("job_open"):
        st.button("What if I got a job? Try the numbers", key="job_open_btn", icon=":material/calculate:",
                  on_click=_open_form)
        return
    with st.container(border=True, key="job_whatif"):
        st.markdown("**:material/calculate: What if I got this job?**")
        with st.form("job_form", border=False):
            st.text_input("Job name", key="job_name", max_chars=40)
            a, b = st.columns(2)
            a.number_input("Pay per hour ($)", key="job_rate", min_value=0.0, max_value=float(engine.MAX_RATE),
                           step=0.5, format="%.2f", value=None, placeholder="From the job page")
            b.number_input("Hours a week", key="job_hours", min_value=0.0, max_value=float(engine.MAX_WEEK_HOURS),
                           step=1.0)
            a, b = st.columns(2)
            a.date_input("Start date", key="job_start", min_value=config.DEMO_TODAY + timedelta(days=1),
                         max_value=config.SEMESTER_END, format="MM/DD/YYYY")
            b.selectbox("Paid", list(SCHEDULES), key="job_schedule", format_func=SCHEDULES.get)
            st.number_input("Taxes withheld (%)", key="job_tax", min_value=0.0, max_value=49.0, step=0.5,
                            help="Your current job withholds this much." if ds is not None and ds.job else
                            "0 means before taxes.")
            st.form_submit_button("See what changes", type="primary", on_click=_see)
        st.caption("Each pay period is paid the Friday after it ends. Ask the employer for the real payday.")
        job = s.get("job_what_if")
        if job:
            w = engine.job_what_if(job, scenario, ds, engine.Ledger())
            lines = what_if_lines(w)
            st.markdown(f'<div class="rw-bud-head">{red(lines[0])}</div>'
                        + "".join(f'<div class="rw-card-text">{red(x)}</div>' for x in lines[1:]),
                        unsafe_allow_html=True)
            if w.first_pay:
                st.button("Add to my plan", key="job_add", type="primary", icon=":material/add_task:", on_click=_add,
                          args=(job,))
            st.caption("Nothing changes your forecast unless you click \"Add to my plan\".")
        st.button("Close", key="job_close", type="tertiary", icon=":material/close:", on_click=_close_form)


def jobs_section(ds, scenario):
    """Jobs near campus: found online (check before applying), and a what-if on numbers she confirms."""
    s, c = st.session_state, current()
    st.markdown("#### Jobs near campus")
    st.caption("Found online, check before applying. Runway never applies for you.")
    with st.container(border=True, key="jobs_card"):
        if offline():
            st.caption("Searching online is off in this offline demo. You can still try a job's numbers below.")
        elif not c or not c.get("city"):
            st.caption("Add your college's city in My college to search for jobs near campus.")
        else:
            key = _jobs_key(c)
            if st.button(f"Search for jobs near {c['name']}", key="college_jobs_search", icon=":material/search:"):
                background.forget(key)
                mode = state.data_mode()
                background.start(key, lambda: _search(college.search_jobs, c, mode))
            if key in background._store():
                background.slot(key, SEARCHING, lambda found: _results(found, ds))
            else:
                st.caption("Press the button to search. It can take up to a minute.")
        _what_if_form(ds, scenario)
        added = college.jobs(state.college_data())
        if added:
            st.markdown("**In your plan**")
            for i, job in enumerate(added):
                left, right = st.columns([8, 1], vertical_alignment="center")
                left.markdown(fmt.md(job_words(job)))
                right.button("", key=f"job_rm_{i}", icon=":material/close:", type="tertiary",
                             help="Remove from my plan", on_click=_remove_job, args=(i,))
        if s.get("job_msg"):
            st.caption(f":material/info: {s.job_msg}")
