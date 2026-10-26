"""Tab 4, "Find money": the school's grants, scholarships and work-study she may qualify for, grouped by when the
money would arrive. Every amount is "if approved": an "If approved" switch adds one to the forecast as a what-if,
and nothing here is ever counted as certain money. The UI does no math: eligibility, dates and totals come from
the engine."""
import streamlit as st

import actions
import engine
from ui import checkin, fmt, state

MIME_ICS = checkin.MIME_ICS
TYPE_WORDS = {"emergency_grant": "Grant", "scholarship": "Scholarship", "work_study": "Work-study job"}


def amount_words(x):
    o = x.opp
    if o.type == "work_study":
        return f"${o.hourly_rate:.0f}/hour, up to {o.hours_per_week:.0f} hours a week"
    return (f"Up to {fmt.dollars(x.amount.value)}" if o.max_amount and not o.amount else fmt.dollars(x.amount.value))


def arrival_words(x):
    o = x.opp
    when = fmt.day(x.arrives.value)
    if o.type == "work_study":
        return f"If you're hired, your first paycheck comes {when}."
    if x.this_semester and not x.this_semester.value:
        return f"If approved, it's paid {when}, after the semester, so it adds $0.00 this semester."
    return f"If approved, it arrives around {when}."


def why_words(x, prof):
    if x.status == "almost":
        return f"You'd need {x.missing[0]}."
    reasons = (["Pell-eligible"] if x.opp.pell_required or x.opp.need_based else []) +         ([f"a {prof.class_year}"] if x.opp.class_years else []) + [prof.enrollment]
    head = "You qualify: you're " + ", ".join(reasons[:-1]) + (" and " if len(reasons) > 1 else "") + reasons[-1] + "."
    return head + (" Your FAFSA is on file." if x.opp.fafsa_required else "")


def deadline_words(o):
    return f"Apply by {fmt.day(o.deadline)}" if o.deadline else "Apply anytime"


def situation(ds, x):
    """One true sentence for an emergency grant application, from the engine (the gap it would cover)."""
    if x.opp.type != "emergency_grant":
        return ""
    item = next((it for it in engine.attention_items(engine.Scenario(), ds) if it.kind == "run_out"), None)
    if not item or "payment" not in item.facts:
        return ""
    f = item.facts
    return (f"My {fmt.dollars(f['payment'].value)} card payment is due {fmt.day(item.due.value)}, and my checking "
            f"account will be {fmt.balance(f['after'].value)} that day.")


def _reminder(x):
    o = x.opp
    day = o.deadline or x.apply_on
    return actions.ics([actions.Reminder(f"apply-{o.row_id.lower()}", f"Apply: {o.name}", day, actions.REMINDER_TIME,
                                         f"{deadline_words(o)}. {arrival_words(x)}")])


def card(x, ds, scenario):
    o, key = x.opp, x.opp.row_id
    with st.container(border=True, key=f"fm_card_{key}"):
        st.markdown(f'<div class="rw-ci-title">{fmt.html(o.name)}</div>'
                    f'<div class="rw-fm-meta">{fmt.html(TYPE_WORDS.get(o.type, ""))} · '
                    f'{fmt.html(amount_words(x))} · {fmt.html(deadline_words(o))}</div>'
                    f'<div class="rw-ci-text">{fmt.html(arrival_words(x))} {fmt.html(why_words(x, ds.profile))}</div>',
                    unsafe_allow_html=True)
        if x.status != "eligible":
            return
        to, subject, body = actions.application(x, ds, situation(ds, x))
        with st.container(horizontal=True, gap="xsmall", key=f"fm_acts_{key}"):
            with st.popover("Draft my application", icon=":material/edit_note:", type="tertiary"):
                st.markdown(f"**To:** {fmt.md(to)}  \n**Subject:** {fmt.md(subject)}")
                st.caption("A demo address: Maya's data is made up. Use your school's real address.")
                st.link_button("Open in my email app", actions.mailto(to, subject, body), icon=":material/open_in_new:",
                               key=f"fm_mail_{key}", on_click=state.log,
                               args=(f"Opened the application for {o.name} in the email app (not sent by Runway)",))
                st.code(body, language=None, wrap_lines=True)
                st.caption("Or copy it with the button above. Runway never sends anything.")
            st.download_button("Remind", _reminder(x), file_name=f"runway-apply-{key.lower()}.ics", mime=MIME_ICS,
                               type="tertiary", icon=":material/event:", key=f"fm_cal_{key}", on_click=state.log,
                               args=(f"Downloaded a reminder to apply for {o.name}",))
            helps = x.this_semester is not None and x.this_semester.value > 0
            st.toggle("If approved", key=state.approved_key(key), disabled=not helps,
                      help="Adds it to your forecast as a what-if. It isn't certain money." if helps else
                      "It pays after the semester, so it doesn't change this semester's forecast." if x.this_semester
                      else "Work-study pay depends on the hours you work.")


def render(ds, scenario):
    checks = engine.eligible_opportunities(None, scenario, ds)
    if not checks:
        st.caption("No aid opportunities loaded.")
        return
    total = engine.opportunities_total(checks, engine.Ledger())
    eligible = [x for x in checks if x.status == "eligible"]
    with_amount = [x for x in eligible if x.amount]
    extra = len(eligible) - len(with_amount)
    head = (f"You may qualify for {len(with_amount)} opportunit{'ies' if len(with_amount) != 1 else 'y'} worth up to "
            f"{fmt.dollars(total.value)}" + (", plus a work-study job" if extra else "") + ".")
    st.markdown(f'<div class="rw-bud-line">{fmt.html(head)}</div>', unsafe_allow_html=True)
    st.caption("Nothing here is certain until it's approved, so none of it is in your forecast unless you switch on "
               "\"If approved\".")
    groups = [("Could help before you run out", [x for x in eligible if x.before_run_out]),
              ("Helps later", [x for x in eligible if not x.before_run_out]),
              ("Almost (what you'd need)", [x for x in checks if x.status == "almost"])]
    for title, items in groups:
        if not items:
            continue
        st.markdown(f"#### {title}")
        cols = st.columns(2)
        for i, x in enumerate(items):
            with cols[i % 2]:
                card(x, ds, scenario)
    others = [x for x in checks if x.status == "not_eligible"]
    if others:
        st.caption(f"{len(others)} more you don't qualify for: " + ", ".join(x.opp.name for x in others) + ".")
    if scenario.approved:
        st.caption(f"Your forecast now includes {len(scenario.approved)} \"if approved\" what-if"
                   f"{'s' if len(scenario.approved) != 1 else ''}. Turn them off to see it without.")
